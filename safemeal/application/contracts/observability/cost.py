"""Application value contracts."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPrice:
    input_cost_per_million: float
    output_cost_per_million: float
    cached_input_cost_per_million: float


@dataclass(frozen=True)
class CostUsage:
    currency: str = "CNY"
    input_cost: float = 0.0
    output_cost: float = 0.0
    cached_input_cost: float = 0.0
    total_cost: float = 0.0
    priced_calls: int = 0
    total_calls: int = 0

    @property
    def complete(self) -> bool:
        return self.total_calls > 0 and self.priced_calls == self.total_calls
