"""Unit tests for the portfolio performance calculations.

This module contains unit tests to verify portfolio performance calculations,
input validation, edge cases, and error handling.
"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from tools.portfolio import calculate_portfolio_performance


def test_calculate_portfolio_performance_success() -> None:
    """Test successful calculation of portfolio performance with multiple tickers.

    Mocks fetch_ticker_data calls and verifies alignment, timezone stripping,
    invested amount, gained value, and yield calculations.
    """
    dates = pd.to_datetime(["2026-05-01", "2026-05-02"])

    # Define mock data without tz as fetch_ticker_data strips tzinfo
    aapl_clean = pd.DataFrame(
        {
            "Date": dates,
            "Open": [100.0, 105.0],
            "High": [105.0, 110.0],
            "Low": [95.0, 100.0],
            "Close": [100.0, 105.0],
            "Volume": [1000.0, 1100.0],
        }
    )
    msft_clean = pd.DataFrame(
        {
            "Date": dates,
            "Open": [200.0, 210.0],
            "High": [205.0, 215.0],
            "Low": [195.0, 205.0],
            "Close": [200.0, 210.0],
            "Volume": [2000.0, 2200.0],
        }
    )

    def mock_fetch(symbol: str, **kwargs: MagicMock) -> pd.DataFrame:
        if symbol == "AAPL":
            return aapl_clean.copy()
        elif symbol == "MSFT":
            return msft_clean.copy()
        else:
            raise ValueError(f"Ticker {symbol} not found or delisted.")

    with patch("tools.portfolio.fetch_ticker_data", side_effect=mock_fetch):
        result = calculate_portfolio_performance(
            tickers=["AAPL", "MSFT"],
            shares=[10.0, 5.0],
            buy_prices=[90.0, 180.0],
            start_date="2026-05-01",
            end_date="2026-05-02",
        )

    # 10*90 + 5*180 = 1800.0
    assert result.loc[0, "Invested"] == 1800.0
    assert result.loc[1, "Invested"] == 1800.0

    # 10*100 + 5*200 = 2000.0
    assert result.loc[0, "Value"] == 2000.0
    # 10*105 + 5*210 = 2100.0
    assert result.loc[1, "Value"] == 2100.0

    # Gained = Value - Invested
    assert result.loc[0, "Gained"] == 200.0
    assert result.loc[1, "Gained"] == 300.0

    # Yield = (Gained / Invested) * 100
    assert pytest.approx(result.loc[0, "Yield"]) == (200.0 / 1800.0) * 100
    assert pytest.approx(result.loc[1, "Yield"]) == (300.0 / 1800.0) * 100

    # Verify timezone stripped from index (Date column has no tz)
    assert result.loc[0, "Date"].tzinfo is None


def test_calculate_portfolio_performance_validation_errors() -> None:
    """Test validation errors for invalid inputs.

    Verifies empty tickers list, mismatched lists lengths, negative shares,
    negative purchase prices, invalid symbols, and bad date formats raise ValueError.
    """
    # Empty tickers
    with pytest.raises(ValueError, match="Tickers list cannot be empty."):
        calculate_portfolio_performance(
            tickers=[], shares=[], buy_prices=[], start_date="2026-05-01"
        )

    # Length mismatch
    with pytest.raises(
        ValueError, match="Lengths of tickers, shares, and buy_prices must match."
    ):
        calculate_portfolio_performance(
            tickers=["AAPL"],
            shares=[10.0, 5.0],
            buy_prices=[90.0],
            start_date="2026-05-01",
        )

    # Negative shares
    with pytest.raises(ValueError, match="Shares must be positive numbers."):
        calculate_portfolio_performance(
            tickers=["AAPL"],
            shares=[-10.0],
            buy_prices=[90.0],
            start_date="2026-05-01",
        )

    # Negative buy price
    with pytest.raises(ValueError, match="Buy prices must be positive numbers."):
        calculate_portfolio_performance(
            tickers=["AAPL"],
            shares=[10.0],
            buy_prices=[-90.0],
            start_date="2026-05-01",
        )

    # Invalid ticker format
    with pytest.raises(ValueError, match="Ticker symbols must be non-empty strings."):
        calculate_portfolio_performance(
            tickers=[""],
            shares=[10.0],
            buy_prices=[90.0],
            start_date="2026-05-01",
        )

    # Invalid start date format
    with pytest.raises(ValueError, match="start_date must be in YYYY-MM-DD format"):
        calculate_portfolio_performance(
            tickers=["AAPL"],
            shares=[10.0],
            buy_prices=[90.0],
            start_date="2026/05/01",
        )

    # Invalid end date format
    with pytest.raises(ValueError, match="end_date must be in YYYY-MM-DD format"):
        calculate_portfolio_performance(
            tickers=["AAPL"],
            shares=[10.0],
            buy_prices=[90.0],
            start_date="2026-05-01",
            end_date="2026/05/02",
        )
