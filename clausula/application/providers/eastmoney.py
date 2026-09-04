"""Real Eastmoney daily-OHLCV provider adapter for #34.

Fetches daily bars (klt=101) for CN (1./0. secid), HK (116.) and US (105.)
equities, captures the raw response bytes before canonical conversion, and
labels the series explicitly by adjustment mode. fqt=0 is an unadjusted price
series and is never labeled total_return; qfq/hfq are split/dividend-adjusted
series with the adjustment mode recorded, not total-return indices.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib.request import Request, urlopen

from clausula.application.market_provider import ProviderPrice, ProviderSnapshot
from clausula.domain import canonical_timestamp, now


@dataclass(frozen=True, slots=True)
class EastmoneyInstrument:
    market_code: str
    symbol: str
    name: str = ""
    currency: str = "USD"


MARKET_PREFIX = {
    "CN-SH": "1.",
    "CN-SZ": "0.",
    "HK": "116.",
    "US": "105.",
}

FQT_LABELS = {
    "0": "unadjusted",
    "1": "qfq",
    "2": "hfq",
}


class EastmoneyProviderError(RuntimeError):
    pass


def _secid(market: str, symbol: str) -> str:
    prefix = MARKET_PREFIX.get(market)
    if prefix is None:
        raise EastmoneyProviderError(f"unsupported market: {market}")
    return prefix + symbol


class EastmoneyDailyProvider:
    """Fetch daily OHLCV from Eastmoney with raw-payload capture."""

    ENDPOINT = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

    def __init__(
        self,
        instrument: EastmoneyInstrument,
        *,
        market: str,
        fqt: str = "0",
        timeout_seconds: float = 30.0,
    ) -> None:
        self.instrument = instrument
        self.market = market
        if fqt not in FQT_LABELS:
            raise EastmoneyProviderError(f"unsupported fqt mode: {fqt}")
        self.fqt = fqt
        self.timeout_seconds = timeout_seconds

    def _url(self, begin: str, end: str) -> str:
        return (
            f"{self.ENDPOINT}?secid={_secid(self.market, self.instrument.symbol)}"
            "&fields1=f1,f2,f3,f4,f5,f6"
            "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
            "&klt=101"
            f"&fqt={self.fqt}"
            f"&beg={begin}&end={end}"
        )

    def fetch_raw(self, begin: str, end: str) -> tuple[bytes, dict[str, Any]]:
        url = self._url(begin, end)
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        observed_at = now()
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                status = getattr(response, "status", 200)
                headers = dict(response.headers)
                body = response.read()
        except OSError as exc:
            raise EastmoneyProviderError(
                f"eastmoney request failed: {exc}"
            ) from exc
        capture = {
            "source": "eastmoney_http",
            "request_url": url,
            "observed_at": observed_at,
            "status_code": status,
            "response_headers": headers,
            "byte_length": len(body),
        }
        return body, capture

    @staticmethod
    def parse_klines(body: bytes) -> tuple[str, str, list[dict[str, str]]]:
        payload = json.loads(body.decode("utf-8"))
        data = payload.get("data")
        if data is None or data.get("klines") is None:
            raise EastmoneyProviderError(f"eastmoney returned no data: {payload.get('rc')}")
        name = str(data.get("name") or "")
        code = str(data.get("code") or "")
        rows: list[dict[str, str]] = []
        for line in data["klines"]:
            fields = line.split(",")
            if len(fields) < 6:
                raise EastmoneyProviderError(f"malformed kline row: {line!r}")
            rows.append(
                {
                    "observed_at": fields[0],
                    "open": fields[1],
                    "close": fields[2],
                    "high": fields[3],
                    "low": fields[4],
                    "volume": fields[5],
                    "amount": fields[6] if len(fields) > 6 else "",
                }
            )
        return name, code, rows

    def snapshot(self, begin: str, end: str) -> ProviderSnapshot:
        body, capture = self.fetch_raw(begin, end)
        name, code, rows = self.parse_klines(body)
        known_at = now()
        recorded_at = now()
        observations = []
        for row in rows:
            observed = canonical_timestamp(row["observed_at"])
            if observed > recorded_at:
                raise EastmoneyProviderError(
                    f"provider observed_at {observed} is after import time"
                )
            observations.append(
                ProviderPrice(
                    identifier=self.instrument.symbol,
                    observed_at=observed,
                    known_at=known_at,
                    close=row["close"],
                    currency=self.instrument.currency or "USD",
                    identifier_scheme="ticker",
                    instrument_name=name or self.instrument.name,
                    asset_type="stock",
                    quality="accepted",
                )
            )
        return ProviderSnapshot(
            provider="eastmoney",
            dataset_name="daily_prices",
            version=f"eastmoney-{self.market}-{code}-fqt{self.fqt}-{begin}-{end}",
            observations=observations,
            raw_payload={
                "capture": capture,
                "klines": [row["observed_at"] for row in rows],
            },
            adapter_name="eastmoney-http",
            adapter_version="1",
            schema_version="1",
        )


def snapshot_for_market(
    market: str, symbol: str, begin: str, end: str, *, name: str = "", currency: str = ""
) -> ProviderSnapshot:
    instrument = EastmoneyInstrument(market_code=market, symbol=symbol, name=name, currency=currency)
    return EastmoneyDailyProvider(instrument, market=market).snapshot(begin, end)
