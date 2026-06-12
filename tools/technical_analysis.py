"""Technical analysis snapshot dashboard tool.

Exposes a single FastMCP app-tool, `technical_analysis`, that renders a
technical analysis dashboard (latest indicator metrics, a price chart with
Bollinger Bands and moving-average overlays, an RSI sub-panel, and a MACD
sub-panel) for a given ticker and date range.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

import pandas as pd
import ta
from fastmcp import FastMCP
from prefab_ui import PrefabApp
from prefab_ui.components import (
    Badge,
    Card,
    Column,
    Metric,
    Row,
    Separator,
    Text,
)
from prefab_ui.components.charts import BarChart, ChartSeries, LineChart

from tools._data import StockDataError, TickerNotFoundError, fetch_ohlcv

#: Default number of days to look back when no `start` date is provided.
DEFAULT_LOOKBACK_DAYS: int = 250

#: Maximum span (in days) for which dates are rendered as "%b %d" instead
#: of the full "%Y-%m-%d" form.
SHORT_HORIZON_DAYS: int = 180

#: Window (in periods) used for the RSI indicator.
RSI_WINDOW: int = 14

#: Fast/slow/signal windows used for the MACD indicator.
MACD_WINDOW_FAST: int = 12
MACD_WINDOW_SLOW: int = 26
MACD_WINDOW_SIGN: int = 9

#: Window used for the short simple moving average.
SMA_WINDOW: int = 20

#: Window used for the long simple moving average.
SMA_LONG_WINDOW: int = 50

#: Window used for the exponential moving average.
EMA_WINDOW: int = 20

#: Window and standard-deviation multiplier used for Bollinger Bands.
BB_WINDOW: int = 20
BB_WINDOW_DEV: int = 2

#: RSI thresholds for overbought/oversold classification.
RSI_OVERBOUGHT: float = 70.0
RSI_OVERSOLD: float = 30.0

#: Minimum number of trading-day rows required to compute the full set of
#: indicators (notably the MACD warm-up period).
MIN_ROWS_REQUIRED: int = 35

technical_analysis_mcp: FastMCP = FastMCP("TechnicalAnalysis")


def _resolve_date_range(start: str | None, end: str | None) -> tuple[date, date]:
    """Resolve the effective `(start_date, end_date)` range.

    Args:
        start: Optional ISO "YYYY-MM-DD" start date. If `None`, defaults to
            `end_date - timedelta(days=DEFAULT_LOOKBACK_DAYS)`.
        end: Optional ISO "YYYY-MM-DD" end date. If `None`, defaults to
            today (UTC).

    Returns:
        A tuple of `(start_date, end_date)` as `date` objects.

    Raises:
        ValueError: If `start` or `end` is not a valid ISO "YYYY-MM-DD"
            date string. Propagates from `date.fromisoformat`.
    """
    today = datetime.now(timezone.utc).date()
    end_date = date.fromisoformat(end) if end else today
    start_date = (
        date.fromisoformat(start)
        if start
        else end_date - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    )
    return start_date, end_date


def _compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Compute technical indicators for an OHLCV DataFrame.

    Args:
        df: OHLCV DataFrame indexed by date/datetime, as returned by
            `fetch_ohlcv`. Must contain a `close` column.

    Returns:
        A copy of `df` with additional columns: `rsi`, `macd`,
        `macd_signal`, `macd_hist`, `sma_20`, `sma_50`, `ema_20`,
        `bb_upper`, `bb_mid`, `bb_lower`. Warm-up periods are left as NaN
        (no `fillna`). This function does not raise.
    """
    out = df.copy()
    out.columns = out.columns.str.lower()
    close = out["close"]

    out["rsi"] = ta.momentum.RSIIndicator(close, window=RSI_WINDOW).rsi()

    macd = ta.trend.MACD(
        close,
        window_slow=MACD_WINDOW_SLOW,
        window_fast=MACD_WINDOW_FAST,
        window_sign=MACD_WINDOW_SIGN,
    )
    out["macd"] = macd.macd()
    out["macd_signal"] = macd.macd_signal()
    out["macd_hist"] = macd.macd_diff()

    out["sma_20"] = ta.trend.SMAIndicator(close, window=SMA_WINDOW).sma_indicator()
    out["sma_50"] = ta.trend.SMAIndicator(close, window=SMA_LONG_WINDOW).sma_indicator()
    out["ema_20"] = ta.trend.EMAIndicator(close, window=EMA_WINDOW).ema_indicator()

    bb = ta.volatility.BollingerBands(close, window=BB_WINDOW, window_dev=BB_WINDOW_DEV)
    out["bb_upper"] = bb.bollinger_hband()
    out["bb_mid"] = bb.bollinger_mavg()
    out["bb_lower"] = bb.bollinger_lband()

    return out


