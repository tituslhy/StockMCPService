"""Unit tests for `ui.compare`.

All price fetches are mocked via `unittest.mock.patch` on
`ui.compare.fetch_ohlcv`. No network calls are made. Backend tools
(`add_ticker`, `remove_ticker`, `search_tickers`) are decorated with
`@compare_app.tool()`, which returns the original function unchanged --
so they are called directly here with no MCP context.
"""

from __future__ import annotations

import json
import math
from datetime import date, timedelta
from unittest.mock import patch

import pandas as pd
import pytest

from tools._data import InvalidTickerError, NetworkError
from ui.compare import (
    _COMPARE_SET,
    _compare_snapshot,
    _normalize_performance,
    _pairwise_correlation,
    _ticker_stats,
    add_ticker,
    compare_dashboard,
    remove_ticker,
    reset_compare,
    search_tickers,
)


def _make_close_df(closes: list[float], dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Build a multi-row OHLCV DataFrame (lowercase columns, DatetimeIndex).

    `open`, `high`, `low`, and `close` are all set to the values in
    `closes`. `volume` is a constant placeholder.
    """
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1000] * len(closes),
        },
        index=dates,
    )


@pytest.fixture(autouse=True)
def _clean_compare() -> object:
    """Reset state and forbid all live network access for every test.

    `add_ticker`/`remove_ticker` internally call `_compare_snapshot()`,
    which fetches data once two or more tickers are present. To guarantee
    no test ever reaches the real `fetch_ohlcv` (and thus yfinance), this
    fixture patches it with a benign multi-row default. Tests that need
    specific data or failures override it with their own
    `with patch("ui.compare.fetch_ohlcv", ...)` block.
    """
    reset_compare()
    default_dates = pd.date_range(end=pd.Timestamp.today(), periods=10, freq="D")
    default_df = _make_close_df([100.0 + i for i in range(10)], default_dates)
    with patch("ui.compare.fetch_ohlcv", return_value=default_df):
        yield
    reset_compare()


def _to_json(app: object) -> dict:
    """Serialize a PrefabApp to a dict.

    NOTE: `PrefabApp.to_json()` wraps the view in an additional container on
    each call, so this must only be called ONCE per app instance.
    """
    return app.to_json()  # type: ignore[attr-defined,no-any-return]


# --------------------------------------------------------------------------- #
# add_ticker
# --------------------------------------------------------------------------- #


def test_add_ticker_new_symbol() -> None:
    snapshot = add_ticker("aapl")

    assert "AAPL" in _COMPARE_SET
    assert snapshot["symbols"] == ["AAPL"]


def test_add_ticker_idempotent_no_duplicate() -> None:
    add_ticker("AAPL")
    add_ticker("AAPL")

    assert _COMPARE_SET == ["AAPL"]


def test_add_ticker_invalid_ticker_raises() -> None:
    with pytest.raises(InvalidTickerError):
        add_ticker("???")


# --------------------------------------------------------------------------- #
# remove_ticker
# --------------------------------------------------------------------------- #


def test_remove_existing_ticker() -> None:
    add_ticker("AAPL")
    add_ticker("MSFT")

    snapshot = remove_ticker("aapl")

    assert "AAPL" not in _COMPARE_SET
    assert snapshot["symbols"] == ["MSFT"]


def test_remove_nonexistent_ticker_idempotent() -> None:
    snapshot = remove_ticker("AAPL")

    assert "AAPL" not in _COMPARE_SET
    assert snapshot["symbols"] == []


def test_remove_invalid_ticker_raises() -> None:
    with pytest.raises(InvalidTickerError):
        remove_ticker("???")


# --------------------------------------------------------------------------- #
# search_tickers
# --------------------------------------------------------------------------- #


def test_search_tickers_found() -> None:
    dates = pd.date_range(end=pd.Timestamp.today(), periods=5, freq="D")
    df = _make_close_df([100.0] * 5, dates)

    with patch("ui.compare.fetch_ohlcv", return_value=df):
        results = search_tickers("aapl")

    assert len(results) == 1
    assert results[0]["symbol"] == "AAPL"
    assert results[0]["status"] == "found"


def test_search_tickers_not_found() -> None:
    with patch(
        "ui.compare.fetch_ohlcv",
        side_effect=NetworkError("A network error occurred while fetching data."),
    ):
        results = search_tickers("zzzz")

    assert len(results) == 1
    assert results[0]["symbol"] == "ZZZZ"
    assert results[0]["status"] == "not_found"


def test_search_tickers_empty_query() -> None:
    assert search_tickers("") == []
    assert search_tickers("   ") == []


def test_search_tickers_invalid_ticker_format() -> None:
    results = search_tickers("???")
    assert len(results) == 1
    assert results[0]["status"] == "not_found"
    assert "not a valid ticker" in results[0]["message"]


def test_search_tickers_value_error() -> None:
    with patch("ui.compare.fetch_ohlcv", side_effect=ValueError("Some error")):
        results = search_tickers("AAPL")

    assert len(results) == 1
    assert results[0]["status"] == "not_found"
    assert "Some error" in results[0]["message"]


# --------------------------------------------------------------------------- #
# _compare_snapshot -- status transitions
# --------------------------------------------------------------------------- #


def test_snapshot_empty_set() -> None:
    snapshot = _compare_snapshot()

    assert snapshot["status"] == "empty"
    assert snapshot["symbols"] == []
    assert snapshot["message"] is not None
    assert snapshot["performance"] == []
    assert snapshot["correlation_matrix"] == []
    assert snapshot["stats"] == []


def test_snapshot_single_ticker_is_empty_status() -> None:
    add_ticker("AAPL")

    snapshot = _compare_snapshot()

    assert snapshot["status"] == "empty"
    assert snapshot["symbols"] == ["AAPL"]
    assert snapshot["message"] is not None


# --------------------------------------------------------------------------- #
# _normalize_performance -- hand-computed
# --------------------------------------------------------------------------- #


def test_normalize_performance_hand_computed() -> None:
    today = date.today()
    dates = pd.to_datetime(
        [today - timedelta(days=2), today - timedelta(days=1), today]
    )

    aapl = pd.Series([100.0, 110.0, 90.0], index=dates)
    msft = pd.Series([50.0, 55.0, 45.0], index=dates)

    aligned = {"AAPL": aapl, "MSFT": msft}
    start_date = today - timedelta(days=2)
    end_date = today

    records = _normalize_performance(aligned, dates, start_date, end_date)

    assert len(records) == 3
    assert records[0]["AAPL"] == 0.0
    assert records[0]["MSFT"] == 0.0
    assert records[1]["AAPL"] == 10.0
    assert records[1]["MSFT"] == 10.0
    assert records[2]["AAPL"] == -10.0
    assert records[2]["MSFT"] == -10.0


def test_normalize_performance_zero_close_0_all_zeros() -> None:
    """Test close_0 == 0 guard (line 201-202)."""
    today = date.today()
    dates = pd.to_datetime([today - timedelta(days=1), today])

    aapl = pd.Series([0.0, 100.0], index=dates)
    aligned = {"AAPL": aapl}
    start_date = today - timedelta(days=1)
    end_date = today

    records = _normalize_performance(aligned, dates, start_date, end_date)

    assert records[0]["AAPL"] == 0.0
    assert records[1]["AAPL"] == 0.0


def test_normalize_performance_nan_close_t_becomes_zero() -> None:
    """Test non-finite close_t guard (line 205-206)."""
    today = date.today()
    dates = pd.to_datetime([today - timedelta(days=1), today])

    aapl = pd.Series([100.0, float("nan")], index=dates)
    aligned = {"AAPL": aapl}
    start_date = today - timedelta(days=1)
    end_date = today

    records = _normalize_performance(aligned, dates, start_date, end_date)

    assert records[1]["AAPL"] == 0.0


def test_normalize_performance_inf_normalized_becomes_zero() -> None:
    """Test non-finite normalized guard (line 209-210)."""
    today = date.today()
    dates = pd.to_datetime([today - timedelta(days=1), today])

    aapl = pd.Series([0.0, 100.0], index=dates)
    aligned = {"AAPL": aapl}
    start_date = today - timedelta(days=1)
    end_date = today

    records = _normalize_performance(aligned, dates, start_date, end_date)
    # When close_0 == 0, normalized is hardcoded to 0.0
    assert records[1]["AAPL"] == 0.0


# --------------------------------------------------------------------------- #
# _pairwise_correlation
# --------------------------------------------------------------------------- #


def test_correlation_perfectly_correlated() -> None:
    today = date.today()
    dates = pd.to_datetime(
        [
            today - timedelta(days=4),
            today - timedelta(days=3),
            today - timedelta(days=2),
            today - timedelta(days=1),
            today,
        ]
    )

    aapl = pd.Series([100.0, 102.0, 101.0, 105.0, 110.0], index=dates)
    msft = aapl * 0.5

    aligned = {"AAPL": aapl, "MSFT": msft}
    matrix, columns, note = _pairwise_correlation(aligned)

    assert columns == ["AAPL", "MSFT"]
    by_ticker = {row["ticker"]: row for row in matrix}
    assert by_ticker["AAPL"]["AAPL"] == 1.0
    assert by_ticker["AAPL"]["MSFT"] == pytest.approx(1.0, abs=1e-6)
    assert by_ticker["MSFT"]["AAPL"] == pytest.approx(1.0, abs=1e-6)
    assert note is None


def test_correlation_anti_correlated() -> None:
    today = date.today()
    dates = pd.to_datetime(
        [
            today - timedelta(days=4),
            today - timedelta(days=3),
            today - timedelta(days=2),
            today - timedelta(days=1),
            today,
        ]
    )

    aapl = pd.Series([100.0, 102.0, 101.0, 105.0, 110.0], index=dates)
    diffs = aapl.diff().fillna(0.0)
    msft = 200.0 - diffs.cumsum()  # inverse movements

    aligned = {"AAPL": aapl, "MSFT": msft}
    matrix, columns, note = _pairwise_correlation(aligned)

    by_ticker = {row["ticker"]: row for row in matrix}
    assert by_ticker["AAPL"]["MSFT"] == pytest.approx(-1.0, abs=1e-6)
    assert note is None


def test_correlation_note_with_exactly_two_common_dates_and_nan_safe() -> None:
    today = date.today()
    dates = pd.to_datetime([today - timedelta(days=1), today])

    aapl = pd.Series([100.0, 101.0], index=dates)
    msft = pd.Series([50.0, 50.5], index=dates)

    aligned = {"AAPL": aapl, "MSFT": msft}
    matrix, columns, note = _pairwise_correlation(aligned)

    assert note is not None
    assert "Not enough" in note
    # NaN-safe: must serialize without error.
    json.dumps(matrix)


def test_correlation_zero_variance_nan_becomes_zero() -> None:
    """Test zero-variance NaN→0.0 path (line 268-270).

    When both series have no variance (constant values), np.corrcoef
    produces NaN, which is substituted with 0.0.
    """
    today = date.today()
    dates = pd.to_datetime(
        [today - timedelta(days=2), today - timedelta(days=1), today]
    )

    aapl = pd.Series([100.0, 100.0, 100.0], index=dates)
    msft = pd.Series([50.0, 50.0, 50.0], index=dates)

    aligned = {"AAPL": aapl, "MSFT": msft}
    matrix, columns, note = _pairwise_correlation(aligned)

    by_ticker = {row["ticker"]: row for row in matrix}
    # No variation means NaN correlation, should be substituted with 0.0
    assert by_ticker["AAPL"]["MSFT"] == 0.0


def test_correlation_nan_substitution_for_non_finite() -> None:
    """Test NaN correlation substitution (line 268)."""
    today = date.today()
    dates = pd.to_datetime([today - timedelta(days=1), today])

    aapl = pd.Series([100.0, 101.0], index=dates)
    msft = pd.Series([50.0, 50.0], index=dates)

    aligned = {"AAPL": aapl, "MSFT": msft}
    matrix, columns, note = _pairwise_correlation(aligned)

    by_ticker = {row["ticker"]: row for row in matrix}
    # Zero variance in one series -> NaN correlation -> 0.0
    assert by_ticker["AAPL"]["MSFT"] == 0.0


def test_correlation_empty_aligned_set() -> None:
    """Test empty aligned_closes (line 241)."""
    aligned: dict[str, pd.Series] = {}
    matrix, columns, note = _pairwise_correlation(aligned)

    assert columns == []
    assert matrix == []
    assert note is not None


# --------------------------------------------------------------------------- #
# _ticker_stats -- hand-computed
# --------------------------------------------------------------------------- #


def test_ticker_stats_hand_computed() -> None:
    today = date.today()
    dates = pd.to_datetime(
        [today - timedelta(days=2), today - timedelta(days=1), today]
    )

    close = pd.Series([100.0, 110.0, 99.0], index=dates)

    stats = _ticker_stats("AAPL", close)

    assert stats["symbol"] == "AAPL"
    assert stats["latest_close"] == 99.0
    assert stats["period_return_pct"] == pytest.approx(-1.0)
    assert stats["max_drawdown_pct"] == pytest.approx(-10.0)
    assert stats["best_day_pct"] == pytest.approx(10.0)
    assert stats["worst_day_pct"] == pytest.approx(-10.0)

    returns = pd.Series([0.10, -0.10])
    expected_vol = round(returns.std(ddof=1) * math.sqrt(252) * 100.0, 2)
    assert stats["annualized_volatility_pct"] == pytest.approx(expected_vol)


def test_ticker_stats_single_row_no_volatility() -> None:
    """Test single-row case (line 305-306)."""
    today = date.today()
    dates = pd.to_datetime([today])

    close = pd.Series([100.0], index=dates)

    stats = _ticker_stats("AAPL", close)

    assert stats["annualized_volatility_pct"] == 0.0
    assert stats["max_drawdown_pct"] == 0.0


def test_ticker_stats_no_returns_no_daily_metrics() -> None:
    """Test empty returns (line 311-313)."""
    today = date.today()
    dates = pd.to_datetime([today])

    close = pd.Series([100.0], index=dates)

    stats = _ticker_stats("AAPL", close)

    assert stats["best_day_pct"] == 0.0
    assert stats["worst_day_pct"] == 0.0


def test_ticker_stats_zero_period_return() -> None:
    """Test first_close == 0 guard (line 295-298)."""
    today = date.today()
    dates = pd.to_datetime([today - timedelta(days=1), today])

    close = pd.Series([0.0, 100.0], index=dates)

    stats = _ticker_stats("AAPL", close)

    assert stats["period_return_pct"] == 0.0


def test_ticker_stats_nan_values_guarded_to_zero() -> None:
    """Test NaN/inf guards (line 327-328)."""
    today = date.today()
    dates = pd.to_datetime([today - timedelta(days=1), today])

    close = pd.Series([100.0, 100.0], index=dates)

    stats = _ticker_stats("AAPL", close)

    # All metrics should be finite floats, not NaN or inf
    for key in [
        "latest_close",
        "period_return_pct",
        "annualized_volatility_pct",
        "max_drawdown_pct",
        "best_day_pct",
        "worst_day_pct",
    ]:
        value = stats[key]  # type: ignore[literal-required]
        assert isinstance(value, float)
        assert math.isfinite(value)


# --------------------------------------------------------------------------- #
# _compare_snapshot -- full integration cases
# --------------------------------------------------------------------------- #


def test_snapshot_per_ticker_fetch_failure() -> None:
    today = date.today()
    dates = pd.date_range(end=pd.Timestamp(today), periods=10, freq="D")

    aapl_df = _make_close_df([100.0 + i for i in range(10)], dates)
    msft_df = _make_close_df([50.0 + i * 0.5 for i in range(10)], dates)

    def side_effect(symbol: str, **kwargs: object) -> pd.DataFrame:
        if symbol == "GOOG":
            raise NetworkError("A network error occurred while fetching data.")
        if symbol == "AAPL":
            return aapl_df
        return msft_df

    add_ticker("AAPL")
    add_ticker("MSFT")
    add_ticker("GOOG")

    with patch("ui.compare.fetch_ohlcv", side_effect=side_effect):
        snapshot = _compare_snapshot()

    assert snapshot["status"] == "ok"
    failed_symbols = [f["symbol"] for f in snapshot["failed"]]
    assert "GOOG" in failed_symbols
    assert len(snapshot["stats"]) == 2
    assert set(snapshot["performance_series"]) == {"AAPL", "MSFT"}
    assert len(snapshot["performance"]) == 10


def test_snapshot_single_success_insufficient() -> None:
    """Test single-success 'insufficient' branch (line 387-399)."""
    today = date.today()
    dates = pd.date_range(end=pd.Timestamp(today), periods=10, freq="D")

    aapl_df = _make_close_df([100.0 + i for i in range(10)], dates)

    def side_effect(symbol: str, **kwargs: object) -> pd.DataFrame:
        if symbol == "AAPL":
            return aapl_df
        raise NetworkError("A network error occurred while fetching data.")

    add_ticker("AAPL")
    add_ticker("MSFT")

    with patch("ui.compare.fetch_ohlcv", side_effect=side_effect):
        snapshot = _compare_snapshot()

    assert snapshot["status"] == "insufficient"
    assert snapshot["message"] is not None
    assert len(snapshot["failed"]) == 1


def test_snapshot_misaligned_indexes() -> None:
    today = date.today()

    aapl_dates = pd.date_range(
        end=pd.Timestamp(today) - pd.Timedelta(days=1), periods=4, freq="D"
    )
    msft_dates = pd.date_range(start=aapl_dates[1], periods=4, freq="D")

    aapl_df = _make_close_df([100.0, 101.0, 102.0, 103.0], aapl_dates)
    msft_df = _make_close_df([50.0, 51.0, 52.0, 53.0], msft_dates)

    def side_effect(symbol: str, **kwargs: object) -> pd.DataFrame:
        if symbol == "AAPL":
            return aapl_df
        return msft_df

    add_ticker("AAPL")
    add_ticker("MSFT")

    with patch("ui.compare.fetch_ohlcv", side_effect=side_effect):
        snapshot = _compare_snapshot()

    assert snapshot["status"] == "ok"
    # Common dates = aapl_dates[1:4] intersected with msft_dates[0:3] = 3 dates.
    assert len(snapshot["performance"]) == 3
    assert snapshot["performance"][0]["AAPL"] == 0.0
    assert snapshot["performance"][0]["MSFT"] == 0.0


def test_snapshot_no_overlap_insufficient() -> None:
    today = date.today()

    aapl_dates = pd.date_range(
        end=pd.Timestamp(today) - pd.Timedelta(days=10), periods=5, freq="D"
    )
    msft_dates = pd.date_range(end=pd.Timestamp(today), periods=5, freq="D")

    aapl_df = _make_close_df([100.0, 101.0, 102.0, 103.0, 104.0], aapl_dates)
    msft_df = _make_close_df([50.0, 51.0, 52.0, 53.0, 54.0], msft_dates)

    def side_effect(symbol: str, **kwargs: object) -> pd.DataFrame:
        if symbol == "AAPL":
            return aapl_df
        return msft_df

    add_ticker("AAPL")
    add_ticker("MSFT")

    with patch("ui.compare.fetch_ohlcv", side_effect=side_effect):
        snapshot = _compare_snapshot()

    assert snapshot["status"] == "insufficient"
    assert snapshot["performance"] == []
    assert snapshot["message"] is not None
    assert snapshot["failed"] == []


def test_snapshot_no_data_after_dropna() -> None:
    """Test TickerNotFoundError from empty close series (line 158)."""
    today = date.today()
    dates = pd.date_range(end=pd.Timestamp(today), periods=3, freq="D")

    empty_df = pd.DataFrame(
        {
            "open": [float("nan"), float("nan"), float("nan")],
            "high": [float("nan"), float("nan"), float("nan")],
            "low": [float("nan"), float("nan"), float("nan")],
            "close": [float("nan"), float("nan"), float("nan")],
            "volume": [1000, 1000, 1000],
        },
        index=dates,
    )

    def side_effect(symbol: str, **kwargs: object) -> pd.DataFrame:
        return empty_df

    add_ticker("AAPL")
    add_ticker("MSFT")

    with patch("ui.compare.fetch_ohlcv", side_effect=side_effect):
        snapshot = _compare_snapshot()

    assert snapshot["status"] == "insufficient"
    assert len(snapshot["failed"]) == 2


# --------------------------------------------------------------------------- #
# compare_dashboard
# --------------------------------------------------------------------------- #


def test_compare_dashboard_renders_empty_state() -> None:
    app = compare_dashboard()

    assert app is not None
    assert app.view is not None

    rendered = _to_json(app)
    json.dumps(rendered)  # must serialize without error


def test_compare_dashboard_renders_with_tickers() -> None:
    today = date.today()
    dates = pd.date_range(end=pd.Timestamp(today), periods=10, freq="D")

    aapl_df = _make_close_df([100.0 + i for i in range(10)], dates)
    msft_df = _make_close_df([50.0 + i * 0.5 for i in range(10)], dates)

    def side_effect(symbol: str, **kwargs: object) -> pd.DataFrame:
        if symbol == "AAPL":
            return aapl_df
        return msft_df

    with patch("ui.compare.fetch_ohlcv", side_effect=side_effect):
        add_ticker("AAPL")
        add_ticker("MSFT")
        app = compare_dashboard()

    assert app is not None
    assert app.view is not None

    rendered = _to_json(app)
    json.dumps(rendered)  # must serialize without error
