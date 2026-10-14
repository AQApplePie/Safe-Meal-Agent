"""Reproducible, opt-in HTTP/SQL experiment against fixture-owned infrastructure."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock, Thread
import json
import os
import platform
import socket
import statistics
import subprocess
import time

from fastapi import FastAPI, Request
import httpx
import pytest
from sqlalchemy import event, text
import uvicorn

from safemeal.infrastructure.cache.recipe_repository import CachedRecipeRepository
from safemeal.infrastructure.cache.ranking_store import RedisRankingStore
from safemeal.infrastructure.persistence.behavior_outbox import SqlBehaviorOutbox
from safemeal.infrastructure.persistence.recipe_repository import (
    SqlAlchemyRecipeRepository,
)
from safemeal.infrastructure.persistence.ranking_repository import (
    SqlAlchemyRankingRepository,
)
from safemeal.infrastructure.persistence.reaction_repository import (
    SqlAlchemyReactionRepository,
)
from safemeal.interfaces.http.routers import recipes, rankings, interactions
from safemeal.interfaces.http.authentication import get_interaction_actor
from safemeal.interfaces.http.platform_dependencies import (
    get_recipe_browse_service,
    get_ranking_service,
    get_interaction_service,
)
from safemeal.modules.recipe.application.recipe_service import RecipeService
from safemeal.modules.interaction.application.ranking_service import RankingService
from safemeal.modules.interaction.application.interaction_service import (
    InteractionService,
)
from safemeal.modules.interaction.contracts.models import InteractionActor
from test_mysql_backend import services, docker  # noqa: F401

pytestmark = [
    pytest.mark.integration,
    pytest.mark.testcontainers,
    pytest.mark.skipif(
        os.environ.get("RUN_BACKEND_PERFORMANCE") != "1",
        reason="set RUN_BACKEND_PERFORMANCE=1 and RUN_MYSQL_INTEGRATION=1",
    ),
]
ENVIRONMENT_REPORT = "backend_performance_environment.json"
ROOT = Path(__file__).resolve().parents[2]


class Counter:
    def __init__(self):
        self.lock = Lock()
        self.value = 0

    def add(self, *args):
        with self.lock:
            self.value += 1


class ObservedRepository:
    def __init__(self, repository):
        self.repository = repository
        self.loads = Counter()

    def search(self, query):
        self.loads.add()
        return self.repository.search(query)

    def get(self, recipe_id):
        self.loads.add()
        return self.repository.get(recipe_id)


def percentile(values, fraction):
    # Linear interpolation, same definition across all runs; no extrapolated capacity.
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    return ordered[lower] + (
        ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]
    ) * (position - lower)


def sql_experiment(connection, before, after, parameters):
    result = {}
    assert (
        connection.execute(text(before), parameters).all()
        == connection.execute(text(after), parameters).all()
    )
    for name, statement in (("before", before), ("after", after)):
        result[name] = {
            "sql": statement,
            "explain_analyze": connection.execute(
                text("EXPLAIN ANALYZE " + statement), parameters
            ).scalar_one(),
        }
    # Alternate ordering to reduce warm-buffer/order bias; ten repeats after warm-up.
    samples = {"before": [], "after": []}
    for repetition in range(10):
        variants = (("before", before), ("after", after))
        for name, statement in variants if repetition % 2 == 0 else reversed(variants):
            started = time.perf_counter()
            connection.execute(text(statement), parameters).all()
            samples[name].append((time.perf_counter() - started) * 1000)
    for name in samples:
        result[name].update(
            samples_ms=samples[name], median_ms=statistics.median(samples[name])
        )
    return result


def seed(engine):
    # Dedicated database only. Deterministic generated values, no downloaded data.
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE benchmark_digits (n INT PRIMARY KEY)"))
        conn.execute(
            text(
                "INSERT INTO benchmark_digits VALUES (0),(1),(2),(3),(4),(5),(6),(7),(8),(9)"
            )
        )
        conn.execute(text("CREATE TABLE benchmark_numbers (n INT PRIMARY KEY)"))
        conn.execute(
            text(
                "INSERT INTO benchmark_numbers SELECT a.n+10*b.n+100*c.n+1000*d.n+10000*e.n+100000*f.n FROM benchmark_digits a CROSS JOIN benchmark_digits b CROSS JOIN benchmark_digits c CROSS JOIN benchmark_digits d CROSS JOIN benchmark_digits e CROSS JOIN benchmark_digits f"
            )
        )
        conn.execute(
            text(
                "INSERT INTO recipes (id,name,description,total_time,servings,difficulty,total_calories) SELECT 1001+n, CONCAT('benchmark-',LPAD(n,6,'0')), 'Synthetic benchmark recipe', 5+MOD(n,116), 2, ELT(1+MOD(n,3),'easy','medium','hard'),100+MOD(n,600) FROM benchmark_numbers WHERE n<100000"
            )
        )
        conn.execute(
            text(
                "INSERT INTO recipe_steps(recipe_id,step_number,action,instruction,duration) SELECT 1001+n,1,'cook','Synthetic benchmark instruction',5 FROM benchmark_numbers WHERE n<100000"
            )
        )
        conn.execute(
            text(
                "INSERT INTO recipe_ingredients(recipe_id,ingredient_id,quantity,unit,is_main,ingredient_type) SELECT 1001+n,(SELECT MIN(id) FROM ingredients),'100','g',1,'main' FROM benchmark_numbers WHERE n<100000"
            )
        )
        conn.execute(
            text(
                "INSERT INTO recipe_reactions(tenant_id,subject,recipe_id,kind) SELECT 'benchmark',CONCAT('subject-',n),1001+MOD(n,100000),'like' FROM benchmark_numbers WHERE n<500000"
            )
        )
        conn.execute(
            text(
                "INSERT INTO recipe_view_history(tenant_id,subject,recipe_id,last_viewed_at) SELECT 'benchmark',CONCAT('subject-',n),1001+MOD(n,100000),UTC_TIMESTAMP(6) FROM benchmark_numbers WHERE n<500000"
            )
        )
    with engine.connect() as conn:
        for table in ("recipes", "recipe_reactions", "recipe_view_history"):
            conn.execute(text("ANALYZE TABLE " + table)).all()


def test_http_and_sql_performance(services):  # noqa: F811
    evidence = {
        "method": "direct loopback TCP HTTP, trust_env=False; closed-loop, one uvicorn worker; auth dependency replaced by fixed/per-client actor; workers disabled; MySQL/Redis real",
        "machine": {
            "system": platform.system(),
            "architecture": platform.machine(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
        },
        "workloads": [],
        "seed": {
            "generated_recipes": 100000,
            "original_recipes": 70,
            "reaction_facts": 500000,
            "view_facts": 500000,
            "ingredients_per_generated_recipe": 1,
            "steps_per_generated_recipe": 1,
        },
        "warmup_seconds": 1,
        "measurement_seconds": 5,
        "concurrency": [1, 8],
        "cache_ttl_seconds": 60,
        "local_cache_ttl_seconds": 1,
    }
    started = time.monotonic()
    seed(services.engine)
    evidence["seed_seconds"] = time.monotonic() - started
    before = "SELECT r.id,r.name,COUNT(*) AS score FROM recipes r JOIN recipe_reactions f ON f.recipe_id=r.id WHERE f.tenant_id=:tenant GROUP BY r.id,r.name ORDER BY score DESC,r.id DESC LIMIT 1001"
    after = "SELECT r.id,r.name,f.score FROM recipes r JOIN (SELECT recipe_id,COUNT(*) AS score FROM recipe_reactions WHERE tenant_id=:tenant GROUP BY recipe_id) f ON f.recipe_id=r.id ORDER BY f.score DESC,r.id DESC LIMIT 1001"
    with services.engine.connect() as conn:
        evidence["exact_row_counts"] = {
            table: conn.execute(text("SELECT COUNT(*) FROM " + table)).scalar_one()
            for table in ("recipes", "recipe_reactions", "recipe_view_history")
        }
        assert evidence["exact_row_counts"] == {
            "recipes": 100070,
            "recipe_reactions": 500000,
            "recipe_view_history": 500000,
        }
        evidence["list_count_sql"] = sql_experiment(
            conn,
            "SELECT COUNT(r.id) FROM recipes r IGNORE INDEX (ix_recipe_browse_difficulty_time_id) LEFT JOIN cuisines c ON c.id=r.cuisine_id WHERE r.difficulty='easy' AND r.total_time<=30",
            "SELECT COUNT(r.id) FROM recipes r IGNORE INDEX (ix_recipe_browse_difficulty_time_id) WHERE r.difficulty='easy' AND r.total_time<=30",
            {},
        )
        evidence["difficulty_time_index_count_sql"] = sql_experiment(
            conn,
            "SELECT COUNT(id) FROM recipes IGNORE INDEX (ix_recipe_browse_difficulty_time_id) WHERE difficulty='easy' AND total_time<=30",
            "SELECT COUNT(id) FROM recipes WHERE difficulty='easy' AND total_time<=30",
            {},
        )
        evidence["difficulty_time_index_page_sql"] = sql_experiment(
            conn,
            "SELECT id,name,total_time FROM recipes IGNORE INDEX (ix_recipe_browse_difficulty_time_id) WHERE difficulty='easy' AND total_time<=30 ORDER BY total_time,id LIMIT 20",
            "SELECT id,name,total_time FROM recipes WHERE difficulty='easy' AND total_time<=30 ORDER BY total_time,id LIMIT 20",
            {},
        )
        evidence["ranking_sql"] = sql_experiment(
            conn, before, after, {"tenant": "benchmark"}
        )
        evidence["list_sql"] = {
            "filter_and_sort": conn.execute(
                text(
                    "EXPLAIN ANALYZE SELECT id,name,total_time FROM recipes WHERE difficulty='easy' AND total_time<=30 ORDER BY total_time,id LIMIT 20"
                )
            ).scalar_one(),
            "deep_offset": conn.execute(
                text(
                    "EXPLAIN ANALYZE SELECT id,name FROM recipes ORDER BY name,id LIMIT 20 OFFSET 90000"
                )
            ).scalar_one(),
            "count": conn.execute(
                text(
                    "EXPLAIN ANALYZE SELECT COUNT(r.id) FROM recipes r LEFT JOIN cuisines c ON c.id=r.cuisine_id"
                )
            ).scalar_one(),
        }
        evidence["storage"] = [
            dict(row._mapping)
            for row in conn.execute(
                text(
                    "SELECT table_name,table_rows,data_length,index_length FROM information_schema.tables WHERE table_schema=DATABASE() ORDER BY table_name"
                )
            )
        ]
    sql_count = Counter()
    event.listen(services.engine, "before_cursor_execute", sql_count.add)
    app = FastAPI()
    app.include_router(rankings.router, prefix="/api/v1/recipes")
    app.include_router(recipes.router, prefix="/api/v1/recipes")
    app.include_router(interactions.router, prefix="/api/v1/recipes")
    observed = ObservedRepository(SqlAlchemyRecipeRepository(services.engine))
    configuration = {}
    app.dependency_overrides[get_recipe_browse_service] = lambda: configuration[
        "recipes"
    ]
    app.dependency_overrides[get_ranking_service] = lambda: configuration["rankings"]
    app.dependency_overrides[get_interaction_service] = lambda: InteractionService(
        SqlAlchemyReactionRepository(
            services.engine, outbox=SqlBehaviorOutbox(services.engine)
        )
    )

    def actor(request: Request):
        return InteractionActor(
            tenant_id="benchmark",
            subject=request.headers.get("x-benchmark-subject", "benchmark-reader"),
        )

    app.dependency_overrides[get_interaction_actor] = actor
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline
        time.sleep(0.01)
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}",
            timeout=60,
            trust_env=False,
            limits=httpx.Limits(max_connections=32, max_keepalive_connections=32),
        ) as client:
            for cache_mode in ("disabled", "redis_only", "redis_and_l1"):
                services.redis.flushdb()
                repository = (
                    observed
                    if cache_mode == "disabled"
                    else CachedRecipeRepository(
                        observed,
                        services.redis,
                        local_ttl_seconds=0 if cache_mode == "redis_only" else 1,
                    )
                )
                configuration["recipes"] = RecipeService(repository)
                store = (
                    None
                    if cache_mode == "disabled"
                    else RedisRankingStore(services.redis)
                )
                configuration["rankings"] = RankingService(
                    SqlAlchemyRankingRepository(services.engine), store
                )
                if store is not None:
                    assert configuration["rankings"].refresh_tenant("benchmark")
                for workload, path in (
                    (
                        "list",
                        "/api/v1/recipes?difficulties=easy&max_total_time_minutes=30&sort_by=total_time&limit=20",
                    ),
                    ("detail", "/api/v1/recipes/1001"),
                    ("ranking", "/api/v1/recipes/rankings?mode=popular&limit=20"),
                    ("write", "/api/v1/recipes/1001/like"),
                ):
                    # Writes unaffected by recipe cache: run once rather than misleading comparisons.
                    if workload == "write" and cache_mode != "disabled":
                        continue
                    for concurrency in (1, 8):

                        def request(worker, index):
                            if workload == "write":
                                response = client.request(
                                    "PUT" if index % 2 == 0 else "DELETE",
                                    path,
                                    headers={
                                        "x-benchmark-subject": f"load-worker-{worker}"
                                    },
                                )
                            else:
                                response = client.get(path)
                            assert response.status_code == 200, (
                                workload,
                                response.status_code,
                            )
                            payload = response.json()
                            if workload == "detail":
                                assert payload["id"] == 1001
                            elif workload == "list":
                                assert (
                                    len(payload["items"]) == 20 and payload["total"] > 0
                                )
                            elif workload == "ranking":
                                assert (
                                    len(payload["items"]) == 20
                                    and payload["items"][0]["score"] >= 5
                                )
                            else:
                                assert payload["liked"] == (index % 2 == 0)

                        if concurrency == 1 and workload in ("list", "detail"):
                            cold_barrier = Barrier(8)
                            cold_loads = observed.loads.value
                            cold_sql = sql_count.value

                            def first_wave(n):
                                cold_barrier.wait()
                                tick = time.perf_counter()
                                request(n, 0)
                                return (time.perf_counter() - tick) * 1000

                            with ThreadPoolExecutor(max_workers=8) as burst:
                                cold_latencies = list(burst.map(first_wave, range(8)))
                            evidence.setdefault("cold_first_wave", []).append(
                                {
                                    "workload": workload,
                                    "cache_mode": cache_mode,
                                    "requests": 8,
                                    "concurrency": 8,
                                    "latencies_ms": cold_latencies,
                                    "repository_loads": observed.loads.value
                                    - cold_loads,
                                    "sql_statements": sql_count.value - cold_sql,
                                }
                            )
                            assert observed.loads.value - cold_loads == (
                                8 if cache_mode == "disabled" else 1
                            )
                        # Warm buffers/cache/connections; warm-up excluded from SQL/load counters.
                        warm_end = time.monotonic() + 1
                        index = 0
                        while time.monotonic() < warm_end:
                            request(99, index)
                            index += 1
                        sql_start, load_start = sql_count.value, observed.loads.value
                        barrier = Barrier(concurrency + 1)

                        def worker(worker_id):
                            latencies = []
                            errors = 0
                            error_examples = []
                            barrier.wait()
                            stop = time.monotonic() + 5
                            index = 0
                            while time.monotonic() < stop:
                                tick = time.perf_counter()
                                try:
                                    request(worker_id, index)
                                except Exception as exc:
                                    errors += 1
                                    if len(error_examples) < 3:
                                        error_examples.append(
                                            type(exc).__name__ + ": " + str(exc)[:200]
                                        )
                                latencies.append((time.perf_counter() - tick) * 1000)
                                index += 1
                            return latencies, errors, error_examples

                        resources = {}

                        def sample_resources():
                            time.sleep(2)
                            try:
                                resources["docker_stats_at_2s"] = [
                                    json.loads(line)
                                    for line in docker(
                                        "stats",
                                        "--no-stream",
                                        "--format",
                                        "{{json .}}",
                                        *services.evidence["container_names"],
                                    ).splitlines()
                                ]
                            except Exception as exc:
                                resources["sampling_error"] = type(exc).__name__

                        sampler = Thread(target=sample_resources, daemon=True)
                        with ThreadPoolExecutor(max_workers=concurrency) as pool:
                            futures = [
                                pool.submit(worker, n) for n in range(concurrency)
                            ]
                            tick = time.perf_counter()
                            barrier.wait()
                            sampler.start()
                            results = [future.result() for future in futures]
                            elapsed = time.perf_counter() - tick
                        sampler.join(timeout=10)
                        latencies = [
                            value for values, _, _ in results for value in values
                        ]
                        errors = sum(error for _, error, _ in results)
                        loads = observed.loads.value - load_start
                        record = {
                            "workload": workload,
                            "cache_mode": cache_mode,
                            "concurrency": concurrency,
                            "resources": resources,
                            "requests": len(latencies),
                            "errors": errors,
                            "error_examples": [
                                message
                                for _, _, messages in results
                                for message in messages
                            ],
                            "error_rate": errors / len(latencies),
                            "elapsed_seconds": elapsed,
                            "requests_per_second": len(latencies) / elapsed,
                            "p50_ms": percentile(latencies, 0.5),
                            "p95_ms": percentile(latencies, 0.95),
                            "p99_ms": percentile(latencies, 0.99),
                            "sql_statements": sql_count.value - sql_start,
                            "repository_loads": loads,
                            "recipe_cache_hit_ratio": 1 - loads / len(latencies)
                            if workload in ("list", "detail")
                            else None,
                        }
                        evidence["workloads"].append(record)
                        (
                            ROOT / "evaluation_results/backend_performance.json"
                        ).write_text(
                            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
                        )
                        print(json.dumps(record), flush=True)
                        assert errors == 0
                        assert "sampling_error" not in resources
                        assert not sampler.is_alive()
                        if workload in ("list", "detail"):
                            assert sql_count.value - sql_start == loads * (
                                4 if workload == "list" else 3
                            )
                            if cache_mode != "disabled":
                                assert loads == 0
            evidence["docker_resources_end_snapshot"] = json.loads(
                "["
                + ",".join(
                    docker(
                        "stats",
                        "--no-stream",
                        "--format",
                        "{{json .}}",
                        *services.evidence["container_names"],
                    ).splitlines()
                )
                + "]"
            )
            evidence["redis_memory"] = services.redis.info("memory")["used_memory"]
            evidence["api_and_load_generator_shared_process_end_rss_bytes"] = (
                int(
                    subprocess.check_output(
                        ["ps", "-o", "rss=", "-p", str(os.getpid())], text=True
                    ).strip()
                )
                * 1024
            )
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        event.remove(services.engine, "before_cursor_execute", sql_count.add)
        evidence["http_server_stopped"] = not thread.is_alive()
        (ROOT / "evaluation_results/backend_performance.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2) + "\n"
        )