def _format_dates(df: pd.DataFrame, start_date: date, end_date: date) -> pd.DataFrame:
    """Reset the index, lowercase columns, and format the date column.

    Args:
        df: A DataFrame indexed by date/datetime.
        start_date: Start of the requested date range (used to choose the
            date display format).
        end_date: End of the requested date range (used to choose the date
            display format).

    Returns:
        A new DataFrame with the former index as a "date" column,
        lowercase column names, and dates formatted as either "%b %d"
        (short horizons) or "%Y-%m-%d" (longer horizons).
    """
    df = df.reset_index()
    df = df.rename(columns={df.columns[0]: "date"})
    df.columns = df.columns.str.lower()

    span_days = (end_date - start_date).days
    fmt = "%b %d" if span_days <= SHORT_HORIZON_DAYS else "%Y-%m-%d"
    df["date"] = pd.to_datetime(df["date"]).dt.strftime(fmt)

    return df


def _prepare_overlay_records(
    df: pd.DataFrame, start_date: date, end_date: date
) -> tuple[list[dict[str, Any]], bool]:
    """Build price/Bollinger-band/moving-average overlay chart records.

    Args:
        df: Indicator DataFrame, as returned by `_compute_indicators`.
        start_date: Start of the requested date range.
        end_date: End of the requested date range.

    Returns:
        A tuple of `(records, has_sma_50)` where `records` is a list of
        row dicts (keys: date, close, bb_upper, bb_mid, bb_lower, sma_20,
        ema_20, and sma_50 if present) and `has_sma_50` indicates whether
        any SMA-50 values are available in the requested range.

    Raises:
        TickerNotFoundError: If no rows remain after dropping rows with
            missing close/Bollinger-band/SMA-20/EMA-20 values.
    """
    subset = df.dropna(
        subset=["close", "bb_upper", "bb_mid", "bb_lower", "sma_20", "ema_20"]
    ).copy()

    if subset.empty:
        raise TickerNotFoundError(
            "No indicator data available for the requested range."
        )

    has_sma_50 = bool(subset["sma_50"].notna().any())

    round_cols = ["close", "bb_upper", "bb_mid", "bb_lower", "sma_20", "ema_20"]
    if has_sma_50:
        round_cols.append("sma_50")
    for col in round_cols:
        subset[col] = subset[col].round(2)

    if has_sma_50:
        subset["sma_50"] = (
            subset["sma_50"].astype(object).where(subset["sma_50"].notna(), None)
        )
    else:
        subset = subset.drop(columns=["sma_50"])

    subset = _format_dates(subset, start_date, end_date)

    overlay_cols = [
        "date",
        "close",
        "bb_upper",
        "bb_mid",
        "bb_lower",
        "sma_20",
        "ema_20",
    ]
    if has_sma_50:
        overlay_cols.append("sma_50")

    return subset[overlay_cols].to_dict(orient="records"), has_sma_50


