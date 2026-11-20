"""This pulls new prices, then reruns the models if there's new data.

    uv run python -m stockwave_pipeline.nightly            # normal run
    uv run python -m stockwave_pipeline.nightly --force    # rerun models even without new data
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from . import backfill, db, forecast

log = logging.getLogger("stockwave.nightly")


def wait_for_db(engine, timeout: float = 60.0) -> None:
    """Postgres needs a few sec. to accept connections after startup."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh prices and forecasts.")
    parser.add_argument("--force", action="store_true", help="rerun models even if no new data")
    parser.add_argument("--skip-prices", action="store_true", help="don't call Tiingo")
    parser.add_argument("--origins", type=int, default=504, help="backtest length in days")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-5s  %(message)s")
    engine = db.get_engine()
    wait_for_db(engine)

    if not args.skip_prices:
        code = backfill.main([])
        if code == 2:
            return code
        if code != 0:
            log.warning("some tickers failed to update; continuing with what's stored")
    else:
        db.apply_schema(engine)

    with engine.connect() as conn:
        latest_price = conn.execute(text("SELECT max(trade_date) FROM prices")).scalar()
    last = forecast.last_ok_run(engine)

    if last and last["data_through"] == latest_price and not args.force:
        log.info("forecasts already current through %s; nothing to do", latest_price)
        return 0

    forecast.run(engine, n_origins=args.origins)
    return 0


if __name__ == "__main__":
    sys.exit(main())
