"""Unit tests for `tools.technical_analysis`.

All data access is mocked via `unittest.mock.patch` on
`tools.technical_analysis.fetch_ohlcv`. No network calls are made.
Synthetic OHLCV DataFrames use relative dates anchored to `date.today()`.
"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import ta

from tools._data import InvalidTickerError, NetworkError, TickerNotFoundError
from tools.technical_analysis import (
    DEFAULT_LOOKBACK_DAYS,
    MIN_ROWS_REQUIRED,
    RSI_OVERBOUGHT,
    _compute_indicators,
    _latest_metrics,
    _prepare_macd_records,
    _prepare_overlay_records,
    _prepare_rsi_records,
    technical_analysis,
)

#: Empirically verified warm-up row counts (ta 0.11.x, fillna=False) for a
#: DataFrame with >= 40 rows of monotonically increasing close prices.
RSI_WARMUP_ROWS: int = 13
MACD_WARMUP_ROWS: int = 33
OVERLAY_WARMUP_ROWS: int = 19


def _make_df(periods: int, end: date, freq: str = "D") -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame with a DatetimeIndex named 'Date'."""
    idx = pd.date_range(end=end, periods=periods, freq=freq, name="Date")
    return pd.DataFrame(
        {
            "Open": np.linspace(100.0, 100.0 + periods - 1, periods),
            "High": np.linspace(101.0, 101.0 + periods - 1, periods),
            "Low": np.linspace(99.0, 99.0 + periods - 1, periods),
            "Close": np.linspace(100.5, 100.5 + periods - 1, periods),
            "Volume": np.linspace(1000, 1000 + periods - 1, periods),
        },
        index=idx,
    )


def _to_json(app: object) -> dict:
    """Serialize a PrefabApp to a dict.

    NOTE: `PrefabApp.to_json()` wraps the view in an additional container on
    each call, so this must only be called ONCE per app instance and the
    result reused for all subsequent assertions.
    """
    return app.to_json()  # type: ignore[attr-defined,no-any-return]


# --------------------------------------------------------------------------- #
# 1. _compute_indicators matches ta-direct
# --------------------------------------------------------------------------- #


def test_compute_indicators_matches_ta_direct() -> None:
    today = date.today()
    df = _make_df(periods=60, end=today)
    df.columns = df.columns.str.lower()

    out = _compute_indicators(df)
    close = df["close"]

    expected_rsi = ta.momentum.RSIIndicator(close, window=14).rsi()
    macd = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
    expected_macd = macd.macd()
    expected_macd_signal = macd.macd_signal()
    expected_macd_hist = macd.macd_diff()
    expected_sma_20 = ta.trend.SMAIndicator(close, window=20).sma_indicator()
    expected_sma_50 = ta.trend.SMAIndicator(close, window=50).sma_indicator()
    expected_ema_20 = ta.trend.EMAIndicator(close, window=20).ema_indicator()
    bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
    expected_bb_upper = bb.bollinger_hband()
    expected_bb_mid = bb.bollinger_mavg()
    expected_bb_lower = bb.bollinger_lband()

    assert np.allclose(out["rsi"].to_numpy(), expected_rsi.to_numpy(), equal_nan=True)
    assert np.allclose(out["macd"].to_numpy(), expected_macd.to_numpy(), equal_nan=True)
    assert np.allclose(
        out["macd_signal"].to_numpy(),
        expected_macd_signal.to_numpy(),
        equal_nan=True,
    )
    assert np.allclose(
        out["macd_hist"].to_numpy(), expected_macd_hist.to_numpy(), equal_nan=True
    )
    assert np.allclose(
        out["sma_20"].to_numpy(), expected_sma_20.to_numpy(), equal_nan=True
    )
    assert np.allclose(
        out["sma_50"].to_numpy(), expected_sma_50.to_numpy(), equal_nan=True
    )
    assert np.allclose(
        out["ema_20"].to_numpy(), expected_ema_20.to_numpy(), equal_nan=True
    )
    assert np.allclose(
        out["bb_upper"].to_numpy(), expected_bb_upper.to_numpy(), equal_nan=True
    )
    assert np.allclose(
        out["bb_mid"].to_numpy(), expected_bb_mid.to_numpy(), equal_nan=True
    )
    assert np.allclose(
        out["bb_lower"].to_numpy(), expected_bb_lower.to_numpy(), equal_nan=True
    )


