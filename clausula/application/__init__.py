"""Canonical application services."""

# Compose optimized/extended concrete services before importing downstream
# modules. Baseline modules remain semantic references; subclasses replace only
# bounded read paths or add deterministic replay support.
from .ledger import ImportValidationError
from .ledger_fast import LedgerService
from . import ledger as _ledger_module

_ledger_module.LedgerService = LedgerService

from .ports import CoreRepository, LedgerRepository
from .rebuild import RebuildError
from .rebuild_ext import LedgerRebuilder
from .market import MarketImportError, MarketService
from .market_provider import (
    MarketProvider,
    ProviderPrice,
    ProviderSnapshot,
    ProviderSnapshotImporter,
)
from .portfolio_fast import PortfolioService
from . import portfolio as _portfolio_module

_portfolio_module.PortfolioService = PortfolioService

from .benchmark import BenchmarkService, ReturnSeriesRepository
from .policy import PolicyService
from .planning import PlanningError, PlanningService
from .decision import DecisionError, DecisionService
from .research import ResearchError, ResearchService
from .research_ingest import ResearchIngestionService, ResearchExtractor, ExtractedDocument
from .recommendation import RecommendationService
from .execution import ExecutionContractError, ExecutionService
from .decision_workspace import DecisionWorkspaceRepository, DecisionWorkspaceService

__all__ = [
    "BenchmarkService",
    "CoreRepository",
    "ExtractedDocument",
    "ImportValidationError",
    "LedgerRebuilder",
    "LedgerRepository",
    "LedgerService",
    "MarketImportError",
    "MarketProvider",
    "MarketService",
    "ProviderPrice",
    "ProviderSnapshot",
    "ProviderSnapshotImporter",
    "ReturnSeriesRepository",
    "PortfolioService",
    "PolicyService",
    "PlanningError",
    "PlanningService",
    "DecisionError",
    "DecisionService",
    "RebuildError",
    "ResearchError",
    "ResearchExtractor",
    "ResearchIngestionService",
    "ResearchService",
    "RecommendationService",
    "ExecutionContractError",
    "ExecutionService",
    "DecisionWorkspaceRepository",
    "DecisionWorkspaceService",
]
