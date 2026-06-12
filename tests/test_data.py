"""Unit tests for `tools._data`.

All yfinance access is mocked via `unittest.mock.patch` on
`tools._data.yf.Ticker`. No network calls are made.
"""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import requests
from yfinance.exceptions import YFPricesMissingError, YFRateLimitError

from tools._data import (
    OHLCV_COLUMNS,
    DataValidationError,
    InvalidDateRangeError,
    InvalidPeriodError,
    InvalidTickerError,
    NetworkError,
    TickerNotFoundError,
    fetch_ohlcv,
    validate_date_range,
    validate_period,
    validate_ticker,
)

# --------------------------------------------------------------------------- #
# validate_ticker
# --------------------------------------------------------------------------- #


def test_validate_ticker_lowercase_is_normalized() -> None:
    assert validate_ticker("aapl") == "AAPL"


def test_validate_ticker_with_dot_is_preserved() -> None:
    assert validate_ticker("brk.b") == "BRK.B"


def test_validate_ticker_strips_whitespace() -> None:
    assert validate_ticker("  msft  ") == "MSFT"


def test_validate_ticker_empty_raises() -> None:
    with pytest.raises(InvalidTickerError):
        validate_ticker("")


def test_validate_ticker_whitespace_only_raises() -> None:
    with pytest.raises(InvalidTickerError):
        validate_ticker("   ")


def test_validate_ticker_too_long_raises() -> None:
    with pytest.raises(InvalidTickerError):
        validate_ticker("ABCDEFGHIJK")


def test_validate_ticker_invalid_chars_raises() -> None:
    with pytest.raises(InvalidTickerError):
        validate_ticker("AAP$L")


def test_validate_ticker_internal_space_raises() -> None:
    with pytest.raises(InvalidTickerError):
        validate_ticker("AA PL")


def test_validate_ticker_leading_dot_raises() -> None:
    with pytest.raises(InvalidTickerError):
        validate_ticker(".AAPL")


# --------------------------------------------------------------------------- #
# validate_date_range
# --------------------------------------------------------------------------- #


def test_validate_date_range_valid_strings() -> None:
    today = date.today()
    start = (today - timedelta(days=10)).isoformat()
    end = (today - timedelta(days=1)).isoformat()

    result = validate_date_range(start, end)

    assert result == (date.fromisoformat(start), date.fromisoformat(end))


def test_validate_date_range_start_after_end_raises() -> None:
    today = date.today()
    start = (today - timedelta(days=1)).isoformat()
    end = (today - timedelta(days=10)).isoformat()

    with pytest.raises(InvalidDateRangeError):
        validate_date_range(start, end)


def test_validate_date_range_start_equal_end_raises() -> None:
    today = date.today()
    same_day = (today - timedelta(days=5)).isoformat()

    with pytest.raises(InvalidDateRangeError):
        validate_date_range(same_day, same_day)


def test_validate_date_range_future_end_raises() -> None:
    today = date.today()
    start = (today - timedelta(days=5)).isoformat()
    tomorrow = (today + timedelta(days=1)).isoformat()

    with pytest.raises(InvalidDateRangeError):
        validate_date_range(start, tomorrow)


def test_validate_date_range_bad_format_raises() -> None:
    with pytest.raises(InvalidDateRangeError):
        validate_date_range("2024/01/01", "2024/02/01")


# --------------------------------------------------------------------------- #
# validate_period
# --------------------------------------------------------------------------- #


def test_validate_period_valid() -> None:
    assert validate_period("1mo", "1d") == ("1mo", "1d")


def test_validate_period_invalid_period_raises() -> None:
    with pytest.raises(InvalidPeriodError):
        validate_period("2wk", "1d")


def test_validate_period_invalid_interval_raises() -> None:
    with pytest.raises(InvalidPeriodError):
        validate_period("1mo", "3d")


def test_validate_period_case_insensitive() -> None:
    assert validate_period("1MO", "1D") == ("1mo", "1d")


# --------------------------------------------------------------------------- #
# fetch_ohlcv
# --------------------------------------------------------------------------- #


def _make_mock_history_df() -> pd.DataFrame:
    """Build a mixed-case mock yfinance history DataFrame."""
    index = pd.date_range(end=date.today() - timedelta(days=1), periods=3, freq="D")
    return pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0],
            "High": [105.0, 106.0, 107.0],
            "Low": [99.0, 100.0, 101.0],
            "Close": [104.0, 105.0, 106.0],
            "Volume": [1_000, 1_100, 1_200],
            "Dividends": [0.0, 0.0, 0.0],
            "Stock Splits": [0.0, 0.0, 0.0],
        },
        index=index,
    )


@patch("tools._data.yf.Ticker")
def test_fetch_ohlcv_valid_period_returns_expected_columns(
    mock_ticker_cls: MagicMock,
) -> None:
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = _make_mock_history_df()
    mock_ticker_cls.return_value = mock_ticker

    df = fetch_ohlcv("AAPL", period="1mo", interval="1d")

    assert list(df.columns) == list(OHLCV_COLUMNS)
    assert len(df) == 3
    assert isinstance(df.index, pd.DatetimeIndex)


@patch("tools._data.yf.Ticker")
def test_fetch_ohlcv_invalid_ticker_does_not_call_yfinance(
    mock_ticker_cls: MagicMock,
) -> None:
    with pytest.raises(InvalidTickerError):
        fetch_ohlcv("AAP$L", period="1mo")

    mock_ticker_cls.assert_not_called()