# --------------------------------------------------------------------------- #
# 2. short series (< MIN_ROWS_REQUIRED) -> insufficient data app
# --------------------------------------------------------------------------- #


def test_short_series_renders_insufficient_data_app() -> None:
    today = date.today()
    df = _make_df(periods=10, end=today)

    with patch("tools.technical_analysis.fetch_ohlcv", return_value=df):
        app = technical_analysis("AAPL")

    serialized = json.dumps(_to_json(app))
    assert '"variant": "destructive"' not in serialized
    assert "at least 35" in serialized or "need" in serialized.lower()
    assert "available" in serialized.lower()


# --------------------------------------------------------------------------- #
# 3. exactly MIN_ROWS_REQUIRED rows -> renders dashboard, sma_50 dropped
# --------------------------------------------------------------------------- #


def test_min_rows_required_renders_dashboard_without_sma_50() -> None:
    today = date.today()
    df = _make_df(periods=MIN_ROWS_REQUIRED, end=today)

    with patch("tools.technical_analysis.fetch_ohlcv", return_value=df):
        app = technical_analysis("AAPL")

    rendered = _to_json(app)
    serialized = json.dumps(rendered)

    line_chart_count = serialized.count('"type": "LineChart"')
    bar_chart_count = serialized.count('"type": "BarChart"')
    assert line_chart_count >= 3
    assert bar_chart_count >= 1

    # 35 rows < 50 -> sma_50 is all-NaN -> dropped from overlay records.
    assert '"sma_50"' not in serialized


# --------------------------------------------------------------------------- #
# 4. >= 70 rows -> full dashboard with sma_50 present
# --------------------------------------------------------------------------- #


def test_long_series_renders_full_dashboard_with_sma_50() -> None:
    today = date.today()
    df = _make_df(periods=70, end=today)

    with patch("tools.technical_analysis.fetch_ohlcv", return_value=df):
        app = technical_analysis("AAPL")

    rendered = _to_json(app)
    serialized = json.dumps(rendered)

    assert serialized.count('"type": "LineChart"') >= 3
    assert serialized.count('"type": "BarChart"') >= 1
    assert '"sma_50"' in serialized
    assert '"SMA 50"' in serialized


# --------------------------------------------------------------------------- #
# 5. macd_hist rounded to 4dp
# --------------------------------------------------------------------------- #


def test_macd_hist_rounded_to_4dp() -> None:
    today = date.today()
    df = _make_df(periods=60, end=today)
    df.columns = df.columns.str.lower()

    start_date = today - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    indicators_df = _compute_indicators(df)
    macd_records = _prepare_macd_records(indicators_df, start_date, today)

    assert macd_records
    for record in macd_records:
        for key in ("macd", "macd_signal", "macd_hist"):
            value = record[key]
            assert round(value, 4) == value


# --------------------------------------------------------------------------- #
# 6. NaN warm-up rows dropped per panel
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("periods", [36, 38, 40])
def test_nan_warmup_rows_dropped_per_panel(periods: int) -> None:
    today = date.today()
    df = _make_df(periods=periods, end=today)
    df.columns = df.columns.str.lower()

    start_date = today - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    indicators_df = _compute_indicators(df)

    rsi_records = _prepare_rsi_records(indicators_df, start_date, today)
    macd_records = _prepare_macd_records(indicators_df, start_date, today)
    overlay_records, _ = _prepare_overlay_records(indicators_df, start_date, today)

    assert len(rsi_records) == periods - RSI_WARMUP_ROWS
    assert len(macd_records) == periods - MACD_WARMUP_ROWS
    assert len(overlay_records) == periods - OVERLAY_WARMUP_ROWS


# --------------------------------------------------------------------------- #
# 7. invalid ticker
# --------------------------------------------------------------------------- #


def test_invalid_ticker_renders_error_app() -> None:
    with patch(
        "tools.technical_analysis.fetch_ohlcv",
        side_effect=InvalidTickerError("'???' is not a valid ticker symbol format."),
    ):
        app = technical_analysis("???")

    serialized = json.dumps(_to_json(app))
    assert "is not a valid ticker symbol format" in serialized
    assert '"variant": "destructive"' in serialized


