"""Unit tests for the utils module.

This module contains unit tests to verify historical data fetching, cleaning,
timezone stripping, limit handling, and parameter validation.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tools.utils import fetch_ticker_data


def test_fetch_ticker_data_success() -> None:
    """Test successful data fetching and cleaning.

    Verifies timezone stripping, index resetting, and standard column integrity.
    """
    dates = pd.to_datetime(["2026-05-01", "2026-05-02"])
    mock_df = pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [105.0, 106.0],
            "Low": [95.0, 96.0],
            "Close": [101.0, 102.0],
            "Volume": [1000.0, 1100.0],
        },
        index=pd.DatetimeIndex(dates, tz="UTC"),
    )

    mock_obj = MagicMock()
    mock_obj.history.return_value = mock_df

    with patch("yfinance.Ticker", return_value=mock_obj):
        # Happy path fetching without date overrides
        df = fetch_ticker_data("AAPL", period="2d", interval="1d")
        assert len(df) == 2
        assert list(df.columns) == [
            "Date",
            "Open",
            "High",
            "Low",
            "Close",
            "Volume",
        ]
        assert df.loc[0, "Date"].tzinfo is None
        assert df.loc[0, "Close"] == 101.0
        assert df.loc[1, "Close"] == 102.0

        # Happy path with start/end date overrides
        df_dates = fetch_ticker_data(
            "AAPL", start_date="2026-05-01", end_date="2026-05-02"
        )
        assert len(df_dates) == 2


def test_fetch_ticker_data_limit() -> None:
    """Test limits on the returned DataFrame size.

    Verifies that the returned rows are sliced from the end of the history DataFrame.
    """
    dates = pd.to_datetime(["2026-05-01", "2026-05-02", "2026-05-03"])
    mock_df = pd.DataFrame(
        {
            "Open": [100.0, 101.0, 102.0],
            "High": [105.0, 106.0, 107.0],
            "Low": [95.0, 96.0, 97.0],
            "Close": [101.0, 102.0, 103.0],
            "Volume": [1000.0, 1100.0, 1200.0],
        },
        index=pd.DatetimeIndex(dates, tz="UTC"),
    )

    mock_obj = MagicMock()
    mock_obj.history.return_value = mock_df

    with patch("yfinance.Ticker", return_value=mock_obj):
        # Request limit=2 (should get the last 2 rows: indices 1 and 2 of mock_df)
        df_limited = fetch_ticker_data("AAPL", limit=2)
        assert len(df_limited) == 2
        assert df_limited.loc[0, "Close"] == 102.0
        assert df_limited.loc[1, "Close"] == 103.0


def test_fetch_ticker_data_validation_errors() -> None:
    """Test fetch parameter validation errors.

    Verifies that invalid symbols and malformed start/end dates raise ValueError.
    """
    # Empty ticker symbol
    with pytest.raises(ValueError, match="Symbol must be a non-empty string."):
        fetch_ticker_data("")

    # Invalid start_date format
    with pytest.raises(ValueError, match="start_date must be in YYYY-MM-DD"):
        fetch_ticker_data("AAPL", start_date="2026/05/01")

    # Invalid end_date format
    with pytest.raises(ValueError, match="end_date must be in YYYY-MM-DD"):
        fetch_ticker_data("AAPL", end_date="2026/05/01")


def test_fetch_ticker_data_not_found() -> None:
    """Test fetch error handling when the ticker is not found/delisted.

    Verifies that returning an empty DataFrame from yfinance raises ValueError.
    """
    mock_obj = MagicMock()
    mock_obj.history.return_value = pd.DataFrame()

    with patch("yfinance.Ticker", return_value=mock_obj):
        with pytest.raises(ValueError, match="Ticker AAPL not found or delisted."):
            fetch_ticker_data("AAPL")
