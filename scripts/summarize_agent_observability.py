"""Summarize isolated live evaluation timing; nearest-rank p95 is descriptive."""

import argparse
import json
import math
from pathlib import Path
from statistics import median


def summarize(report):
    groups = {}
    for row in report["rows"]:
        for output in row["outputs"]:
            if row["system"] != "production_agent":
                continue
            observation = output.get("metadata", {}).get("observability")
            if observation is None:
                raise ValueError("production response has no observation")
            groups.setdefault(row["case_id"], []).append((output, observation))
    result = {}
    for case, entries in groups.items():
        timings = sorted(o["duration_ms"] for _, o in entries)
        result[case] = {
            "requests": len(entries),
            "workflow_p50_ms": median(timings),
            "workflow_p95_ms": timings[math.ceil(len(timings) * 0.95) - 1],
            "http_p50_ms": median(o["seconds"] * 1000 for o, _ in entries),
            "model_calls": sum(o["model_call_count"] for _, o in entries),
            "input_tokens": sum(o["input_tokens"] for _, o in entries),
            "output_tokens": sum(o["output_tokens"] for _, o in entries),
            "cached_input_tokens": sum(o["cached_input_tokens"] for _, o in entries),
            "usage_complete": all(o["usage_complete"] for _, o in entries),
            "cost_complete": all(o["cost_complete"] for _, o in entries),
            "estimated_cost": sum(o["estimated_cost"] for _, o in entries)
            if all(o["cost_complete"] for _, o in entries)
            else None,
        }
    return {
        "source": "isolated live benchmark",
        "groups": result,
        "limits": [
            "3 samples per case; p95 equals sample maximum",
            "Workflow duration excludes HTTP authentication and persistence",
            "SDK internal retries are included in duration, not individually counted",
            "Configured prices are estimates, not provider billing records",
        ],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = summarize(json.loads(args.input.read_text()))
    args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