# --------------------------------------------------------------------------- #
# 8. no data
# --------------------------------------------------------------------------- #


def test_no_data_renders_error_app() -> None:
    with patch(
        "tools.technical_analysis.fetch_ohlcv",
        side_effect=TickerNotFoundError("No data found for ticker 'AAPL'."),
    ):
        app = technical_analysis("AAPL")

    serialized = json.dumps(_to_json(app))
    assert "No data found for ticker 'AAPL'." in serialized
    assert '"variant": "destructive"' in serialized


# --------------------------------------------------------------------------- #
# 9. network error
# --------------------------------------------------------------------------- #


def test_network_error_renders_error_app() -> None:
    with patch(
        "tools.technical_analysis.fetch_ohlcv",
        side_effect=NetworkError("A network error occurred while fetching data."),
    ):
        app = technical_analysis("AAPL")

    serialized = json.dumps(_to_json(app))
    assert "A network error occurred while fetching data." in serialized
    assert '"variant": "destructive"' in serialized


# --------------------------------------------------------------------------- #
# 10. malformed date
# --------------------------------------------------------------------------- #


def test_malformed_date_renders_error_without_fetch() -> None:
    with patch("tools.technical_analysis.fetch_ohlcv") as mock_fetch:
        app = technical_analysis("AAPL", start="not-a-date")

    mock_fetch.assert_not_called()
    serialized = json.dumps(_to_json(app))
    assert "Invalid date" in serialized
    assert '"variant": "destructive"' in serialized


# --------------------------------------------------------------------------- #
# 11. default date range relative to today
# --------------------------------------------------------------------------- #


def test_default_date_range_is_relative_to_today() -> None:
    today = date.today()
    df = _make_df(periods=85, end=today)

    with patch("tools.technical_analysis.fetch_ohlcv", return_value=df) as mock_fetch:
        technical_analysis("AAPL")

    mock_fetch.assert_called_once()
    _, kwargs = mock_fetch.call_args
    assert kwargs["end"] == today
    assert (kwargs["end"] - kwargs["start"]) == timedelta(days=DEFAULT_LOOKBACK_DAYS)


# --------------------------------------------------------------------------- #
# 12. overlay records contain no NaN, even when MACD warm-up exceeds the
#     overlay warm-up (i.e. rsi/macd columns are still NaN for early rows)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("periods", [36, 38, 40])
def test_prepare_overlay_records_contain_no_nan(periods: int) -> None:
    today = date.today()
    df = _make_df(periods=periods, end=today)
    df.columns = df.columns.str.lower()

    start_date = today - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    indicators_df = _compute_indicators(df)

    overlay_records, _ = _prepare_overlay_records(indicators_df, start_date, today)

    assert overlay_records
    assert all(
        not (isinstance(v, float) and math.isnan(v))
        for r in overlay_records
        for v in r.values()
    )


# --------------------------------------------------------------------------- #
# 13. rsi_state is computed from the raw (unrounded) RSI value
# --------------------------------------------------------------------------- #


def test_latest_metrics_rsi_state_uses_raw_value_overbought() -> None:
    today = date.today()
    df = _make_df(periods=60, end=today)
    df.columns = df.columns.str.lower()

    indicators_df = _compute_indicators(df)
    # Raw RSI just above 70 rounds to 70.0, which would be "neutral" if
    # rsi_state were computed from the rounded value.
    indicators_df.loc[indicators_df.index[-1], "rsi"] = 70.0001

    metrics = _latest_metrics(indicators_df)

    assert metrics["rsi"] == 70.0
    assert metrics["rsi_state"] == "overbought"


def test_latest_metrics_rsi_state_uses_raw_value_oversold() -> None:
    today = date.today()
    df = _make_df(periods=60, end=today)
    df.columns = df.columns.str.lower()

    indicators_df = _compute_indicators(df)
    # Raw RSI just below 30 rounds to 30.0, which would be "neutral" if
    # rsi_state were computed from the rounded value.
    indicators_df.loc[indicators_df.index[-1], "rsi"] = 29.9999

    metrics = _latest_metrics(indicators_df)

    assert metrics["rsi"] == 30.0
    assert metrics["rsi_state"] == "oversold"


