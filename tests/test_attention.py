from __future__ import annotations

from clausula import Store
from clausula.application.attention import AttentionService


def test_attention_only_appends_material_changes_and_deduplicates(tmp_path) -> None:
    store = Store(tmp_path / "home")
    service = AttentionService(store)

    assert service.evaluate(
        event_key="policy:household",
        event_type="policy_violation",
        severity="high",
        material=False,
        summary="No material change",
        occurred_at="2026-01-01",
    ) is None
    created = service.evaluate(
        event_key="policy:household",
        event_type="policy_violation",
        severity="high",
        material=True,
        summary="Cash reserve rule is violated.",
        occurred_at="2026-01-01",
    )
    duplicate = service.evaluate(
        event_key="policy:household",
        event_type="policy_violation",
        severity="high",
        material=True,
        summary="Cash reserve rule is violated.",
        occurred_at="2026-01-01",
    )

    assert created is not None
    assert duplicate == created
    assert len(service.list()) == 1
