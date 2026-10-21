"""Stockwave configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# config.py -> stockwave_pipeline -> src -> pipeline -> stockwave
PIPELINE_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PIPELINE_ROOT.parent
SQL_DIR = PIPELINE_ROOT / "sql"

load_dotenv(REPO_ROOT / ".env")


@dataclass(frozen=True)
class Ticker:
    symbol: str
    sector: str
    is_benchmark: bool = False


# tracked stocks and benchmark.
UNIVERSE: tuple[Ticker, ...] = (
    Ticker("AAPL", "Information Technology"),
    Ticker("NVDA", "Information Technology"),
    Ticker("MSFT", "Information Technology"),
    Ticker("AMZN", "Consumer Discretionary"),
    Ticker("JPM", "Financials"),
    Ticker("XOM", "Energy"),
    Ticker("JNJ", "Health Care"),
    Ticker("SPY", "Benchmark", is_benchmark=True),
)

DEFAULT_START = "2010-01-01"


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. Add it to {REPO_ROOT / '.env'} and try again."
        )
    return value


def database_url() -> str:
    return require_env("DATABASE_URL")


def tiingo_api_key() -> str:
    return require_env("TIINGO_API_KEY")
