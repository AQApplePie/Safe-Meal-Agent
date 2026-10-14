"""Grounded answer probe using only the frozen public FDA summary, never user files."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")


async def main(output):
    from loguru import logger

    logger.remove()
    from safemeal.bootstrap.composition.model_factory import (
        create_language_model_gateway,
    )
    from safemeal.agent.contracts.decisions import Observation
    from safemeal.agent.runtime.observability import observe_request
    from safemeal.agent.runtime.aggregation.sources import collect_answer_sources

    path = ROOT / "tests/evaluation/datasets/retrieval_v1.json"
    data = json.loads(path.read_text())
    doc = data["documents"][0]
    assert doc["tenant_id"] == "public" and doc["id"] == "D01"
    observation = Observation(
        call_id="public-fda-probe",
        tool_name="search_knowledge",
        purpose="寻找鱼类组胺依据",
        success_criteria="原文依据",
        ok=True,
        has_data=True,
        summary="FDA 摘要",
        data={
            "documents": [
                dict(
                    id="D01_0",
                    document_id="D01",
                    content=doc["content"],
                    metadata={"source": doc["source"], "tenant_id": "public"},
                )
            ]
        },
    )
    gateway = create_language_model_gateway(
        decision_temperature=0, answer_temperature=0
    )
    rows = []
    try:
        for repeat in range(3):
            for q in data["queries"][:2]:
                with observe_request() as usage:
                    answer = await gateway.answer(
                        q["query"], [], [observation], "已检索到 FDA 摘要", True, []
                    )
                rows.append(
                    dict(
                        case_id=q["id"],
                        repeat=repeat,
                        answer=answer,
                        sources=[
                            s.model_dump()
                            for s in collect_answer_sources([observation])
                        ],
                        observability=usage.snapshot(),
                    )
                )
                output.write_text(
                    json.dumps(
                        dict(
                            dataset_sha256=hashlib.sha256(
                                path.read_bytes()
                            ).hexdigest(),
                            rows=rows,
                            complete=False,
                        ),
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n"
                )
    finally:
        await gateway.close()
    output.write_text(
        json.dumps(
            dict(
                dataset_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                rows=rows,
                complete=True,
                scope="actual production answer gateway with manually supplied frozen FDA chunk; not full retrieval or HTTP graph",
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print("completed", len(rows), "public grounded answers")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-provider-calls", action="store_true", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "evaluation_results/agent_retrieval_grounded_answers.json",
    )
    asyncio.run(main(parser.parse_args().output))
