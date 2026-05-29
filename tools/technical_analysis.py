"""Technical analysis tools and features.

This module provides functions to fetch historical stock ticker data and run
standard technical analysis indicators (SMA, EMA, RSI, Bollinger Bands, OBV)
using the third-party 'ta' library.
"""

import numpy as np
import pandas as pd
import ta

from tools.utils import fetch_ticker_data


def run_technical_analysis(
    df: pd.DataFrame, indicators: list[str] | None = None
) -> pd.DataFrame:
    """Run technical analysis indicators on stock ticker data.

    Calculates trend, momentum, volatility, and volume indicators
    and adds them as columns to the provided DataFrame.

    Args:
        df: Pandas DataFrame containing stock data with 'Close' and 'Volume' columns.
            Must have at least 30 rows.
        indicators: List of indicators to calculate. Options: 'sma', 'ema', 'rsi', 'bb', 'obv'.
            If None or empty, all indicators will be calculated.

    Returns:
        A DataFrame with the calculated indicators added as columns, and NaN rows dropped.

    Raises:
        ValueError: If df has fewer than 30 rows, missing required columns, or invalid indicator specified.
    """
    if len(df) < 30:
        raise ValueError("Not enough data for reliable TA. Need at least 30 rows.")

    if "Close" not in df.columns:
        raise ValueError("DataFrame must contain 'Close' column.")

    df = df.copy()

    # Determine which indicators to calculate
    valid_indicators = {"sma", "ema", "rsi", "bb", "obv"}
    if indicators is None or len(indicators) == 0:
        indicators_to_run = list(valid_indicators)
    else:
        # Validate requested indicators
        for ind in indicators:
            if ind.lower() not in valid_indicators:
                raise ValueError(
                    f"Invalid indicator '{ind}'. Valid options: {list(valid_indicators)}"
                )
        indicators_to_run = [ind.lower() for ind in indicators]

    close_series = df["Close"]

    # 1. Trend: SMA 20, EMA 20
    if "sma" in indicators_to_run:
        df["SMA_20"] = ta.trend.sma_indicator(close_series, window=20)
    if "ema" in indicators_to_run:
        df["EMA_20"] = ta.trend.ema_indicator(close_series, window=20)

    # 2. Momentum: RSI 14
    if "rsi" in indicators_to_run:
        df["RSI_14"] = ta.momentum.rsi(close_series, window=14)

    # 3. Volatility: Bollinger Bands (20, 2)
    if "bb" in indicators_to_run:
        bb = ta.volatility.BollingerBands(close_series, window=20, window_dev=2)
        df["BB_High"] = bb.bollinger_hband()
        df["BB_Low"] = bb.bollinger_lband()
        df["BB_Mid"] = bb.bollinger_mavg()

    # 4. Volume: OBV
    if "obv" in indicators_to_run:
        if "Volume" not in df.columns:
            raise ValueError("DataFrame must contain 'Volume' column to calculate OBV.")
        df["OBV"] = ta.volume.on_balance_volume(close_series, df["Volume"])

    # Drop rows with NaN values AFTER adding all indicators
    df.dropna(inplace=True)

    return df


def analyze_tickers_ta(
    tickers: list[str],
    start_date: str | None = None,
    end_date: str | None = None,
    period: str = "3mo",
    interval: str = "1d",
    indicators: list[str] | None = None,
) -> dict[str, pd.DataFrame]:
    """Run technical analysis on one or multiple stock tickers.

    Args:
        tickers: List of stock ticker symbols.
        start_date: Start date string (YYYY-MM-DD).
        end_date: End date string (YYYY-MM-DD).
        period: Data period if start/end are not set. Defaults to '3mo'.
        interval: Data interval. Defaults to '1d'.
        indicators: List of indicators to calculate. Defaults to None.

    Returns:
        A dictionary mapping ticker symbol to the enriched DataFrame containing TA indicators.

    Raises:
        ValueError: If input lists/parameters are invalid or a ticker lacks enough data.
    """
    if not tickers:
        raise ValueError("Tickers list cannot be empty.")

    # Validate inputs
    for symbol in tickers:
        if not symbol or not isinstance(symbol, str):
            raise ValueError("Ticker symbols must be non-empty strings.")

    # Fetch data and run TA for each ticker
    results = {}
    for symbol in tickers:
        df = fetch_ticker_data(
            symbol=symbol,
            interval=interval,
            period=period,
            start_date=start_date,
            end_date=end_date,
        )
        enriched_df = run_technical_analysis(df, indicators=indicators)
        results[symbol] = enriched_df

    return results


def convert_to_numpy(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """Convert a DataFrame to a dictionary of NumPy arrays.

    Args:
        df: Pandas DataFrame.

    Returns:
        A dictionary mapping column name to NumPy array.
    """
    return {str(col): df[col].to_numpy() for col in df.columns}
