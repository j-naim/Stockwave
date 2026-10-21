"""Load daily stock prices into Postgres.

Usage:
    uv run python -m stockwave_pipeline.backfill
    uv run python -m stockwave_pipeline.backfill --full
    uv run python -m stockwave_pipeline.backfill --tickers AAPL SPY
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import timedelta

from . import db
from .config import DEFAULT_START, UNIVERSE, tiingo_api_key
from .tiingo import TiingoClient, has_corporate_action, to_rows

log = logging.getLogger("stockwave.backfill")

# re-fetch recent days for corrections.
OVERLAP_DAYS = 7


def load_symbol(client: TiingoClient, engine, symbol: str, force_full: bool) -> tuple[str, int]:
    last = None if force_full else db.last_trade_date(engine, symbol)
    mode = "full" if last is None else "incremental"
    run_id = db.start_run(engine, symbol, mode)

    try:
        if mode == "incremental":
            rows = to_rows(symbol, client.daily_prices(symbol, last - timedelta(days=OVERLAP_DAYS)))
            if has_corporate_action(rows, after=last):
                log.info("%s: dividend or split since %s, reloading full history", symbol, last)
                mode = "full"

        if mode == "full":
            rows = to_rows(symbol, client.daily_prices(symbol, DEFAULT_START))

        count = db.upsert_prices(engine, rows)

        name = None
        if db.ticker_name(engine, symbol) is None:
            name = client.metadata(symbol).get("name")
        db.update_ticker_meta(engine, symbol, name)

        db.finish_run(engine, run_id, status="ok", rows=count, mode=mode)
        return mode, count
    except Exception as exc:
        db.finish_run(engine, run_id, status="error", error=str(exc)[:1000], mode=mode)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Load daily prices into Postgres.")
    parser.add_argument("--full", action="store_true", help="reload all history")
    parser.add_argument("--tickers", nargs="+", metavar="SYMBOL", help="limit to these symbols")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-5s  %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING) 

    universe = {t.symbol for t in UNIVERSE}
    symbols = [s.upper() for s in args.tickers] if args.tickers else [t.symbol for t in UNIVERSE]
    unknown = [s for s in symbols if s not in universe]
    if unknown:
        log.error("Not in the universe (add them to config.py first): %s", ", ".join(unknown))
        return 2

    engine = db.get_engine()
    db.apply_schema(engine)
    db.seed_tickers(engine)

    failures = 0
    with TiingoClient(tiingo_api_key()) as client:
        for symbol in symbols:
            try:
                mode, count = load_symbol(client, engine, symbol, args.full)
                last = db.last_trade_date(engine, symbol)
                log.info("%-5s %-11s %6d rows  through %s", symbol, mode, count, last)
            except Exception as exc:
                failures += 1
                log.error("%-5s failed: %s", symbol, exc)

    if failures:
        log.error("%d of %d tickers failed.", failures, len(symbols))
        return 1
    log.info("Done. %d tickers up to date.", len(symbols))
    return 0


if __name__ == "__main__":
    sys.exit(main())
