PYTHON ?= python

.PHONY: comments-check
.PHONY: test-agent-approval eval-agent-live eval-agent install run-server run-worker lint format-check typecheck test test-integration test-mysql bench-backend test-operations check init-data db-upgrade neo4j-sync docker-up docker-up-ingestion docker-down docker-smoke help

install:
	python -m pip install -r requirements.txt

run-server:
	python -m uvicorn safemeal.main:application --host 0.0.0.0 --port 8000 --reload

run-worker:
	python -m safemeal.infrastructure.ingestion.worker

lint:
	python -m ruff check safemeal tests

format-check:
	python -m ruff format --check safemeal tests

typecheck:
	python -m mypy safemeal

test:
	PYTHONPATH=. python -m pytest -q

test-integration:
	RUN_TESTCONTAINERS=1 PYTHONPATH=. python -m pytest -m testcontainers -q

# Always creates owned temporary containers; never accepts a user's DATABASE_URL.
test-mysql:
	RUN_MYSQL_INTEGRATION=1 PYTHONPATH=. python -m pytest tests/integration/test_mysql_backend.py -q --junitxml=evaluation_results/mysql_integration_pytest.xml

# Fixed synthetic catalog/facts; real HTTP, SQL plans, no external DATABASE_URL.
bench-backend:
	RUN_BACKEND_PERFORMANCE=1 RUN_MYSQL_INTEGRATION=1 PYTHONPATH=. python -m pytest tests/integration/test_backend_performance.py -q -s --junitxml=evaluation_results/backend_performance_pytest.xml

test-operations:
	RUN_MYSQL_INTEGRATION=1 PYTHONPATH=. python -m pytest tests/backend/test_operations_metrics.py tests/integration/test_backend_operations.py -q --junitxml=evaluation_results/backend_operations_pytest.xml

comments-check:
	$(PYTHON) scripts/check_backend_comments.py

check: lint format-check typecheck comments-check test

init-data:
	mkdir -p data/runtime uploads

db-upgrade:
	alembic upgrade head

neo4j-sync:
	python -m safemeal.infrastructure.retrieval.neo4j.dietary_migration

docker-up:
	docker compose up -d --wait

# 文档上传/向量入库需要 EMBEDDING_API_KEY；普通 Agent 测试无需启动。
docker-up-ingestion:
	docker compose --profile ingestion up -d --wait

docker-down:
	docker compose down

docker-smoke:
	docker compose config --quiet
	docker build -t safemeal:smoke .

help:
	@echo "make install       - install backend dependencies"
	@echo "make run-server    - start the local API"
	@echo "make check         - run lint, type checking and tests"
	@echo "make comments-check - verify Chinese backend class/method comments"
	@echo "make test-operations - metrics and owned Redis outage/recovery drill"
	@echo "make bench-backend - isolated HTTP/SQL performance and cache experiment"
	@echo "make test-mysql    - real MySQL/Redis migrations, concurrency and recovery"
	@echo "make db-upgrade    - apply Alembic migrations"
	@echo "make neo4j-sync    - import the domain recipe graph"
	@echo "make docker-up     - start the core Agent stack"
	@echo "make docker-up-ingestion - additionally start document ingestion (requires embeddings)"
	@echo "make docker-down   - stop the local stack"

# Offline deterministic contracts, no provider calls or production data.
eval-agent:
	PYTHONPATH=. python scripts/evaluate_agent_contracts.py --split test --repeats 3 --output evaluation_results/agent_contract_frozen_test.json

# Explicit real-provider evaluation; creates only owned temporary data.
eval-agent-live:
	PYTHONPATH=. python scripts/evaluate_agent_live.py --allow-provider-calls --repeats 3 --output evaluation_results/agent_live_baselines.json

# Persistent approval lifecycle without external model calls.
test-agent-approval:
	DATABASE_URL=sqlite+pysqlite:///:memory: pytest -q tests/refactor/test_approval_flow.py --junitxml=evaluation_results/agent_approval_cases.xml
	PYTHONPATH=. python scripts/evaluate_agent_approval.py
	cd web && npm test && npm run build

# Offline reference ablation; opt-in provider runs are separate CLI commands.
.PHONY: test-agent-retrieval
test-agent-retrieval:
	$(PYTHON) -m pytest tests/refactor/test_retrieval_quality.py -q
	$(PYTHON) scripts/evaluate_agent_retrieval.py --reference --cache evaluation_results/agent_retrieval_reference_cache.json
