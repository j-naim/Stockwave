
"""Stockwave chart themes."""

from __future__ import annotations

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib import font_manager

TOKENS = {
    "dark": {
        "bg": "#0A0C0F", "surface": "#111419", "surface_2": "#181C22",
        "border": "#242A32", "grid": "#1A1F26",
        "text_1": "#E7EAEE", "text_2": "#A0A8B3", "text_3": "#626B76",
        "accent": "#5B9BFF", "positive": "#3CC08E", "negative": "#F2616B",
        "vol": "#E8B04B", "violet": "#B392F0",
    },
    "light": {
        "bg": "#F6F7F9", "surface": "#FFFFFF", "surface_2": "#EFF1F4",
        "border": "#DDE1E6", "grid": "#ECEEF1",
        "text_1": "#0E1217", "text_2": "#4A535E", "text_3": "#8B939D",
        "accent": "#1F5FD6", "positive": "#0B8A5E", "negative": "#CC2F3C",
        "vol": "#A86A00", "violet": "#7148C2",
    },
}

# colors for comparing multiple tickers.
SERIES = {
    "dark": ["#6CB6FF", "#F0A24B", "#B392F0", "#3DC9B8", "#F07FB4", "#A8C86A", "#E8865C", "#9AA9C2"],
    "light": ["#1B6FC2", "#B8670A", "#7148C2", "#0E8577", "#B83777", "#5E7E1E", "#B04F25", "#556479"],
}

# forecast band opacity -- inner bands darker.
BAND_ALPHA = {50: 0.28, 80: 0.16, 95: 0.08}

_FONT_PREFS = ["Geist", "Inter", "IBM Plex Sans", "DejaVu Sans"]


def _first_installed(names: list[str]) -> str:
    installed = {f.name for f in font_manager.fontManager.ttflist}
    return next((n for n in names if n in installed), "DejaVu Sans")


def use_theme(mode: str = "dark") -> dict:
    """Apply the theme globally and return its color tokens."""
    t = TOKENS[mode]
    mpl.rcParams.update({
        "figure.facecolor": t["surface"],
        "figure.dpi": 110,
        "figure.figsize": (11, 4.2),
        "axes.facecolor": t["surface"],
        "axes.edgecolor": t["border"],
        "axes.labelcolor": t["text_2"],
        "axes.titlecolor": t["text_1"],
        "axes.titlesize": 11,
        "axes.titleweight": "medium",
        "axes.titlelocation": "left",
        "axes.titlepad": 10,
        "axes.labelsize": 9,
        "axes.grid": True,
        "axes.axisbelow": True,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.prop_cycle": mpl.cycler(color=SERIES[mode]),
        "grid.color": t["grid"],
        "grid.linewidth": 0.8,
        "xtick.color": t["text_3"],
        "ytick.color": t["text_3"],
        "xtick.labelsize": 8.5,
        "ytick.labelsize": 8.5,
        "xtick.major.size": 0,
        "ytick.major.size": 0,
        "legend.frameon": False,
        "legend.fontsize": 8.5,
        "legend.labelcolor": t["text_2"],
        "lines.linewidth": 1.4,
        "font.family": _first_installed(_FONT_PREFS),
        "text.color": t["text_1"],
        "savefig.facecolor": t["surface"],
    })
    return t


def legend_below(ax: plt.Axes, ncol: int = 8) -> None:
    """legend under the plot, so it never covers data."""
    ax.legend(ncol=ncol, loc="upper left", bbox_to_anchor=(0, -0.09), handlelength=1.6,
              columnspacing=1.6)


def titles(ax: plt.Axes, title: str, sub: str | None, tokens: dict) -> None:
    """add title and optional subtitle."""
    ax.set_title(title, pad=22 if sub else 10)
    if sub:
        ax.text(0, 1.02, sub, transform=ax.transAxes, color=tokens["text_3"], fontsize=8.5, va="bottom")
