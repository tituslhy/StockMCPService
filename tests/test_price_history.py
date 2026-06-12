"""Unit tests for `tools.price_history`.

All data access is mocked via `unittest.mock.patch` on
`tools.price_history.fetch_ohlcv`. No network calls are made. Synthetic
OHLCV DataFrames use relative dates anchored to `date.today()`.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from tools._data import InvalidTickerError, NetworkError, TickerNotFoundError
from tools.price_history import DEFAULT_LOOKBACK_DAYS, price_history


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
# 1. valid data
# --------------------------------------------------------------------------- #


def test_valid_data_renders_dashboard() -> None:
    today = date.today()
    df = _make_df(periods=30, end=today)

    with patch("tools.price_history.fetch_ohlcv", return_value=df):
        app = price_history("AAPL")

    assert app is not None
    assert app.view is not None

    rendered = _to_json(app)
    serialized = json.dumps(rendered)
    assert '"type": "LineChart"' in serialized
    assert '"type": "BarChart"' in serialized
    assert '"type": "DataTable"' in serialized

    table = next(
        c
        for c in rendered["view"]["children"][0]["children"]
        if c["type"] == "DataTable"
    )
    assert len(table["rows"]) == 30


# --------------------------------------------------------------------------- #
# 2. long horizon -> "%Y-%m-%d"
# --------------------------------------------------------------------------- #


def test_long_horizon_uses_iso_date_format() -> None:
    end = date.today()
    start = end - timedelta(days=365)
    df = _make_df(periods=365, end=end)

    with patch("tools.price_history.fetch_ohlcv", return_value=df):
        app = price_history("AAPL", start=start.isoformat(), end=end.isoformat())

    rendered = _to_json(app)
    table = next(
        c
        for c in rendered["view"]["children"][0]["children"]
        if c["type"] == "DataTable"
    )
    sample_date = table["rows"][0]["date"]
    # "%Y-%m-%d" should parse successfully.
    date.fromisoformat(sample_date)


# --------------------------------------------------------------------------- #
# 3. short horizon -> "%b %d"
# --------------------------------------------------------------------------- #


def test_short_horizon_uses_short_date_format() -> None:
    end = date.today()
    df = _make_df(periods=10, end=end)

    with patch("tools.price_history.fetch_ohlcv", return_value=df):
        app = price_history("AAPL")

    rendered = _to_json(app)
    table = next(
        c
        for c in rendered["view"]["children"][0]["children"]
        if c["type"] == "DataTable"
    )
    sample_date = table["rows"][0]["date"]

    # "%b %d" form, e.g. "Jan 01" -- should NOT parse as ISO date.
    with pytest.raises(ValueError):
        date.fromisoformat(sample_date)

    # Should match the strftime("%b %d") format of some date in the range.
    expected_values = {
        (end - timedelta(days=i)).strftime("%b %d")
        for i in range(DEFAULT_LOOKBACK_DAYS + 1)
    }
    assert sample_date in expected_values


# --------------------------------------------------------------------------- #
# 4. rounding + NaN drop
# --------------------------------------------------------------------------- #


def test_rounds_floats_and_drops_nan_row() -> None:
    end = date.today()
    df = _make_df(periods=5, end=end)
    # Add precision beyond 2dp.
    df["Open"] = [100.12345, 101.98765, 102.0, 103.0, 104.0]
    # Inject a NaN row.
    df.loc[df.index[2], "Close"] = np.nan

    with patch("tools.price_history.fetch_ohlcv", return_value=df):
        app = price_history("AAPL")

    rendered = _to_json(app)
    table = next(
        c
        for c in rendered["view"]["children"][0]["children"]
        if c["type"] == "DataTable"
    )
    rows = table["rows"]

    # NaN row dropped -> 4 rows remain.
    assert len(rows) == 4

    # Floats rounded to 2dp.
    for row in rows:
        assert row["open"] == round(row["open"], 2)


# --------------------------------------------------------------------------- #
# 5. invalid ticker
# --------------------------------------------------------------------------- #


def test_invalid_ticker_renders_error_app() -> None:
    with patch(
        "tools.price_history.fetch_ohlcv",
        side_effect=InvalidTickerError("'???' is not a valid ticker symbol format."),
    ):
        app = price_history("???")

    serialized = json.dumps(_to_json(app))
    assert "is not a valid ticker symbol format" in serialized
    assert '"variant": "destructive"' in serialized


# --------------------------------------------------------------------------- #
# 6. no data
# --------------------------------------------------------------------------- #


def test_no_data_renders_error_app() -> None:
    with patch(
        "tools.price_history.fetch_ohlcv",
        side_effect=TickerNotFoundError("No data found for ticker 'AAPL'."),
    ):
        app = price_history("AAPL")

    serialized = json.dumps(_to_json(app))
    assert "No data found for ticker 'AAPL'." in serialized
    assert '"variant": "destructive"' in serialized


# --------------------------------------------------------------------------- #
# 7. network error
# --------------------------------------------------------------------------- #


def test_network_error_renders_error_app() -> None:
    with patch(
        "tools.price_history.fetch_ohlcv",
        side_effect=NetworkError("A network error occurred while fetching data."),
    ):
        app = price_history("AAPL")

    serialized = json.dumps(_to_json(app))
    assert "A network error occurred while fetching data." in serialized
    assert '"variant": "destructive"' in serialized


# --------------------------------------------------------------------------- #
# 8. malformed date
# --------------------------------------------------------------------------- #


def test_malformed_date_renders_error_without_fetch() -> None:
    with patch("tools.price_history.fetch_ohlcv") as mock_fetch:
        app = price_history("AAPL", start="not-a-date")

    mock_fetch.assert_not_called()
    serialized = json.dumps(_to_json(app))
    assert "Invalid date" in serialized
    assert '"variant": "destructive"' in serialized


# --------------------------------------------------------------------------- #
# 9. default date range relative to today
# --------------------------------------------------------------------------- #


def test_default_date_range_is_relative_to_today() -> None:
    today = date.today()
    df = _make_df(periods=DEFAULT_LOOKBACK_DAYS + 1, end=today)

    with patch("tools.price_history.fetch_ohlcv", return_value=df) as mock_fetch:
        price_history("AAPL")

    mock_fetch.assert_called_once()
    _, kwargs = mock_fetch.call_args
    assert kwargs["end"] == today
    assert (kwargs["end"] - kwargs["start"]) == timedelta(days=DEFAULT_LOOKBACK_DAYS)


# --------------------------------------------------------------------------- #
# 10. single-row df
# --------------------------------------------------------------------------- #


def test_single_row_dataframe_has_zero_pct_change() -> None:
    today = date.today()
    df = _make_df(periods=1, end=today)

    with patch("tools.price_history.fetch_ohlcv", return_value=df):
        app = price_history("AAPL")

    rendered = _to_json(app)
    row_children = rendered["view"]["children"][0]["children"]
    metrics_row = next(c for c in row_children if c["type"] == "Row")
    change_metric = next(m for m in metrics_row["children"] if m["label"] == "Change")

    assert change_metric["value"] == "+0.00%"
    assert change_metric.get("trend") == "neutral"