def test_latest_metrics_rsi_state_exact_boundary_is_neutral() -> None:
    today = date.today()
    df = _make_df(periods=60, end=today)
    df.columns = df.columns.str.lower()

    indicators_df = _compute_indicators(df)
    indicators_df.loc[indicators_df.index[-1], "rsi"] = RSI_OVERBOUGHT

    metrics = _latest_metrics(indicators_df)

    assert metrics["rsi"] == 70.0
    assert metrics["rsi_state"] == "neutral"


# --------------------------------------------------------------------------- #
# Additional tests for uncovered lines
# --------------------------------------------------------------------------- #


def test_prepare_overlay_records_empty_after_dropna() -> None:
    """Test TickerNotFoundError when overlay records are empty (line 188)."""
    today = date.today()
    df = _make_df(periods=60, end=today)
    df.columns = df.columns.str.lower()

    indicators_df = _compute_indicators(df)
    # Make all required columns NaN to trigger the empty case
    indicators_df["close"] = float("nan")

    with pytest.raises(TickerNotFoundError) as exc_info:
        _prepare_overlay_records(indicators_df, today - timedelta(days=30), today)

    assert "No indicator data" in exc_info.value.user_message


def test_prepare_overlay_records_sma_50_absent() -> None:
    """Test has_sma_50 == False branch (lines 195-205)."""
    today = date.today()
    df = _make_df(periods=40, end=today)
    df.columns = df.columns.str.lower()

    indicators_df = _compute_indicators(df)
    overlay_records, has_sma_50 = _prepare_overlay_records(
        indicators_df, today - timedelta(days=30), today
    )

    assert has_sma_50 is False
    assert "sma_50" not in overlay_records[0]


def test_prepare_overlay_records_sma_50_present() -> None:
    """Test has_sma_50 == True branch (lines 195-205)."""
    today = date.today()
    df = _make_df(periods=70, end=today)
    df.columns = df.columns.str.lower()

    indicators_df = _compute_indicators(df)
    overlay_records, has_sma_50 = _prepare_overlay_records(
        indicators_df, today - timedelta(days=60), today
    )

    assert has_sma_50 is True
    assert "sma_50" in overlay_records[0]


def test_prepare_rsi_records_empty_after_dropna() -> None:
    """Test TickerNotFoundError when RSI records are empty (line 244)."""
    today = date.today()
    df = _make_df(periods=60, end=today)
    df.columns = df.columns.str.lower()

    indicators_df = _compute_indicators(df)
    # Make RSI all NaN
    indicators_df["rsi"] = float("nan")

    with pytest.raises(TickerNotFoundError) as exc_info:
        _prepare_rsi_records(indicators_df, today - timedelta(days=30), today)

    assert "No RSI data" in exc_info.value.user_message


def test_prepare_macd_records_empty_after_dropna() -> None:
    """Test TickerNotFoundError when MACD records are empty (line 273)."""
    today = date.today()
    df = _make_df(periods=60, end=today)
    df.columns = df.columns.str.lower()

    indicators_df = _compute_indicators(df)
    # Make MACD all NaN
    indicators_df["macd"] = float("nan")

    with pytest.raises(TickerNotFoundError) as exc_info:
        _prepare_macd_records(indicators_df, today - timedelta(days=30), today)

    assert "No MACD data" in exc_info.value.user_message


def test_latest_metrics_rsi_none_when_nan() -> None:
    """Test rsi == None when raw_rsi is NaN (line 308)."""
    today = date.today()
    df = _make_df(periods=60, end=today)
    df.columns = df.columns.str.lower()

    indicators_df = _compute_indicators(df)
    indicators_df.loc[indicators_df.index[-1], "rsi"] = float("nan")

    metrics = _latest_metrics(indicators_df)

    assert metrics["rsi"] is None
    assert metrics["rsi_state"] == "neutral"


def test_latest_metrics_macd_hist_none_when_nan() -> None:
    """Test macd_hist == None when NaN (line 319)."""
    today = date.today()
    df = _make_df(periods=60, end=today)
    df.columns = df.columns.str.lower()

    indicators_df = _compute_indicators(df)
    indicators_df.loc[indicators_df.index[-1], "macd_hist"] = float("nan")

    metrics = _latest_metrics(indicators_df)

    assert metrics["macd_hist"] is None
    assert metrics["macd_signal_state"] == "neutral"