def _prepare_rsi_records(
    df: pd.DataFrame, start_date: date, end_date: date
) -> list[dict[str, Any]]:
    """Build RSI sub-panel chart records.

    Args:
        df: Indicator DataFrame, as returned by `_compute_indicators`.
        start_date: Start of the requested date range.
        end_date: End of the requested date range.

    Returns:
        A list of row dicts with keys `date` and `rsi` (rounded to 2dp).

    Raises:
        TickerNotFoundError: If no rows remain after dropping rows with
            missing `rsi` values.
    """
    subset = df.dropna(subset=["rsi"]).copy()

    if subset.empty:
        raise TickerNotFoundError("No RSI data available for the requested range.")

    subset["rsi"] = subset["rsi"].round(2)
    subset = _format_dates(subset, start_date, end_date)

    return subset[["date", "rsi"]].to_dict(orient="records")


def _prepare_macd_records(
    df: pd.DataFrame, start_date: date, end_date: date
) -> list[dict[str, Any]]:
    """Build MACD sub-panel chart records.

    Args:
        df: Indicator DataFrame, as returned by `_compute_indicators`.
        start_date: Start of the requested date range.
        end_date: End of the requested date range.

    Returns:
        A list of row dicts with keys `date`, `macd`, `macd_signal`, and
        `macd_hist` (each rounded to 4dp).

    Raises:
        TickerNotFoundError: If no rows remain after dropping rows with
            missing `macd`/`macd_signal`/`macd_hist` values.
    """
    subset = df.dropna(subset=["macd", "macd_signal", "macd_hist"]).copy()

    if subset.empty:
        raise TickerNotFoundError("No MACD data available for the requested range.")

    for col in ("macd", "macd_signal", "macd_hist"):
        subset[col] = subset[col].round(4)

    subset = _format_dates(subset, start_date, end_date)

    return subset[["date", "macd", "macd_signal", "macd_hist"]].to_dict(
        orient="records"
    )


def _latest_metrics(df: pd.DataFrame) -> dict[str, Any]:
    """Summarize the most recent indicator values.

    Args:
        df: Indicator DataFrame, as returned by `_compute_indicators`. Must
            be non-empty.

    Returns:
        A dict with keys:
            - `close` (float, 2dp)
            - `rsi` (float, 2dp, or `None`)
            - `rsi_state` (one of "overbought", "oversold", "neutral")
            - `macd_signal_state` (one of "bullish", "bearish", "neutral")
            - `macd_hist` (float, 4dp, or `None`)
            - `sma_20` (float, 2dp, or `None`)
            - `sma_50` (float, 2dp, or `None`)
            - `ema_20` (float, 2dp, or `None`)
    """
    last = df.iloc[-1]

    close = float(round(last["close"], 2))

    raw_rsi = last["rsi"]
    rsi: float | None = float(round(raw_rsi, 2)) if pd.notna(raw_rsi) else None

    rsi_state: Literal["overbought", "oversold", "neutral"]
    if pd.notna(raw_rsi) and raw_rsi > RSI_OVERBOUGHT:
        rsi_state = "overbought"
    elif pd.notna(raw_rsi) and raw_rsi < RSI_OVERSOLD:
        rsi_state = "oversold"
    else:
        rsi_state = "neutral"

    macd_hist: float | None = (
        float(round(last["macd_hist"], 4)) if pd.notna(last["macd_hist"]) else None
    )

    macd_signal_state: Literal["bullish", "bearish", "neutral"]
    if macd_hist is not None and macd_hist > 0:
        macd_signal_state = "bullish"
    elif macd_hist is not None and macd_hist < 0:
        macd_signal_state = "bearish"
    else:
        macd_signal_state = "neutral"

    sma_20: float | None = (
        float(round(last["sma_20"], 2)) if pd.notna(last["sma_20"]) else None
    )
    sma_50: float | None = (
        float(round(last["sma_50"], 2)) if pd.notna(last["sma_50"]) else None
    )
    ema_20: float | None = (
        float(round(last["ema_20"], 2)) if pd.notna(last["ema_20"]) else None
    )

    return {
        "close": close,
        "rsi": rsi,
        "rsi_state": rsi_state,
        "macd_signal_state": macd_signal_state,
        "macd_hist": macd_hist,
        "sma_20": sma_20,
        "sma_50": sma_50,
        "ema_20": ema_20,
    }


