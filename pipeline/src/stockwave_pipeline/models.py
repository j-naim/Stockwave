"""stock return forecasting models."""

from __future__ import annotations

import warnings
from collections.abc import Sequence

import numpy as np
import pandas as pd
from scipy import stats

QUANTILES = (0.025, 0.10, 0.25, 0.50, 0.75, 0.90, 0.975)
QCOLS = ("q025", "q10", "q25", "q50", "q75", "q90", "q975")
BANDS = {50: ("q25", "q75"), 80: ("q10", "q90"), 95: ("q025", "q975")}

_Z = stats.norm.ppf(QUANTILES)


def _rows(origins: np.ndarray, h: int, mean: np.ndarray, sd: np.ndarray, z: np.ndarray) -> pd.DataFrame:
    df = pd.DataFrame({"origin_pos": origins, "horizon": h, "mean": mean, "sd": sd})
    for col, zq in zip(QCOLS, z):
        df[col] = mean + sd * zq
    return df


def random_walk(r: pd.Series, origins: Sequence[int], horizons: Sequence[int], vol_window: int = 20) -> pd.DataFrame:
    """forecast zero returns using recent volatility."""
    origins = np.asarray(origins)
    sd1 = r.rolling(vol_window).std().to_numpy()[origins]
    return pd.concat(
        [_rows(origins, h, np.zeros(len(origins)), sd1 * np.sqrt(h), _Z) for h in horizons],
        ignore_index=True,
    )


def drift(
    r: pd.Series,
    origins: Sequence[int],
    horizons: Sequence[int],
    mean_window: int = 252,
    vol_window: int = 20,
) -> pd.DataFrame:
    """forecast returns using historical drift and volatility."""
    origins = np.asarray(origins)
    mu1 = r.rolling(mean_window).mean().to_numpy()[origins]
    sd1 = r.rolling(vol_window).std().to_numpy()[origins]
    return pd.concat(
        [_rows(origins, h, mu1 * h, sd1 * np.sqrt(h), _Z) for h in horizons],
        ignore_index=True,
    )


def garch(
    r: pd.Series,
    origins: Sequence[int],
    horizons: Sequence[int],
    refit_every: int = 21,
    fit_window: int = 2520,
) -> pd.DataFrame:
    """forecast returns and volatility using GARCH(1,1)."""
    from arch import arch_model

    # scale returns for model fitting.
    y = r.to_numpy() * 100.0  
    origins = np.asarray(origins)
    max_h = max(horizons)
    frames = []

    for b in range(0, len(origins), refit_every):
        block = origins[b : b + refit_every]
        first, last = int(block[0]), int(block[-1])
        lo = max(0, first + 1 - fit_window)
        model = arch_model(y[lo : last + 1], mean="Constant", vol="GARCH", p=1, q=1, dist="t")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            # fit using data through the first origin.
            res = model.fit(last_obs=first + 1 - lo, disp="off")
        fc = res.forecast(horizon=max_h, start=first - lo, reindex=False)
        mean = fc.mean.to_numpy()[block - first]
        var = fc.variance.to_numpy()[block - first]
        nu = float(res.params["nu"])
        t_z = stats.t.ppf(QUANTILES, nu) * np.sqrt((nu - 2.0) / nu)  # unit-variance t

        for h in horizons:
            mu_h = mean[:, :h].sum(axis=1) / 100.0
            sd_h = np.sqrt(var[:, :h].sum(axis=1)) / 100.0
            frames.append(_rows(block, h, mu_h, sd_h, t_z if h == 1 else _Z))

    return pd.concat(frames, ignore_index=True)


def ets(
    log_price: pd.Series,
    origins: Sequence[int],
    horizons: Sequence[int],
    refit_every: int = 21,
) -> pd.DataFrame:
    """forecast log prices using AutoETS."""
    from statsforecast import StatsForecast
    from statsforecast.models import AutoETS

    lp = log_price.to_numpy()
    n = len(lp)
    origins = np.asarray(origins)
    max_h = max(horizons)
    levels = [50, 80, 95]
    df = pd.DataFrame({"unique_id": "s", "ds": np.arange(n), "y": lp})
    sf = StatsForecast(models=[AutoETS(season_length=1)], freq=1, n_jobs=1)

    parts = []
    backtest = origins[origins <= n - 1 - max_h]
    if len(backtest):
        if not np.array_equal(backtest, np.arange(backtest[0], backtest[-1] + 1)):
            raise ValueError("ets() needs contiguous origins")
        
        # limit data to the backtest period.
        end = backtest[-1] + max_h + 1
        cv = sf.cross_validation(
            df=df.iloc[:end], h=max_h, n_windows=len(backtest), step_size=1,
            refit=refit_every, level=levels,
        )
        parts.append(cv)
    if origins[-1] == n - 1:
        fc = sf.forecast(df=df, h=max_h, level=levels)
        fc["cutoff"] = n - 1
        parts.append(fc)

    out = pd.concat(parts, ignore_index=True)
    out["horizon"] = out["ds"] - out["cutoff"]
    out = out[out["horizon"].isin(horizons)]
    base = lp[out["cutoff"].to_numpy()]
    q = {
        "q50": out["AutoETS"].to_numpy() - base,
        "q25": out["AutoETS-lo-50"].to_numpy() - base,
        "q75": out["AutoETS-hi-50"].to_numpy() - base,
        "q10": out["AutoETS-lo-80"].to_numpy() - base,
        "q90": out["AutoETS-hi-80"].to_numpy() - base,
        "q025": out["AutoETS-lo-95"].to_numpy() - base,
        "q975": out["AutoETS-hi-95"].to_numpy() - base,
    }
    res = pd.DataFrame({
        "origin_pos": out["cutoff"].to_numpy(),
        "horizon": out["horizon"].to_numpy(),
        "mean": q["q50"],
        # implied by the 80% band, for the volatility scores.
        "sd": (q["q90"] - q["q10"]) / (2 * stats.norm.ppf(0.90)),
    })
    for col in QCOLS:
        res[col] = q[col]
    return res
