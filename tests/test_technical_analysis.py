"""Unit tests for the technical analysis module.

This module contains unit tests to verify historical data fetching,
technical analysis indicators (SMA, EMA, RSI, BB, OBV), input validation,
error handling, and numpy conversion helpers.
"""

from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from tools.technical_analysis import (
    analyze_tickers_ta,
    convert_to_numpy,
    run_technical_analysis,
)


def _create_mock_df(num_rows: int = 40) -> pd.DataFrame:
    """Helper to create a standard mock price DataFrame.

    Args:
        num_rows: Number of rows in the DataFrame. Defaults to 40.

    Returns:
        A Pandas DataFrame with DatetimeIndex and standard financial columns.
    """
    dates = pd.date_range(start="2026-05-01", periods=num_rows, freq="D")
    return pd.DataFrame(
        {
            "Open": np.linspace(100.0, 100.0 + num_rows, num_rows),
            "High": np.linspace(105.0, 105.0 + num_rows, num_rows),
            "Low": np.linspace(95.0, 95.0 + num_rows, num_rows),
            "Close": np.linspace(101.0, 101.0 + num_rows, num_rows),
            "Volume": np.linspace(1000.0, 1000.0 + 100 * num_rows, num_rows),
        },
        index=pd.DatetimeIndex(dates),
    )


def test_run_technical_analysis_default_suite() -> None:
    """Test technical analysis runs the full default suite.

    Verifies all default indicators (SMA_20, EMA_20, RSI_14, BB_High, BB_Low, BB_Mid, OBV)
    are calculated and added as columns, and NaN rows are dropped.
    """
    df = _create_mock_df(40)
    df = df.reset_index().rename(columns={"index": "Date"})

    result = run_technical_analysis(df)

    expected_cols = [
        "Date",
        "Open",
        "High",
        "Low",
        "Close",
        "Volume",
        "SMA_20",
        "EMA_20",
        "RSI_14",
        "BB_High",
        "BB_Low",
        "BB_Mid",
        "OBV",
    ]
    for col in expected_cols:
        assert col in result.columns

    # Verify no NaN values remain
    assert not result.isna().any().any()
    # For window=20, first 19 values of SMA/BB are NaN, so length should be 40 - 19 = 21
    assert len(result) == 21


def test_run_technical_analysis_custom_indicators() -> None:
    """Test running a custom subset of indicators.

    Verifies only requested indicators are calculated and added.
    """
    df = _create_mock_df(40)
    df = df.reset_index().rename(columns={"index": "Date"})

    result = run_technical_analysis(df, indicators=["rsi", "sma"])

    assert "RSI_14" in result.columns
    assert "SMA_20" in result.columns
    assert "EMA_20" not in result.columns
    assert "BB_High" not in result.columns
    assert "OBV" not in result.columns


def test_run_technical_analysis_validation_errors() -> None:
    """Test validation errors for run_technical_analysis.

    Verifies insufficient rows, missing required columns, and invalid indicators.
    """
    # Fewer than 30 rows
    short_df = _create_mock_df(29)
    short_df = short_df.reset_index().rename(columns={"index": "Date"})
    with pytest.raises(
        ValueError, match="Not enough data for reliable TA. Need at least 30 rows."
    ):
        run_technical_analysis(short_df)

    # Missing Close column
    df = _create_mock_df(40)
    df = df.reset_index().rename(columns={"index": "Date"})
    df_no_close = df.drop(columns=["Close"])
    with pytest.raises(ValueError, match="DataFrame must contain 'Close'"):
        run_technical_analysis(df_no_close)

    # Missing Volume column for OBV
    df = _create_mock_df(40)
    df = df.reset_index().rename(columns={"index": "Date"})
    df_no_vol = df.drop(columns=["Volume"])
    with pytest.raises(
        ValueError, match="must contain 'Volume' column to calculate OBV"
    ):
        run_technical_analysis(df_no_vol, indicators=["obv"])

    # Invalid indicator name
    df = _create_mock_df(40)
    df = df.reset_index().rename(columns={"index": "Date"})
    with pytest.raises(ValueError, match="Invalid indicator 'invalid_ind'"):
        run_technical_analysis(df, indicators=["invalid_ind"])


def test_analyze_tickers_ta_success() -> None:
    """Test running TA on multiple tickers.

    Verifies correct dictionary mapping and enriched DataFrame structure.
    """
    mock_df = _create_mock_df(40)
    mock_df = mock_df.reset_index().rename(columns={"index": "Date"})

    with patch(
        "tools.technical_analysis.fetch_ticker_data", return_value=mock_df
    ) as mock_fetch:
        results = analyze_tickers_ta(
            tickers=["AAPL", "MSFT"],
            start_date="2026-05-01",
            end_date="2026-06-10",
        )
        assert mock_fetch.call_count == 2

    assert list(results.keys()) == ["AAPL", "MSFT"]
    assert "SMA_20" in results["AAPL"].columns
    assert "SMA_20" in results["MSFT"].columns


def test_analyze_tickers_ta_empty_tickers() -> None:
    """Test validation when tickers list is empty."""
    with pytest.raises(ValueError, match="Tickers list cannot be empty."):
        analyze_tickers_ta(tickers=[])

    with pytest.raises(ValueError, match="Ticker symbols must be non-empty"):
        analyze_tickers_ta(tickers=["AAPL", ""])


def test_convert_to_numpy() -> None:
    """Test converting a DataFrame to a dictionary of numpy arrays."""
    df = pd.DataFrame({"A": [1, 2, 3], "B": [4.0, 5.0, 6.0]})
    np_dict = convert_to_numpy(df)

    assert list(np_dict.keys()) == ["A", "B"]
    assert isinstance(np_dict["A"], np.ndarray)
    assert isinstance(np_dict["B"], np.ndarray)
    np.testing.assert_array_equal(np_dict["A"], np.array([1, 2, 3]))
    np.testing.assert_array_equal(np_dict["B"], np.array([4.0, 5.0, 6.0]))