def _render_error_app(message: str) -> PrefabApp:
    """Render an error-state Prefab app.

    Args:
        message: Human-readable error message to display.

    Returns:
        A `PrefabApp` showing a destructive badge and the error message.
    """
    with PrefabApp() as app:
        with Column(gap=4, css_class="p-6"):
            with Card(css_class="p-6"):
                with Column(gap=2):
                    Badge("Unable to load technical analysis", variant="destructive")
                    Text(message)
    return app


def _render_insufficient_data_app(ticker: str, row_count: int) -> PrefabApp:
    """Render an insufficient-data-state Prefab app.

    Args:
        ticker: Ticker symbol requested by the caller (used in the
            displayed message).
        row_count: Number of trading-day rows actually available.

    Returns:
        A `PrefabApp` showing a secondary (non-destructive) badge and a
        message explaining the minimum data requirement.
    """
    normalized_ticker = ticker.strip().upper()
    message = (
        f"Technical indicators need at least {MIN_ROWS_REQUIRED} trading days "
        f"of data; only {row_count} were available for {normalized_ticker} in "
        "this range. Try a longer date range."
    )
    with PrefabApp() as app:
        with Column(gap=4, css_class="p-6"):
            with Card(css_class="p-6"):
                with Column(gap=2):
                    Badge("Not enough data", variant="secondary")
                    Text(message)
    return app


