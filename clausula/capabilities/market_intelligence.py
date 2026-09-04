from __future__ import annotations

from clausula.adapters.market_intelligence import MarketIntelligenceProjection
from clausula.application.benchmark import BenchmarkService

from .registry import CapabilityRegistry, CapabilitySpec, SideEffect, object_schema


STRING = {"type": "string"}
NULLABLE_STRING = {"type": ["string", "null"]}


def register_market_intelligence_capabilities(
    registry: CapabilityRegistry, repository
) -> CapabilityRegistry:
    projection = MarketIntelligenceProjection(repository)
    benchmarks = BenchmarkService(repository, projection)

    registry.register(
        CapabilitySpec(
            "market.dataset_health",
            "Inspect objective point-in-time quality, coverage, lag and conflict signals for a pinned dataset version.",
            object_schema(
                {
                    "dataset_name": STRING,
                    "dataset_version": STRING,
                    "as_of": STRING,
                    "known_as_of": NULLABLE_STRING,
                },
                required=("dataset_name", "dataset_version", "as_of"),
            ),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("market:read",),
            False,
            "Reads append-only market observations and the hashed dataset manifest; no subjective staleness threshold is invented.",
        ),
        lambda dataset_name, dataset_version, as_of, known_as_of=None: projection.dataset_health(
            dataset_name,
            dataset_version,
            as_of=as_of,
            known_as_of=known_as_of,
        ),
    )

    registry.register(
        CapabilitySpec(
            "market.return_series",
            "Read an explicit price-return or total-return index from a pinned dataset manifest.",
            object_schema(
                {
                    "dataset_name": STRING,
                    "dataset_version": STRING,
                    "identifier": STRING,
                    "identifier_scheme": STRING,
                    "as_of": STRING,
                    "known_as_of": STRING,
                },
                required=(
                    "dataset_name",
                    "dataset_version",
                    "identifier",
                    "as_of",
                    "known_as_of",
                ),
            ),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("market:read",),
            False,
            "Never infers total return from close/adjusted-close naming; semantics must be explicit in the hashed dataset manifest.",
        ),
        lambda dataset_name, dataset_version, identifier, as_of, known_as_of, identifier_scheme="ticker": projection.return_series(
            dataset_name,
            dataset_version,
            identifier,
            identifier_scheme=identifier_scheme,
            as_of=as_of,
            known_as_of=known_as_of,
        ),
    )

    registry.register(
        CapabilitySpec(
            "portfolio.benchmark_compare",
            "Compare portfolio ledger TWR with an explicitly semantic pinned benchmark series.",
            object_schema(
                {
                    "portfolio_id": STRING,
                    "benchmark_dataset_name": STRING,
                    "benchmark_dataset_version": STRING,
                    "benchmark_identifier": STRING,
                    "benchmark_identifier_scheme": STRING,
                    "as_of": STRING,
                    "known_as_of": STRING,
                    "price_dataset_name": NULLABLE_STRING,
                    "price_dataset_version": NULLABLE_STRING,
                    "fx_dataset_name": NULLABLE_STRING,
                    "fx_dataset_version": NULLABLE_STRING,
                },
                required=(
                    "portfolio_id",
                    "benchmark_dataset_name",
                    "benchmark_dataset_version",
                    "benchmark_identifier",
                    "as_of",
                    "known_as_of",
                ),
            ),
            {"type": "object"},
            "read",
            True,
            SideEffect.LOCAL_READ,
            ("portfolio:read", "market:read"),
            False,
            "Uses fixed-vintage benchmark and portfolio inputs and returns explicit comparability semantics.",
        ),
        lambda portfolio_id, benchmark_dataset_name, benchmark_dataset_version, benchmark_identifier, as_of, known_as_of, benchmark_identifier_scheme="ticker", price_dataset_name=None, price_dataset_version=None, fx_dataset_name=None, fx_dataset_version=None: benchmarks.compare(
            portfolio_id,
            benchmark_dataset_name=benchmark_dataset_name,
            benchmark_dataset_version=benchmark_dataset_version,
            benchmark_identifier=benchmark_identifier,
            benchmark_identifier_scheme=benchmark_identifier_scheme,
            as_of=as_of,
            known_as_of=known_as_of,
            price_dataset_name=price_dataset_name,
            price_dataset_version=price_dataset_version,
            fx_dataset_name=fx_dataset_name,
            fx_dataset_version=fx_dataset_version,
        ),
    )
    return registry
