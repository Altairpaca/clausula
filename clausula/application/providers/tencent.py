"""Real Tencent daily-OHLCV provider adapter for #34 (reachable from the dev host)."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any
from urllib.request import Request, urlopen

from clausula.application.market_provider import ProviderPrice, ProviderSnapshot
from clausula.domain import canonical_timestamp, now


@dataclass(frozen=True, slots=True)
class TencentInstrument:
    symbol: str
    market: str
    name: str = ""
    currency: str = ""


MARKET_INFO = {
    "CN-SH": {"prefix": "sh", "currency": "CNY"},
    "CN-SZ": {"prefix": "sz", "currency": "CNY"},
    "HK": {"prefix": "hk", "currency": "HKD"},
    "US": {"prefix": "us", "currency": "USD"},
}

ADJUST_LABELS = {
    "": "unadjusted",
    "qfq": "qfq",
    "hfq": "hfq",
}

ENDPOINT = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"


class TencentProviderError(RuntimeError):
    pass


def _quoted_symbol(market: str, symbol: str) -> str:
    info = MARKET_INFO.get(market)
    if info is None:
        raise TencentProviderError(f"unsupported market: {market}")
    return info["prefix"] + symbol


class TencentDailyProvider:
    """Fetch daily OHLCV bars from Tencent with raw-body capture and adjustment labels.

    Tencent returns unadjusted rows under the 'day' key, qfq under 'qfqday' and
    hfq under 'hfqday'. qfq/hfq are split/dividend-adjusted price series, never
    total-return indices; the label is recorded in the snapshot payload.
    """

    def __init__(
        self,
        instrument: TencentInstrument,
        *,
        adjust: str = "",
        timeout_seconds: float = 30.0,
    ) -> None:
        if instrument.market not in MARKET_INFO:
            raise TencentProviderError(f"unsupported market: {instrument.market}")
        if adjust not in ADJUST_LABELS:
            raise TencentProviderError(f"unsupported adjustment mode: {adjust}")
        self.instrument = instrument
        self.adjust = adjust
        self.timeout_seconds = timeout_seconds

    def _url(self, count: int) -> str:
        quoted = _quoted_symbol(self.instrument.market, self.instrument.symbol)
        return f"{ENDPOINT}?param={quoted},day,,,{count},{self.adjust}"

    def fetch_raw(self, count: int) -> tuple[bytes, dict[str, Any]]:
        url = self._url(count)
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        observed_at = now()
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                status = getattr(response, "status", 200)
                headers = dict(response.headers)
                body = response.read()
        except OSError as exc:
            raise TencentProviderError(f"tencent request failed: {exc}") from exc
        capture = {
            "source": "tencent_http",
            "request_url": url,
            "observed_at": observed_at,
            "status_code": status,
            "response_headers": headers,
            "byte_length": len(body),
        }
        return body, capture

    @staticmethod
    def parse_bars(body: bytes) -> tuple[str, str, list[dict[str, str]]]:
        payload = json.loads(body.decode("utf-8"))
        if payload.get("code") != 0 or not payload.get("data"):
            raise TencentProviderError(f"tencent returned error: {payload.get('msg')}")
        data = next(iter(payload["data"].values()))
        key = "qfqday" if "qfqday" in data else "hfqday" if "hfqday" in data else "day"
        rows_raw = data.get(key) or []
        if not rows_raw:
            raise TencentProviderError("tencent returned no kline rows")
        name = ""
        qt = data.get("qt")
        if qt:
            for values in qt.values():
                if isinstance(values, list) and len(values) > 1:
                    name = str(values[1])
                    break
        rows = []
        for item in rows_raw:
            if len(item) < 6:
                raise TencentProviderError(f"malformed tencent kline row: {item!r}")
            rows.append(
                {
                    "observed_at": str(item[0]),
                    "open": str(item[1]),
                    "close": str(item[2]),
                    "high": str(item[3]),
                    "low": str(item[4]),
                    "volume": str(item[5]),
                }
            )
        return name, rows

    def snapshot(self, count: int = 60) -> ProviderSnapshot:
        body, capture = self.fetch_raw(count)
        name, rows = self.parse_bars(body)
        known_at = now()
        recorded_at = now()
        info = MARKET_INFO[self.instrument.market]
        currency = self.instrument.currency or info["currency"]
        if not currency:
            raise TencentProviderError(f"currency for market {self.instrument.market} is unknown")
        observations = []
        for row in rows:
            observed = canonical_timestamp(row["observed_at"])
            if observed > recorded_at:
                raise TencentProviderError(f"provider observed_at {observed} is after import time")
            observations.append(
                ProviderPrice(
                    identifier=self.instrument.symbol,
                    observed_at=observed,
                    known_at=known_at,
                    close=row["close"],
                    currency=currency,
                    identifier_scheme="ticker",
                    instrument_name=name or self.instrument.name,
                    asset_type="stock",
                    quality="accepted",
                )
            )
        return ProviderSnapshot(
            provider="tencent",
            dataset_name="daily_prices",
            version=f"tencent-{self.instrument.market}-{self.instrument.symbol}-{self.adjust or 'unadj'}-{count}",
            observations=observations,
            raw_payload={
                "capture": capture,
                "adjust": ADJUST_LABELS[self.adjust],
                "body_sha256": hashlib.sha256(body).hexdigest(),
                "body_bytes": len(body),
                "klines": [row["observed_at"] for row in rows],
            },
            adapter_name="tencent-http",
            adapter_version="1",
            schema_version="1",
        )
