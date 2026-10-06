"""实现知识与菜谱检索基础设施适配。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from safemeal.config.settings import settings
from safemeal.infrastructure.retrieval.neo4j.recipe_graph import RecipeGraphDatabase
from safemeal.infrastructure.retrieval.neo4j.importers.recipe_importer import (
    RecipeGraphImporter,
)


def run(*, source: Path, output: Path) -> dict:
    database = RecipeGraphDatabase(
        settings.NEO4J_URI,
        settings.NEO4J_USER,
        settings.NEO4J_PASSWORD,
        database=settings.NEO4J_DATABASE,
        connection_timeout=settings.NEO4J_CONNECTION_TIMEOUT,
    )
    try:
        report = dict(
            RecipeGraphImporter(database).sync_dietary_safety_from_json(source)
        )
    finally:
        database.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=Path(settings.NEO4J_RECIPE_JSON_PATH)
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/runtime/neo4j-dietary-closure.json"),
    )
    args = parser.parse_args(argv)
    report = run(source=args.source, output=args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["closure_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
