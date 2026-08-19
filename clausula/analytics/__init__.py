"""Deterministic analytics over canonical domain facts."""

from .cost_basis import CostBasisError, plan_fifo_transfer, replay_fifo
from .performance import PerformanceError, performance_summary, xirr
from .policy import (
    PolicyEvaluationError,
    evaluate_policy,
    simulate_base_currency_trades,
)
from .planning import compare_plan_scenarios

__all__ = [
    "CostBasisError",
    "PerformanceError",
    "PolicyEvaluationError",
    "evaluate_policy",
    "performance_summary",
    "plan_fifo_transfer",
    "replay_fifo",
    "xirr",
    "simulate_base_currency_trades",
    "compare_plan_scenarios",
]
