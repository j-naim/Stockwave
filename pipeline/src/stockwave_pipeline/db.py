"""Database operations for Stockwave."""

from __future__ import annotations

from datetime import date
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text

from .config import SQL_DIR, UNIVERSE, database_url


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(database_url(), pool_pre_ping=True)


def apply_schema(engine: Engine) -> None:
    """Run every sql/*.sql file in name order. Each file must be re-runnable."""
    for path in sorted(SQL_DIR.glob("*.sql")):
        raw = engine.raw_connection()
        try:
            with raw.cursor() as cur:
                cur.execute(path.read_text())
            raw.commit()
        finally:
            raw.close()


def seed_tickers(engine: Engine) -> None:
    sql = text(
        """
        INSERT INTO tickers (symbol, sector, is_benchmark)
        VALUES (:symbol, :sector, :is_benchmark)
        ON CONFLICT (symbol) DO UPDATE
            SET sector = EXCLUDED.sector,
                is_benchmark = EXCLUDED.is_benchmark
        """
    )
    rows = [
        {"symbol": t.symbol, "sector": t.sector, "is_benchmark": t.is_benchmark}
        for t in UNIVERSE
    ]
    with engine.begin() as conn:
        conn.execute(sql, rows)


def ticker_name(engine: Engine, symbol: str) -> str | None:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT name FROM tickers WHERE symbol = :s"), {"s": symbol}
        ).scalar()


def update_ticker_meta(engine: Engine, symbol: str, name: str | None) -> None:
    sql = text(
        """
        UPDATE tickers
           SET name = COALESCE(:name, name),
               first_date = (SELECT min(trade_date) FROM prices WHERE symbol = :s)
         WHERE symbol = :s
        """
    )
    with engine.begin() as conn:
        conn.execute(sql, {"s": symbol, "name": name})


def last_trade_date(engine: Engine, symbol: str) -> date | None:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT max(trade_date) FROM prices WHERE symbol = :s"), {"s": symbol}
        ).scalar()


_UPSERT_PRICES = text(
    """
    INSERT INTO prices (
        symbol, trade_date, open, high, low, close, volume,
        adj_open, adj_high, adj_low, adj_close, adj_volume,
        div_cash, split_factor, source, ingested_at
    ) VALUES (
        :symbol, :trade_date, :open, :high, :low, :close, :volume,
        :adj_open, :adj_high, :adj_low, :adj_close, :adj_volume,
        :div_cash, :split_factor, 'tiingo', now()
    )
    ON CONFLICT (symbol, trade_date) DO UPDATE SET
        open = EXCLUDED.open,
        high = EXCLUDED.high,
        low = EXCLUDED.low,
        close = EXCLUDED.close,
        volume = EXCLUDED.volume,
        adj_open = EXCLUDED.adj_open,
        adj_high = EXCLUDED.adj_high,
        adj_low = EXCLUDED.adj_low,
        adj_close = EXCLUDED.adj_close,
        adj_volume = EXCLUDED.adj_volume,
        div_cash = EXCLUDED.div_cash,
        split_factor = EXCLUDED.split_factor,
        source = EXCLUDED.source,
        ingested_at = EXCLUDED.ingested_at
    """
)


def upsert_prices(engine: Engine, rows: list[dict]) -> int:
    if not rows:
        return 0
    with engine.begin() as conn:
        conn.execute(_UPSERT_PRICES, rows)
    return len(rows)


def start_run(engine: Engine, symbol: str, mode: str) -> int:
    with engine.begin() as conn:
        return conn.execute(
            text(
                "INSERT INTO ingest_runs (symbol, mode) VALUES (:s, :m) RETURNING id"
            ),
            {"s": symbol, "m": mode},
        ).scalar_one()


def finish_run(
    engine: Engine,
    run_id: int,
    *,
    status: str,
    rows: int | None = None,
    error: str | None = None,
    mode: str | None = None,
) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE ingest_runs
                   SET finished_at = now(),
                       status = :status,
                       rows_upserted = :rows,
                       error = :error,
                       mode = COALESCE(:mode, mode)
                 WHERE id = :id
                """
            ),
            {"id": run_id, "status": status, "rows": rows, "error": error, "mode": mode},
        )
