"""Portfolio performance calculations and tools.

This module provides functions to calculate historical performance of a stock
portfolio, including total invested amount, current/historical value, gained value,
and yield percentage over time.
"""

from datetime import datetime

import pandas as pd

from tools.utils import fetch_ticker_data


def calculate_portfolio_performance(
    tickers: list[str],
    shares: list[float],
    buy_prices: list[float],
    start_date: str,
    end_date: str | None = None,
) -> pd.DataFrame:
    """Calculate the historical performance of a stock portfolio.

    Fetches historical data for each ticker, aligns them by date, and calculates
    daily invested amount, portfolio value, gains, and yield percentage.

    Args:
        tickers: List of stock ticker symbols.
        shares: List of shares owned for each ticker.
        buy_prices: List of purchase prices per share for each ticker.
        start_date: The start date for performance tracking (YYYY-MM-DD).
        end_date: The end date for performance tracking (YYYY-MM-DD). Defaults to None.

    Returns:
        A DataFrame with columns: Date, Invested, Value, Gained, Yield.

    Raises:
        ValueError: If inputs are invalid, tickers mismatch lists, or a ticker is not found/delisted.
    """
    # 1. Validate inputs
    if not tickers:
        raise ValueError("Tickers list cannot be empty.")
    if len(tickers) != len(shares) or len(tickers) != len(buy_prices):
        raise ValueError("Lengths of tickers, shares, and buy_prices must match.")

    for s, p in zip(shares, buy_prices):
        if s <= 0:
            raise ValueError("Shares must be positive numbers.")
        if p <= 0:
            raise ValueError("Buy prices must be positive numbers.")

    for ticker in tickers:
        if not ticker or not isinstance(ticker, str):
            raise ValueError("Ticker symbols must be non-empty strings.")

    # Validate start_date format
    try:
        datetime.strptime(start_date, "%Y-%m-%d")
    except ValueError as e:
        raise ValueError(f"start_date must be in YYYY-MM-DD format: {e}")

    if end_date:
        try:
            datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError as e:
            raise ValueError(f"end_date must be in YYYY-MM-DD format: {e}")

    # Calculate constant total invested amount
    total_invested = sum(s * p for s, p in zip(shares, buy_prices))

    # 2. Fetch historical price data for each ticker
    aligned_prices = pd.DataFrame()

    for ticker, qty in zip(tickers, shares):
        # Fetch historical data using our shared fetch_ticker_data helper
        hist = fetch_ticker_data(
            symbol=ticker,
            interval="1d",
            start_date=start_date,
            end_date=end_date,
        )

        hist_indexed = hist.set_index("Date")
        close_series = hist_indexed["Close"]
        # Convert close price to value contribution (shares * price)
        contrib_series = close_series * qty
        contrib_df = contrib_series.to_frame(name=ticker)

        if aligned_prices.empty:
            aligned_prices = contrib_df
        else:
            # Outer join to align all dates
            aligned_prices = aligned_prices.join(contrib_df, how="outer")

    # Forward fill to handle any gaps, then backward fill for any late starters
    aligned_prices = aligned_prices.ffill().bfill()

    # Calculate total portfolio value at each date
    portfolio_value = aligned_prices.sum(axis=1)

    # Build output DataFrame
    perf_df = pd.DataFrame(index=portfolio_value.index)
    perf_df["Invested"] = total_invested
    perf_df["Value"] = portfolio_value
    perf_df["Gained"] = perf_df["Value"] - perf_df["Invested"]
    perf_df["Yield"] = (perf_df["Gained"] / perf_df["Invested"]) * 100

    # Reset index and rename to Date
    perf_df = perf_df.reset_index()
    perf_df.rename(columns={perf_df.columns[0]: "Date"}, inplace=True)

    return perf_df