@technical_analysis_mcp.tool(app=True)
def technical_analysis(
    ticker: str, start: str | None = None, end: str | None = None
) -> PrefabApp:
    """Render a technical analysis snapshot dashboard for a ticker.

    Args:
        ticker: Ticker symbol to fetch, e.g. "AAPL".
        start: Optional ISO "YYYY-MM-DD" start date. Defaults to
            `DEFAULT_LOOKBACK_DAYS` days before `end`.
        end: Optional ISO "YYYY-MM-DD" end date. Defaults to today (UTC).

    Returns:
        A `PrefabApp` showing latest indicator metrics, a price chart with
        Bollinger Band and moving-average overlays, an RSI sub-panel, and a
        MACD sub-panel. If the request fails or there is not enough data,
        an error-state or insufficient-data-state app is returned instead.
    """
    try:
        start_date, end_date = _resolve_date_range(start, end)
        df = fetch_ohlcv(ticker, start=start_date, end=end_date, interval="1d")
    except StockDataError as exc:
        return _render_error_app(exc.user_message)
    except ValueError as exc:
        return _render_error_app(f"Invalid date: {exc}. Use YYYY-MM-DD format.")

    if len(df) < MIN_ROWS_REQUIRED:
        return _render_insufficient_data_app(ticker, len(df))

    indicators_df = _compute_indicators(df)

    try:
        overlay_records, has_sma_50 = _prepare_overlay_records(
            indicators_df, start_date, end_date
        )
        rsi_records = _prepare_rsi_records(indicators_df, start_date, end_date)
        macd_records = _prepare_macd_records(indicators_df, start_date, end_date)
    except TickerNotFoundError as exc:
        return _render_error_app(exc.user_message)

    metrics = _latest_metrics(indicators_df)

    rsi_trend: Literal["up", "down", "neutral"]
    if metrics["rsi_state"] == "overbought":
        rsi_trend = "down"
    elif metrics["rsi_state"] == "oversold":
        rsi_trend = "up"
    else:
        rsi_trend = "neutral"

    macd_trend: Literal["up", "down", "neutral"]
    if metrics["macd_signal_state"] == "bullish":
        macd_trend = "up"
    elif metrics["macd_signal_state"] == "bearish":
        macd_trend = "down"
    else:
        macd_trend = "neutral"

    rsi_value = f"{metrics['rsi']:.2f}" if metrics["rsi"] is not None else "N/A"
    sma_20_value = (
        f"${metrics['sma_20']:.2f}" if metrics["sma_20"] is not None else "N/A"
    )
    ema_20_value = (
        f"${metrics['ema_20']:.2f}" if metrics["ema_20"] is not None else "N/A"
    )

    overlay_series: list[ChartSeries] = [
        ChartSeries(data_key="close", label="Close"),  # type: ignore[call-arg]
        ChartSeries(data_key="bb_upper", label="Upper Band"),  # type: ignore[call-arg]
        ChartSeries(data_key="bb_mid", label="Mid Band"),  # type: ignore[call-arg]
        ChartSeries(data_key="bb_lower", label="Lower Band"),  # type: ignore[call-arg]
        ChartSeries(data_key="sma_20", label="SMA 20"),  # type: ignore[call-arg]
        ChartSeries(data_key="ema_20", label="EMA 20"),  # type: ignore[call-arg]
    ]
    if has_sma_50:
        overlay_series.append(
            ChartSeries(data_key="sma_50", label="SMA 50")  # type: ignore[call-arg]
        )

    with PrefabApp() as app:
        with Column(gap=4, css_class="p-6"):
            with Row(gap=6):
                Metric(label=ticker, value=f"${metrics['close']:.2f}")
                Metric(label="RSI (14)", value=rsi_value, trend=rsi_trend)
                Metric(
                    label="MACD Signal",
                    value=metrics["macd_signal_state"].title(),
                    trend=macd_trend,
                )
                Metric(label="SMA 20", value=sma_20_value)
                Metric(label="EMA 20", value=ema_20_value)
                if has_sma_50 and metrics["sma_50"] is not None:
                    Metric(label="SMA 50", value=f"${metrics['sma_50']:.2f}")
            Separator()
            with Column(gap=2):
                Text("Price, Bollinger Bands & Moving Averages")
                LineChart(
                    data=overlay_records,
                    series=overlay_series,  # type: ignore[call-arg]
                    x_axis="date",  # type: ignore[call-arg]
                    show_legend=True,  # type: ignore[call-arg]
                    show_dots=False,  # type: ignore[call-arg]
                )
            Separator()
            with Column(gap=2):
                with Row(gap=4):
                    Text("RSI (14)")
                    Badge("Overbought > 70", variant="destructive")
                    Badge("Oversold < 30", variant="secondary")
                LineChart(
                    data=rsi_records,
                    series=[ChartSeries(data_key="rsi", label="RSI")],  # type: ignore[call-arg]
                    x_axis="date",  # type: ignore[call-arg]
                    show_dots=False,  # type: ignore[call-arg]
                    show_legend=False,  # type: ignore[call-arg]
                )
            Separator()
            with Column(gap=2):
                Text("MACD (12, 26, 9)")
                LineChart(
                    data=macd_records,
                    series=[
                        ChartSeries(data_key="macd", label="MACD"),  # type: ignore[call-arg]
                        ChartSeries(data_key="macd_signal", label="Signal"),  # type: ignore[call-arg]
                    ],
                    x_axis="date",  # type: ignore[call-arg]
                    show_dots=False,  # type: ignore[call-arg]
                    show_legend=True,  # type: ignore[call-arg]
                )
                BarChart(
                    data=macd_records,
                    series=[ChartSeries(data_key="macd_hist", label="Histogram")],  # type: ignore[call-arg]
                    x_axis="date",  # type: ignore[call-arg]
                    show_legend=False,  # type: ignore[call-arg]
                )

    return app
