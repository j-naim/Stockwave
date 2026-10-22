"""stock price features and calculations."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sqlalchemy import Engine, text

TRADING_DAYS = 252


def load_prices(engine: Engine, column: str = "adj_close") -> pd.DataFrame:
    """load daily prices from Postgres."""
    if column not in {"adj_close", "close"}:
        raise ValueError("column must be 'adj_close' or 'close'")
    sql = text(f"SELECT trade_date, symbol, {column} AS px FROM prices ORDER BY trade_date")
    with engine.connect() as conn:
        long = pd.read_sql(sql, conn, parse_dates=["trade_date"])
    wide = long.pivot(index="trade_date", columns="symbol", values="px").sort_index()
    wide.index.name = "date"
    wide.columns.name = None
    return wide.astype(float)


def log_returns(prices: pd.DataFrame) -> pd.DataFrame:
    """calc. daily log returns."""
    return np.log(prices).diff().iloc[1:]


def realized_vol(returns: pd.DataFrame, window: int = 20, annualize: bool = True) -> pd.DataFrame:
    """calc. rolling volatility."""
    vol = returns.rolling(window).std()
    return vol * np.sqrt(TRADING_DAYS) if annualize else vol


def rolling_beta(returns: pd.DataFrame, benchmark: str = "SPY", window: int = 60) -> pd.DataFrame:
    """calc. beta against the benchmark."""
    bench = returns[benchmark]
    cov = returns.rolling(window).cov(bench)
    var = bench.rolling(window).var()
    return cov.div(var, axis=0).drop(columns=benchmark)


def excess_returns(returns: pd.DataFrame, benchmark: str = "SPY") -> pd.DataFrame:
    """calc. returns above the benchmark."""
    return returns.drop(columns=benchmark).sub(returns[benchmark], axis=0)


def drawdown(prices: pd.DataFrame) -> pd.DataFrame:
    """calc. declines from peak prices."""
    return prices / prices.cummax() - 1.0


def rebased(prices: pd.DataFrame, start: str | pd.Timestamp | None = None, base: float = 100.0) -> pd.DataFrame:
    """rescale prices to a common starting value."""
    view = prices.loc[start:] if start is not None else prices
    return view / view.iloc[0] * base
