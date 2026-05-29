"""Utility functions for StockMCPService.

This module provides common utility functions, such as fetching historical
stock ticker data from Yahoo Finance and cleaning the returned DataFrames.
"""

from datetime import datetime

import pandas as pd
import yfinance as yf


def fetch_ticker_data(
    symbol: str,
    interval: str = "1d",
    period: str = "3mo",
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int | None = None,
) -> pd.DataFrame:
    """Fetch historical stock price data for a ticker symbol.

    Args:
        symbol: The stock ticker symbol.
        interval: Data interval (e.g., '1d', '1wk', '1mo'). Defaults to '1d'.
        period: Data period (e.g., '3mo', '1y'). Defaults to '3mo'.
        start_date: Start date string (YYYY-MM-DD). If provided, overrides period.
        end_date: End date string (YYYY-MM-DD). If provided, overrides period.
        limit: Number of rows to return from the end. Defaults to None.

    Returns:
        A cleaned Pandas DataFrame with columns: Date, Open, High, Low, Close, Volume.

    Raises:
        ValueError: If ticker is not found/delisted or empty.
    """
    if not symbol or not isinstance(symbol, str):
        raise ValueError("Symbol must be a non-empty string.")

    ticker_obj = yf.Ticker(symbol)

    # Validate start_date / end_date formats
    if start_date:
        try:
            datetime.strptime(start_date, "%Y-%m-%d")
        except ValueError as e:
            raise ValueError(f"start_date must be in YYYY-MM-DD format: {e}")
    if end_date:
        try:
            datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError as e:
            raise ValueError(f"end_date must be in YYYY-MM-DD format: {e}")

    # If start/end date are provided, we use start/end. Else we use period.
    if start_date or end_date:
        hist = ticker_obj.history(
            start=start_date, end=end_date, period=None, interval=interval
        )
    else:
        hist = ticker_obj.history(period=period, interval=interval)

    if hist.empty:
        raise ValueError(f"Ticker {symbol} not found or delisted.")

    # Strip timezone info from index
    if hist.index.tz is not None:
        hist.index = hist.index.tz_localize(None)

    # Reset index so Date is a column
    hist = hist.reset_index()
    hist.rename(columns={hist.columns[0]: "Date"}, inplace=True)

    # Keep only standard columns: Date, Open, High, Low, Close, Volume
    required_cols = ["Date", "Open", "High", "Low", "Close", "Volume"]
    for col in required_cols:
        if col not in hist.columns:
            hist[col] = 0.0

    df_cleaned = hist[required_cols]

    if limit is not None:
        df_cleaned = df_cleaned.tail(limit).reset_index(drop=True)

    return df_cleaned
