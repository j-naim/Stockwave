"""Runs the backtest and saves forecasts and scores to Postgres."""

from __future__ import annotations

import logging
import time

import numpy as np
import pandas as pd
from sqlalchemy import Engine, text

from . import evaluate as E
from . import features as F

log = logging.getLogger("stockwave.forecast")

FORECAST_COLS = [
    "symbol", "model", "origin_date", "horizon", "target_date", "is_backtest",
    "origin_price", "mean", "sd", "q025", "q10", "q25", "q50", "q75", "q90", "q975", "actual",
]
OUTPUT_TABLES = ("forecasts", "forecast_scores", "vol_scores", "dm_tests")


def last_ok_run(engine: Engine) -> dict | None:
    with engine.connect() as conn:
        row = conn.execute(text("SELECT id, data_through FROM latest_run")).mappings().first()
    return dict(row) if row else None


def _scores(fc: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    pooled = E.score(fc, by=("model", "horizon")).reset_index().assign(symbol="ALL")
    per_ticker = E.score(fc, by=("symbol", "model", "horizon")).reset_index()
    scores = pd.concat([pooled, per_ticker], ignore_index=True)

    vol_pooled = E.vol_score(fc, by=("model",)).reset_index().assign(symbol="ALL")
    vol_ticker = E.vol_score(fc, by=("symbol", "model")).reset_index()
    vol = pd.concat([vol_pooled, vol_ticker], ignore_index=True)

    candidates = [m for m in fc["model"].unique() if m != E.BASELINE]
    dm = pd.DataFrame([
        E.diebold_mariano(fc, model, horizon=h)
        for model in sorted(candidates) for h in sorted(fc["horizon"].unique())
    ])
    return scores, vol, dm


def _forward(prices: pd.DataFrame, horizons=range(1, 11)) -> pd.DataFrame:
    """Every model's forecast from the latest close, for each day out to 10."""
    frames = []
    for sym in prices.columns:
        lp = np.log(prices[sym].dropna())
        r = lp.diff().iloc[1:]
        lp = lp.iloc[1:]
        i = len(r) - 1
        for name in E.MODEL_NAMES:
            f = E._run_model(name, r, lp, np.array([i]), list(horizons))
            f["symbol"] = sym
            f["model"] = name
            f["origin_date"] = r.index[i]
            f["target_date"] = [r.index[i] + pd.offsets.BDay(int(h)) for h in f["horizon"]]
            f["origin_price"] = float(np.exp(lp.iloc[i]))
            f["is_backtest"] = False
            f["actual"] = np.nan
            frames.append(f)
    return pd.concat(frames, ignore_index=True)


def run(engine: Engine, n_origins: int = 504) -> int:
    """Backtest every model, write the results and return the run id."""
    prices = F.load_prices(engine)
    data_through = prices.index.max().date()

    with engine.begin() as conn:
        run_id = conn.execute(
            text("INSERT INTO model_runs (data_through, n_origins) VALUES (:d, :n) RETURNING id"),
            {"d": data_through, "n": n_origins},
        ).scalar_one()

    try:
        t0 = time.monotonic()
        fc = E.walk_forward(prices, n_origins=n_origins, progress=log.info)
        log.info("backtest done in %.0fs", time.monotonic() - t0)
        scores, vol, dm = _scores(fc)

        # Swap the latest close's 1/5/10-day rows for the full 1-10 day path.
        latest = fc["origin_date"] == fc["origin_date"].max()
        fc = pd.concat([fc[~latest], _forward(prices)], ignore_index=True)

        out = fc[FORECAST_COLS].copy()
        out["origin_date"] = out["origin_date"].dt.date
        out["target_date"] = out["target_date"].dt.date

        with engine.begin() as conn:
            for name, df in (("forecasts", out), ("forecast_scores", scores),
                             ("vol_scores", vol), ("dm_tests", dm)):
                df.assign(run_id=run_id).to_sql(name, conn, if_exists="append", index=False,
                                                chunksize=5000)
            # Only the newest run's output is kept; model_runs keeps the history.
            for name in OUTPUT_TABLES:
                conn.execute(text(f"DELETE FROM {name} WHERE run_id <> :id"), {"id": run_id})
            conn.execute(
                text("UPDATE model_runs SET status = 'ok', finished_at = now(), n_forecasts = :n "
                     "WHERE id = :id"),
                {"id": run_id, "n": len(out)},
            )
    except Exception as exc:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE model_runs SET status = 'error', finished_at = now(), error = :e "
                     "WHERE id = :id"),
                {"id": run_id, "e": str(exc)[:1000]},
            )
        raise

    log.info("run %d: %d forecasts through %s", run_id, len(out), data_through)
    return run_id
