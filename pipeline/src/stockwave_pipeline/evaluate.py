"""Walk-forward backtesting and forecast scoring."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np
import pandas as pd
from scipy import stats

from . import models as m

HORIZONS = (1, 5, 10)
MODEL_NAMES = ("random_walk", "drift", "garch", "ets")
BASELINE = "random_walk"
MIN_HISTORY = 504  # days of history required before the first origin


def _run_model(name: str, r: pd.Series, lp: pd.Series, origins: np.ndarray, horizons) -> pd.DataFrame:
    if name == "random_walk":
        return m.random_walk(r, origins, horizons)
    if name == "drift":
        return m.drift(r, origins, horizons)
    if name == "garch":
        return m.garch(r, origins, horizons)
    if name == "ets":
        return m.ets(lp, origins, horizons)
    raise ValueError(f"unknown model {name!r}")


def walk_forward(
    prices: pd.DataFrame,
    symbols: Sequence[str] | None = None,
    models: Sequence[str] = MODEL_NAMES,
    horizons: Sequence[int] = HORIZONS,
    n_origins: int = 504,
    include_latest: bool = True,
    progress: Callable[[str], None] | None = print,
) -> pd.DataFrame:
    """generate backtests and latest forecasts for each model."""
    symbols = list(symbols) if symbols is not None else list(prices.columns)
    horizons = sorted(horizons)
    max_h = horizons[-1]
    out = []

    for sym in symbols:
        lp = np.log(prices[sym].dropna())
        r = lp.diff().iloc[1:]
        lp = lp.iloc[1:]  
        n = len(r)
        last_bt = n - 1 - max_h
        first = last_bt - n_origins + 1
        if first < MIN_HISTORY:
            raise ValueError(f"{sym}: not enough history for {n_origins} origins")
        origins = np.arange(first, n if include_latest else last_bt + 1)

        # Cumulative returns for each forecast horizon.
        cum = np.concatenate([[0.0], np.cumsum(r.to_numpy())])

        for name in models:
            if progress:
                progress(f"{sym:<5} {name}")
            f = _run_model(name, r, lp, origins, horizons)
            f.insert(0, "model", name)
            f.insert(0, "symbol", sym)
            tgt = f["origin_pos"].to_numpy() + f["horizon"].to_numpy()
            known = tgt <= n - 1
            actual = np.full(len(f), np.nan)
            actual[known] = cum[tgt[known] + 1] - cum[f["origin_pos"].to_numpy()[known] + 1]
            f["actual"] = actual
            f["origin_date"] = r.index[f["origin_pos"].to_numpy()]
            f["target_date"] = pd.NaT
            f.loc[known, "target_date"] = r.index[tgt[known]]
            # Estimate future trading dates.
            future = ~known
            f.loc[future, "target_date"] = [
                d + pd.offsets.BDay(int(h))
                for d, h in zip(f.loc[future, "origin_date"], f.loc[future, "horizon"])
            ]
            f["origin_price"] = np.exp(lp.to_numpy()[f["origin_pos"].to_numpy()])
            f["is_backtest"] = f["origin_pos"] <= last_bt
            out.append(f)

    fc = pd.concat(out, ignore_index=True)
    cols = ["symbol", "model", "origin_date", "target_date", "horizon", "is_backtest",
            "origin_price", "mean", "sd", *m.QCOLS, "actual", "origin_pos"]
    return fc[cols].sort_values(["symbol", "model", "horizon", "origin_date"], ignore_index=True)


# scoring


def pinball_loss(actual: np.ndarray, q: pd.DataFrame) -> np.ndarray:
    """calc. avg. quantile loss."""
    losses = []
    for tau, col in zip(m.QUANTILES, m.QCOLS):
        diff = actual - q[col].to_numpy()
        losses.append(np.maximum(tau * diff, (tau - 1.0) * diff))
    return np.mean(losses, axis=0)


def _with_losses(fc: pd.DataFrame) -> pd.DataFrame:
    bt = fc[fc["is_backtest"]].copy()
    y = bt["actual"].to_numpy()
    bt["abs_err"] = np.abs(y - bt["q50"].to_numpy())
    bt["pinball"] = pinball_loss(y, bt)
    point = np.sign(bt["q50"].to_numpy())
    bt["hit"] = np.where(point == 0, np.nan, (point == np.sign(y)).astype(float))
    for level, (lo, hi) in m.BANDS.items():
        bt[f"cov{level}"] = ((y >= bt[lo]) & (y <= bt[hi])).astype(float)
    return bt


def score(fc: pd.DataFrame, by: Sequence[str] = ("model", "horizon")) -> pd.DataFrame:
    """Calc. forecast accuracy and coverage metrics."""
    bt = _with_losses(fc)
    keys = ["symbol", "horizon", "origin_pos"]
    base = bt.loc[bt["model"] == BASELINE, keys + ["abs_err"]].rename(columns={"abs_err": "rw_abs_err"})
    bt = bt.merge(base, on=keys, how="left")

    g = bt.groupby(list(by), sort=True)
    res = pd.DataFrame({
        "n": g.size(),
        "mae_bps": g["abs_err"].mean() * 1e4,
        "mase": g["abs_err"].sum() / g["rw_abs_err"].sum(),
        "hit_rate": g["hit"].mean(),
        "base_rate": g["actual"].apply(lambda s: (s > 0).mean()),
        "cov50": g["cov50"].mean(),
        "cov80": g["cov80"].mean(),
        "cov95": g["cov95"].mean(),
        "pinball_bps": g["pinball"].mean() * 1e4,
    })
    return res


def vol_score(fc: pd.DataFrame, by: Sequence[str] = ("model",)) -> pd.DataFrame:
    """score volatility forecasts using QLIKE."""
    bt = fc[fc["is_backtest"] & (fc["horizon"] == 1)].copy()
    var = bt["sd"].to_numpy() ** 2
    bt["qlike"] = np.log(var) + bt["actual"].to_numpy() ** 2 / var
    keys = ["symbol", "origin_pos"]
    base = bt.loc[bt["model"] == BASELINE, keys + ["qlike"]].rename(columns={"qlike": "rw_qlike"})
    bt = bt.merge(base, on=keys, how="left")
    g = bt.groupby(list(by), sort=True)
    return pd.DataFrame({
        "n": g.size(),
        "qlike": g["qlike"].mean(),
        "qlike_vs_rw": g["qlike"].mean() - g["rw_qlike"].mean(),
    })


def diebold_mariano(fc: pd.DataFrame, model: str, loss: str = "pinball", horizon: int = 1) -> dict:
    """compare model accuracy against the random walk."""
    bt = _with_losses(fc)
    bt = bt[bt["horizon"] == horizon]
    a = bt[bt["model"] == model].set_index(["symbol", "origin_date"])[loss]
    b = bt[bt["model"] == BASELINE].set_index(["symbol", "origin_date"])[loss]
    d = (a - b).dropna().groupby(level="origin_date").mean().sort_index().to_numpy()
    T = len(d)
    dc = d - d.mean()
    lags = max(horizon - 1, 0)
    lrv = dc @ dc / T
    for k in range(1, lags + 1):
        lrv += 2 * (1 - k / (lags + 1)) * (dc[k:] @ dc[:-k]) / T
    stat = d.mean() / np.sqrt(lrv / T)
    return {"model": model, "horizon": horizon, "loss": loss, "n_dates": T,
            "mean_diff_bps": d.mean() * 1e4, "dm_stat": stat,
            "p_value": 2 * stats.norm.sf(abs(stat))}


def price_bands(fc: pd.DataFrame) -> pd.DataFrame:
    """convert forecast returns to price levels."""
    out = fc.copy()
    for col in (*m.QCOLS, "mean"):
        out[f"px_{col}"] = out["origin_price"] * np.exp(out[col])
    out["px_actual"] = out["origin_price"] * np.exp(out["actual"])
    return out
