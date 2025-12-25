"""Visualization helpers for canonical :class:`~qcengine.domain.marketdata.Candle` data.

This module intentionally keeps plotting logic thin so callers can quickly inspect
close price and volume trends without worrying about converting dataclasses into the
formats required by matplotlib or plotly. All timestamps are rendered in UTC to match
the candle contract.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Sequence

import pandas as pd

from qcengine.domain.marketdata import Candle


def candles_to_dataframe(candles: Sequence[Candle]) -> pd.DataFrame:
    """Convert canonical candles into a tidy :class:`pandas.DataFrame`.

    The resulting dataframe uses ``bar_start_ts_utc`` as the timezone-aware index and
    preserves the canonical fields so plotting backends can work with simple column
    lookups. Callers are expected to pass already-sorted candles (adapters guarantee
    this ordering).

    Args:
        candles: Iterable of canonical candles.

    Returns:
        DataFrame indexed by ``bar_start_ts_utc``.

    Raises:
        ValueError: If no candles are provided.
    """

    if not candles:
        raise ValueError("At least one candle is required to build a dataframe")

    df = pd.DataFrame([asdict(candle) for candle in candles])
    df["bar_start_ts_utc"] = pd.to_datetime(df["bar_start_ts_utc"], utc=True)
    df.set_index("bar_start_ts_utc", inplace=True)
    return df


def plot_candles_matplotlib(
    candles: Sequence[Candle],
    *,
    annotate_timeframe: bool = True,
    show: bool = False,
):
    """Plot close price and volume trends using matplotlib.

    Args:
        candles: Canonical candle sequence.
        annotate_timeframe: When ``True`` include the timeframe/instrument in the
            title for quick visual confirmation.
        show: Whether to call :func:`matplotlib.pyplot.show` before returning.

    Returns:
        The created matplotlib ``Figure``.
    """

    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    df = candles_to_dataframe(candles)

    fig, (ax_price, ax_volume) = plt.subplots(
        2, 1, sharex=True, figsize=(10, 6), gridspec_kw={"height_ratios": [3, 1]}
    )

    df["close"].plot(ax=ax_price, marker="o", linestyle="-", label="Close")
    ax_price.set_ylabel("Close Price")
    ax_price.legend(loc="upper left")
    ax_price.grid(True, linestyle="--", alpha=0.3)

    df["volume"].fillna(0).plot(
        ax=ax_volume, kind="bar", color="gray", width=0.8, label="Volume"
    )
    ax_volume.set_ylabel("Volume")
    ax_volume.grid(True, linestyle="--", alpha=0.3)

    ax_volume.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d %H:%M UTC"))
    fig.autofmt_xdate()

    if annotate_timeframe:
        instrument = df["instrument_id"].iloc[0]
        timeframe = df["timeframe"].iloc[0]
        fig.suptitle(f"{instrument} — {timeframe}")

    if show:
        plt.show()

    return fig


def plot_candles_plotly(
    candles: Sequence[Candle],
    *,
    annotate_timeframe: bool = True,
):
    """Plot close price and volume trends using plotly.

    Args:
        candles: Canonical candle sequence.
        annotate_timeframe: When ``True`` include the timeframe/instrument in the
            figure title.

    Returns:
        A :class:`plotly.graph_objects.Figure` instance.
    """

    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    df = candles_to_dataframe(candles)

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.7, 0.3],
    )

    fig.add_trace(
        go.Scatter(
            x=df.index,
            y=df["close"],
            mode="lines+markers",
            name="Close",
        ),
        row=1,
        col=1,
    )

    fig.add_trace(
        go.Bar(x=df.index, y=df["volume"].fillna(0), name="Volume", marker_color="gray"),
        row=2,
        col=1,
    )

    layout = {
        "xaxis": {"title": "Time (UTC)"},
        "yaxis": {"title": "Close Price"},
        "yaxis2": {"title": "Volume"},
        "hovermode": "x unified",
    }

    fig.update_layout(**layout)

    if annotate_timeframe:
        instrument = df["instrument_id"].iloc[0]
        timeframe = df["timeframe"].iloc[0]
        fig.update_layout(title=f"{instrument} — {timeframe}")

    fig.update_xaxes(showgrid=True)
    fig.update_yaxes(showgrid=True)

    return fig
