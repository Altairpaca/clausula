from __future__ import annotations

import os
import tempfile
from pathlib import Path

from clausula import Store
from clausula.application.market_provider import ProviderSnapshotImporter
from clausula.application.providers.tencent import TencentDailyProvider, TencentInstrument


def _live_store(tmp: Path) -> Store:
    os.environ["TEST_DATA_ROOT"] = str(tmp)
    return Store(tmp / "home")


def test_live_cn_single_instrument_imports_into_isolated_root() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="clausula-tencent-live-"))
    store = _live_store(tmp)
    provider = TencentDailyProvider(
        TencentInstrument(symbol="600000", market="CN-SH", name="浦发银行"),
        adjust="",
    )
    snapshot = provider.snapshot(count=30)
    assert len(snapshot.observations) >= 20, "expected at least 20 real trading days"
    assert snapshot.observations[0].currency == "CNY"
    assert snapshot.raw_payload["adjust"] == "unadjusted"
    assert snapshot.raw_payload["body_sha256"]

    result = ProviderSnapshotImporter(store).import_snapshot(snapshot)
    assert result["provider"] == "tencent"
    datasets = store.market_datasets("daily_prices")
    assert len(datasets) == 1
    n = store.db.execute(
        "SELECT count(*) c FROM market_prices WHERE dataset_id=?", (datasets[0]["id"],)
    ).fetchone()["c"]
    assert n == len(snapshot.observations)
    assert (tmp / "home" / "clausula.db").exists()
    store.close()


def test_live_import_is_idempotent_by_dataset_version() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="clausula-tencent-idem-"))
    store = _live_store(tmp)
    provider = TencentDailyProvider(
        TencentInstrument(symbol="600000", market="CN-SH"),
        adjust="",
    )
    snapshot = provider.snapshot(count=30)
    importer = ProviderSnapshotImporter(store)
    first = importer.import_snapshot(snapshot)
    second = importer.import_snapshot(snapshot)
    assert first["dataset_id"] == second["dataset_id"]
    datasets = store.market_datasets("daily_prices")
    assert len(datasets) == 1, "re-import must not duplicate the dataset"
    n = store.db.execute(
        "SELECT count(*) c FROM market_prices WHERE dataset_id=?",
        (datasets[0]["id"],),
    ).fetchone()["c"]
    assert n == len(snapshot.observations)
    store.close()


def test_live_hk_market_currency_is_hkd() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="clausula-tencent-hk-"))
    store = _live_store(tmp)
    provider = TencentDailyProvider(
        TencentInstrument(symbol="00700", market="HK", name="腾讯控股"),
        adjust="",
    )
    snapshot = provider.snapshot(count=30)
    assert len(snapshot.observations) >= 10
    assert snapshot.observations[0].currency == "HKD"
    store.close()
