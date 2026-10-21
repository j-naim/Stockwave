"""Tiingo API client."""

from __future__ import annotations

import time
from datetime import date

import httpx

BASE_URL = "https://api.tiingo.com/tiingo/daily"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class TiingoError(RuntimeError):
    pass


class TiingoClient:
    def __init__(self, api_key: str, timeout: float = 30.0, max_retries: int = 4):
        self._max_retries = max_retries
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={
                "Authorization": f"Token {api_key}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    def __enter__(self) -> TiingoClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def _get(self, path: str, params: dict | None = None):
        delay = 2.0
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._http.get(path, params=params)
            except httpx.TransportError as exc:
                if attempt == self._max_retries:
                    raise TiingoError(f"Network error calling {path}: {exc}") from exc
            else:
                if resp.status_code not in RETRY_STATUSES:
                    if resp.status_code >= 400:
                        raise TiingoError(
                            f"Tiingo returned {resp.status_code} for {path}: {resp.text[:200]}"
                        )
                    return resp.json()
                if attempt == self._max_retries:
                    raise TiingoError(
                        f"Tiingo kept returning {resp.status_code} for {path}; giving up."
                    )
            time.sleep(delay)
            delay *= 2
        raise AssertionError("unreachable")

    def metadata(self, symbol: str) -> dict:
        return self._get(f"/{symbol.lower()}")

    def daily_prices(
        self, symbol: str, start: date | str, end: date | str | None = None
    ) -> list[dict]:
        params = {"startDate": str(start), "resampleFreq": "daily", "format": "json"}
        if end is not None:
            params["endDate"] = str(end)
        return self._get(f"/{symbol.lower()}/prices", params=params)


def to_rows(symbol: str, payload: list[dict]) -> list[dict]:
    """convert API data into database rows."""
    rows = []
    for bar in payload:
        rows.append(
            {
                "symbol": symbol,
                "trade_date": date.fromisoformat(bar["date"][:10]),
                "open": bar.get("open"),
                "high": bar.get("high"),
                "low": bar.get("low"),
                "close": bar["close"],
                "volume": int(bar["volume"]) if bar.get("volume") is not None else None,
                "adj_open": bar.get("adjOpen"),
                "adj_high": bar.get("adjHigh"),
                "adj_low": bar.get("adjLow"),
                "adj_close": bar["adjClose"],
                "adj_volume": bar.get("adjVolume"),
                "div_cash": bar.get("divCash") or 0,
                "split_factor": bar.get("splitFactor") or 1,
            }
        )
    return rows


def has_corporate_action(rows: list[dict], after: date) -> bool:
    """check for dividends or splits after a given date."""
    return any(
        r["trade_date"] > after
        and (float(r["div_cash"]) != 0.0 or float(r["split_factor"]) != 1.0)
        for r in rows
    )
