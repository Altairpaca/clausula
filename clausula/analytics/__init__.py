"""Deterministic analytics over canonical domain facts."""

from .cost_basis import CostBasisError, plan_fifo_transfer, replay_fifo
from .performance import PerformanceError, performance_summary, xirr

__all__ = [
    "CostBasisError",
    "PerformanceError",
    "performance_summary",
    "plan_fifo_transfer",
    "replay_fifo",
    "xirr",
]
