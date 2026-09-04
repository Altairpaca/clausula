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
    assert store.verify_audit_chain()["valid"] is True


def test_attention_survives_store_reopen(tmp_path) -> None:
    home = tmp_path / "home"
    first_store = Store(home)
    first_service = AttentionService(first_store)
    created = first_service.evaluate(
        event_key="research:thesis-1",
        event_type="thesis_change",
        severity="medium",
        material=True,
        summary="A material thesis assumption changed.",
        occurred_at="2026-01-02T12:00:00+08:00",
    )
    first_store.close()

    second_store = Store(home)
    second_service = AttentionService(second_store)
    rows = second_service.list()
    duplicate = second_service.evaluate(
        event_key="research:thesis-1",
        event_type="thesis_change",
        severity="medium",
        material=True,
        summary="A material thesis assumption changed.",
        occurred_at="2026-01-02T12:00:00+08:00",
    )

    assert created is not None
    assert rows == [created]
    assert duplicate == created
    assert len(second_service.list()) == 1
    assert second_store.verify_audit_chain()["valid"] is True