@patch("tools._data.yf.Ticker")
def test_fetch_ohlcv_empty_dataframe_raises_ticker_not_found(
    mock_ticker_cls: MagicMock,
) -> None:
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()
    mock_ticker_cls.return_value = mock_ticker

    with pytest.raises(TickerNotFoundError) as exc_info:
        fetch_ohlcv("AAPL", period="1mo")

    assert "AAPL" in exc_info.value.user_message


@patch("tools._data.yf.Ticker")
def test_fetch_ohlcv_partial_columns_raises_ticker_not_found(
    mock_ticker_cls: MagicMock,
) -> None:
    index = pd.date_range(end=date.today() - timedelta(days=1), periods=3, freq="D")
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0],
            "Close": [104.0, 105.0, 106.0],
        },
        index=index,
    )
    mock_ticker_cls.return_value = mock_ticker

    with pytest.raises(TickerNotFoundError) as exc_info:
        fetch_ohlcv("AAPL", period="1mo")

    assert "AAPL" in exc_info.value.user_message


@patch("tools._data.yf.Ticker")
def test_fetch_ohlcv_missing_data_exception_raises_ticker_not_found(
    mock_ticker_cls: MagicMock,
) -> None:
    mock_ticker = MagicMock()
    mock_ticker.history.side_effect = YFPricesMissingError("AAPL", "")
    mock_ticker_cls.return_value = mock_ticker

    with pytest.raises(TickerNotFoundError):
        fetch_ohlcv("AAPL", period="1mo")


@patch("tools._data.yf.Ticker")
def test_fetch_ohlcv_connection_error_raises_network_error(
    mock_ticker_cls: MagicMock,
) -> None:
    mock_ticker = MagicMock()
    mock_ticker.history.side_effect = requests.exceptions.ConnectTimeout("timed out")
    mock_ticker_cls.return_value = mock_ticker

    with pytest.raises(NetworkError):
        fetch_ohlcv("AAPL", period="1mo")


@patch("tools._data.yf.Ticker")
def test_fetch_ohlcv_connection_error_generic_raises_network_error(
    mock_ticker_cls: MagicMock,
) -> None:
    mock_ticker = MagicMock()
    mock_ticker.history.side_effect = requests.exceptions.ConnectionError(
        "connection refused"
    )
    mock_ticker_cls.return_value = mock_ticker

    with pytest.raises(NetworkError):
        fetch_ohlcv("AAPL", period="1mo")


@patch("tools._data.yf.Ticker")
def test_fetch_ohlcv_rate_limit_raises_network_error(
    mock_ticker_cls: MagicMock,
) -> None:
    mock_ticker = MagicMock()
    mock_ticker.history.side_effect = YFRateLimitError()
    mock_ticker_cls.return_value = mock_ticker

    with pytest.raises(NetworkError):
        fetch_ohlcv("AAPL", period="1mo")


def test_fetch_ohlcv_requires_period_xor_date_range_neither() -> None:
    with pytest.raises(DataValidationError):
        fetch_ohlcv("AAPL")


def test_fetch_ohlcv_requires_period_xor_date_range_both() -> None:
    today = date.today()
    start = (today - timedelta(days=10)).isoformat()
    end = (today - timedelta(days=1)).isoformat()

    with pytest.raises(DataValidationError):
        fetch_ohlcv("AAPL", start=start, end=end, period="1mo")


def test_fetch_ohlcv_only_start_given_raises() -> None:
    today = date.today()
    start = (today - timedelta(days=10)).isoformat()

    with pytest.raises(DataValidationError):
        fetch_ohlcv("AAPL", start=start)


def test_fetch_ohlcv_only_end_given_raises() -> None:
    today = date.today()
    end = (today - timedelta(days=1)).isoformat()

    with pytest.raises(DataValidationError):
        fetch_ohlcv("AAPL", end=end)


@patch("tools._data.yf.Ticker")
def test_fetch_ohlcv_period_path_calls_history_with_period(
    mock_ticker_cls: MagicMock,
) -> None:
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = _make_mock_history_df()
    mock_ticker_cls.return_value = mock_ticker

    fetch_ohlcv("AAPL", period="1mo", interval="1d", timeout=5.0)

    mock_ticker.history.assert_called_once()
    _, kwargs = mock_ticker.history.call_args

    assert kwargs["period"] == "1mo"
    assert kwargs["interval"] == "1d"
    assert kwargs["timeout"] == 5.0
    assert "start" not in kwargs
    assert "end" not in kwargs


@patch("tools._data.yf.Ticker")
def test_fetch_ohlcv_date_range_path_calls_history_with_start_end(
    mock_ticker_cls: MagicMock,
) -> None:
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = _make_mock_history_df()
    mock_ticker_cls.return_value = mock_ticker

    today = date.today()
    start = (today - timedelta(days=10)).isoformat()
    end = (today - timedelta(days=1)).isoformat()

    fetch_ohlcv("AAPL", start=start, end=end, interval="1d")

    mock_ticker.history.assert_called_once()
    _, kwargs = mock_ticker.history.call_args

    assert kwargs["start"] == date.fromisoformat(start)
    assert kwargs["end"] == date.fromisoformat(end)
    assert kwargs["interval"] == "1d"
    assert "period" not in kwargs
