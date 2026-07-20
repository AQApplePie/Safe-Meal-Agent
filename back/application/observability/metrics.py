"""Bounded-cardinality Prometheus metrics for the Agent runtime."""

from prometheus_client import Counter, Gauge, Histogram


AGENT_RUNS = Counter(
    "safemeal_agent_runs_total",
    "Completed Agent runs by outcome.",
    ("status",),
)
AGENT_DURATION = Histogram(
    "safemeal_agent_run_duration_seconds",
    "End-to-end Agent run latency.",
)
AGENT_ITERATIONS = Histogram(
    "safemeal_agent_iterations",
    "Tool-loop iterations per Agent run.",
    buckets=(0, 1, 2, 3, 4, 6, 10, 20),
)
AGENT_TOKENS = Counter(
    "safemeal_agent_tokens_total",
    "Model tokens consumed by Agent runs.",
    ("model", "direction"),
)
AGENT_COST = Counter(
    "safemeal_agent_cost_total",
    "Estimated Agent model cost in configured currency units.",
    ("model", "currency"),
)
MODEL_CALLS = Counter(
    "safemeal_model_calls_total",
    "Model calls by stage, model and outcome.",
    ("stage", "model", "status"),
)
MODEL_LATENCY = Histogram(
    "safemeal_model_call_duration_seconds",
    "Model call latency.",
    ("stage", "model"),
)
TOOL_CALLS = Counter(
    "safemeal_tool_calls_total",
    "Tool calls by tool and stable status.",
    ("tool", "status"),
)
TOOL_LATENCY = Histogram(
    "safemeal_tool_call_duration_seconds",
    "Tool call latency.",
    ("tool",),
)
RATE_LIMIT_DECISIONS = Counter(
    "safemeal_rate_limit_decisions_total",
    "Rate-limit decisions by layer and outcome.",
    ("layer", "outcome"),
)
QUEUE_WAIT = Histogram(
    "safemeal_distributed_queue_wait_seconds",
    "Time spent waiting for a distributed concurrency lease.",
    ("queue", "outcome"),
)
QUEUE_ACTIVE = Gauge(
    "safemeal_distributed_queue_active",
    "Distributed concurrency leases observed after admission.",
    ("queue",),
)
QUEUE_DEPTH = Gauge(
    "safemeal_distributed_queue_depth",
    "Distributed queue depth observed while waiting.",
    ("queue",),
)
CIRCUIT_EVENTS = Counter(
    "safemeal_model_circuit_events_total",
    "Provider circuit-breaker and failover events.",
    ("provider", "event"),
)
TRACE_PERSISTENCE = Counter(
    "safemeal_agent_trace_persistence_total",
    "Durable Agent trace persistence outcomes.",
    ("outcome",),
)
FEEDBACK_SUBMISSIONS = Counter(
    "safemeal_answer_feedback_total",
    "Persisted answer feedback by rating and outcome.",
    ("rating", "outcome"),
)


__all__ = [
    "AGENT_COST",
    "AGENT_DURATION",
    "AGENT_ITERATIONS",
    "AGENT_RUNS",
    "AGENT_TOKENS",
    "CIRCUIT_EVENTS",
    "FEEDBACK_SUBMISSIONS",
    "MODEL_CALLS",
    "MODEL_LATENCY",
    "QUEUE_ACTIVE",
    "QUEUE_DEPTH",
    "QUEUE_WAIT",
    "RATE_LIMIT_DECISIONS",
    "TOOL_CALLS",
    "TOOL_LATENCY",
    "TRACE_PERSISTENCE",
]