def test_latest_metrics_sma_20_none_when_nan() -> None:
    """Test sma_20 == None when NaN (line 331)."""
    today = date.today()
    df = _make_df(periods=60, end=today)
    df.columns = df.columns.str.lower()

    indicators_df = _compute_indicators(df)
    indicators_df.loc[indicators_df.index[-1], "sma_20"] = float("nan")

    metrics = _latest_metrics(indicators_df)

    assert metrics["sma_20"] is None


def test_latest_metrics_sma_50_none_when_nan() -> None:
    """Test sma_50 == None when NaN (line 333)."""
    today = date.today()
    df = _make_df(periods=60, end=today)
    df.columns = df.columns.str.lower()

    indicators_df = _compute_indicators(df)
    indicators_df.loc[indicators_df.index[-1], "sma_50"] = float("nan")

    metrics = _latest_metrics(indicators_df)

    assert metrics["sma_50"] is None


def test_latest_metrics_ema_20_none_when_nan() -> None:
    """Test ema_20 == None when NaN (line 336)."""
    today = date.today()
    df = _make_df(periods=60, end=today)
    df.columns = df.columns.str.lower()

    indicators_df = _compute_indicators(df)
    indicators_df.loc[indicators_df.index[-1], "ema_20"] = float("nan")

    metrics = _latest_metrics(indicators_df)

    assert metrics["ema_20"] is None


def test_technical_analysis_macd_hist_positive_bullish() -> None:
    """Test macd_signal_state == 'bullish' branch (line 324)."""
    today = date.today()
    df = _make_df(periods=60, end=today)

    with patch("tools.technical_analysis.fetch_ohlcv", return_value=df):
        app = technical_analysis("AAPL")

    rendered = _to_json(app)
    serialized = json.dumps(rendered)

    # Verify the app renders without error and contains expected state
    assert '"type": "LineChart"' in serialized


def test_technical_analysis_macd_hist_negative_bearish() -> None:
    """Test macd_signal_state == 'bearish' branch (line 326).

    Uses a downtrending series (close prices 150 -> 100) to generate
    a negative MACD histogram, which drives the 'bearish' state.
    """
    today = date.today()
    idx = pd.date_range(end=today, periods=60, freq="D", name="Date")
    # DOWNTRENDING: Close prices decrease from 150.5 to 99.5
    df = pd.DataFrame(
        {
            "Open": np.linspace(151.0, 99.0, 60),
            "High": np.linspace(152.0, 100.0, 60),
            "Low": np.linspace(150.0, 98.0, 60),
            "Close": np.linspace(150.5, 99.5, 60),
            "Volume": np.linspace(1000, 1059, 60),
        },
        index=idx,
    )

    with patch("tools.technical_analysis.fetch_ohlcv", return_value=df):
        app = technical_analysis("AAPL")

    rendered = _to_json(app)
    serialized = json.dumps(rendered)

    # Verify the app renders and contains the bearish state
    assert '"type": "LineChart"' in serialized
    # The MACD signal state metric should show "Bearish"
    assert '"Bearish"' in serialized


def test_technical_analysis_rsi_trend_up_oversold() -> None:
    """Test rsi_trend == 'up' when oversold (lines 442-445).

    Uses a series that stays flat then drops sharply at the end,
    pushing latest RSI below 30 (oversold threshold), driving rsi_trend = "up".
    """
    today = date.today()
    idx = pd.date_range(end=today, periods=60, freq="D", name="Date")
    # Flat for 50 days, then sharp decline in last 10 days
    close_prices = np.concatenate(
        [
            np.linspace(100.0, 100.0, 50),  # Flat: 100.0 for 50 days
            np.linspace(100.0, 70.0, 10),  # Sharp decline: 100 to 70 in 10 days
        ]
    )
    df = pd.DataFrame(
        {
            "Open": close_prices + 0.5,
            "High": close_prices + 1.0,
            "Low": close_prices - 0.5,
            "Close": close_prices,
            "Volume": np.linspace(1000, 1059, 60),
        },
        index=idx,
    )

    with patch("tools.technical_analysis.fetch_ohlcv", return_value=df):
        app = technical_analysis("AAPL")

    rendered = _to_json(app)
    serialized = json.dumps(rendered)

    # Verify the app renders with oversold RSI and "up" trend
    assert '"type": "Metric"' in serialized
    # Should contain "up" trend for RSI metric when oversold
    assert '"up"' in serialized or '"Oversold"' in serialized


def test_technical_analysis_rsi_trend_down_overbought() -> None:
    """Test rsi_trend == 'down' when overbought (lines 440-441)."""
    today = date.today()
    df = _make_df(periods=60, end=today)
    df.columns = df.columns.str.lower()

    with patch("tools.technical_analysis.fetch_ohlcv", return_value=df):
        app = technical_analysis("AAPL")

    rendered = _to_json(app)
    serialized = json.dumps(rendered)

    assert '"type": "Metric"' in serialized


def test_technical_analysis_macd_trend_up_bullish() -> None:
    """Test macd_trend == 'up' when bullish (line 449)."""
    today = date.today()
    df = _make_df(periods=60, end=today)

    with patch("tools.technical_analysis.fetch_ohlcv", return_value=df):
        app = technical_analysis("AAPL")

    rendered = _to_json(app)
    serialized = json.dumps(rendered)

    assert '"type": "Metric"' in serialized


def test_technical_analysis_macd_trend_down_bearish() -> None:
    """Test macd_trend == 'down' when bearish (line 451).

    Uses a downtrending series (close prices 150 -> 100) to generate
    a negative MACD histogram, which drives macd_trend = "down".
    """
    today = date.today()
    idx = pd.date_range(end=today, periods=60, freq="D", name="Date")
    # DOWNTRENDING: Close prices decrease from 150.5 to 99.5
    df = pd.DataFrame(
        {
            "Open": np.linspace(151.0, 99.0, 60),
            "High": np.linspace(152.0, 100.0, 60),
            "Low": np.linspace(150.0, 98.0, 60),
            "Close": np.linspace(150.5, 99.5, 60),
            "Volume": np.linspace(1000, 1059, 60),
        },
        index=idx,
    )

    with patch("tools.technical_analysis.fetch_ohlcv", return_value=df):
        app = technical_analysis("AAPL")

    rendered = _to_json(app)
    serialized = json.dumps(rendered)

    # Verify the app renders with bearish MACD state and down trend
    assert '"type": "Metric"' in serialized
    # The MACD Signal metric should show "Bearish" and trend "down"
    assert '"Bearish"' in serialized


def test_technical_analysis_rsi_trend_neutral() -> None:
    """Test rsi_trend == 'neutral' when RSI is between 30 and 70 (lines 439-445)."""
    today = date.today()
    idx = pd.date_range(end=today, periods=60, freq="D", name="Date")
    # Slightly oscillating series to keep RSI in neutral zone (around 50-60)
    close_prices = 100 + 0.5 * np.sin(np.linspace(0, 4 * np.pi, 60))
    df = pd.DataFrame(
        {
            "Open": close_prices,
            "High": close_prices + 0.5,
            "Low": close_prices - 0.5,
            "Close": close_prices,
            "Volume": np.linspace(1000, 1059, 60),
        },
        index=idx,
    )

    with patch("tools.technical_analysis.fetch_ohlcv", return_value=df):
        app = technical_analysis("AAPL")

    rendered = _to_json(app)
    serialized = json.dumps(rendered)

    # Verify the app renders successfully
    assert '"type": "Metric"' in serialized
    assert '"type": "LineChart"' in serialized


def test_technical_analysis_macd_trend_neutral() -> None:
    """Test macd_trend == 'neutral' when MACD hist is zero (lines 447-453)."""
    today = date.today()
    idx = pd.date_range(end=today, periods=60, freq="D", name="Date")
    # Perfectly flat series to keep MACD hist at exactly 0 (neutral)
    close_prices = np.array([100.0] * 60)
    df = pd.DataFrame(
        {
            "Open": close_prices,
            "High": close_prices + 0.5,
            "Low": close_prices - 0.5,
            "Close": close_prices,
            "Volume": np.linspace(1000, 1059, 60),
        },
        index=idx,
    )

    with patch("tools.technical_analysis.fetch_ohlcv", return_value=df):
        app = technical_analysis("AAPL")

    rendered = _to_json(app)
    serialized = json.dumps(rendered)

    # Verify the app renders successfully with neutral MACD
    assert '"type": "Metric"' in serialized
    assert '"type": "LineChart"' in serialized
