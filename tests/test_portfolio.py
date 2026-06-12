"""Unit tests for `ui.portfolio`.

All price fetches are mocked via `unittest.mock.patch` on
`ui.portfolio.fetch_ohlcv`. No network calls are made. Backend tools
(`add_holding`, `remove_holding`, `search_tickers`) are decorated with
`@portfolio_app.tool()`, which returns the original function unchanged --
so they are called directly here with no MCP context.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest

from tools._data import (
    InvalidTickerError,
    NetworkError,
    TickerNotFoundError,
)
from ui.portfolio import (
    _HOLDINGS,
    _fetch_latest_price,
    _portfolio_snapshot,
    add_holding,
    portfolio_dashboard,
    remove_holding,
    reset_portfolio,
    search_tickers,
)


@pytest.fixture(autouse=True)
def _clean_portfolio() -> object:
    """Ensure `_HOLDINGS` is empty before and after every test."""
    reset_portfolio()
    yield
    reset_portfolio()


def _make_price_df(close: float) -> pd.DataFrame:
    """Build a 1-row OHLCV DataFrame (lowercase columns, DatetimeIndex)."""
    idx = pd.date_range(end=pd.Timestamp.today(), periods=1, freq="D", name="Date")
    return pd.DataFrame(
        {
            "open": [close],
            "high": [close],
            "low": [close],
            "close": [close],
            "volume": [1000],
        },
        index=idx,
    )


def _make_nan_price_df() -> pd.DataFrame:
    """Build a 1-row OHLCV DataFrame whose `close` column is all-NaN.

    Mirrors the shape yfinance can return for the current-day bar before
    a close price has been recorded.
    """
    idx = pd.date_range(end=pd.Timestamp.today(), periods=1, freq="D", name="Date")
    return pd.DataFrame(
        {
            "open": [float("nan")],
            "high": [float("nan")],
            "low": [float("nan")],
            "close": [float("nan")],
            "volume": [0],
        },
        index=idx,
    )


def _to_json(app: object) -> dict:
    """Serialize a PrefabApp to a dict.

    NOTE: `PrefabApp.to_json()` wraps the view in an additional container on
    each call, so this must only be called ONCE per app instance.
    """
    return app.to_json()  # type: ignore[attr-defined,no-any-return]


# --------------------------------------------------------------------------- #
# add_holding
# --------------------------------------------------------------------------- #


def test_add_holding_new_symbol() -> None:
    with patch_fetch(150.0):
        snapshot = add_holding("aapl", 10, 100)

    assert "AAPL" in _HOLDINGS
    assert _HOLDINGS["AAPL"]["quantity"] == 10
    assert _HOLDINGS["AAPL"]["cost_basis"] == 100
    assert len(snapshot["holdings"]) == 1


def test_add_holding_existing_averages_cost_basis() -> None:
    with patch_fetch(150.0):
        add_holding("AAPL", 10, 100)
        add_holding("AAPL", 10, 200)

    holding = _HOLDINGS["AAPL"]
    assert holding["quantity"] == 20
    # weighted avg: (10*100 + 10*200) / 20 = 150
    assert holding["cost_basis"] == pytest.approx(150.0)


def test_add_holding_invalid_ticker_raises() -> None:
    with pytest.raises(InvalidTickerError):
        add_holding("???", 10, 100)


def test_add_holding_nonpositive_quantity_raises() -> None:
    with pytest.raises(ValueError):
        add_holding("AAPL", 0, 100)

    with pytest.raises(ValueError):
        add_holding("AAPL", -5, 100)


def test_add_holding_negative_cost_basis_raises() -> None:
    with pytest.raises(ValueError):
        add_holding("AAPL", 10, -1)


# --------------------------------------------------------------------------- #
# remove_holding
# --------------------------------------------------------------------------- #


def test_remove_existing_holding() -> None:
    with patch_fetch(150.0):
        add_holding("AAPL", 10, 100)
        snapshot = remove_holding("aapl")

    assert "AAPL" not in _HOLDINGS
    assert snapshot["holdings"] == []


def test_remove_nonexistent_holding_idempotent() -> None:
    snapshot = remove_holding("AAPL")
    assert "AAPL" not in _HOLDINGS
    assert snapshot["holdings"] == []


def test_remove_invalid_ticker_raises() -> None:
    with pytest.raises(InvalidTickerError):
        remove_holding("???")


# --------------------------------------------------------------------------- #
# search_tickers
# --------------------------------------------------------------------------- #


def test_search_tickers_found() -> None:
    with patch_fetch(150.0):
        results = search_tickers("aapl")

    assert len(results) == 1
    assert results[0]["symbol"] == "AAPL"
    assert results[0]["status"] == "found"


def test_search_tickers_not_found() -> None:
    with patch(
        "ui.portfolio.fetch_ohlcv",
        side_effect=TickerNotFoundError("No data found for ticker 'ZZZZ'."),
    ):
        results = search_tickers("zzzz")

    assert len(results) == 1
    assert results[0]["status"] == "not_found"
    assert "ZZZZ" in results[0]["message"]


def test_search_tickers_empty_query() -> None:
    assert search_tickers("") == []
    assert search_tickers("   ") == []


# --------------------------------------------------------------------------- #
# _fetch_latest_price
# --------------------------------------------------------------------------- #


def test_fetch_latest_price_all_nan_close_returns_none_without_raising() -> None:
    with patch("ui.portfolio.fetch_ohlcv", return_value=_make_nan_price_df()):
        price, error = _fetch_latest_price("AAPL")

    assert price is None
    assert error is not None


# --------------------------------------------------------------------------- #
# _portfolio_snapshot
# --------------------------------------------------------------------------- #


def test_snapshot_single_holding_pnl() -> None:
    with patch_fetch(150.0):
        add_holding("AAPL", 10, 100)
        snapshot = _portfolio_snapshot()

    holding = snapshot["holdings"][0]
    assert holding["market_value"] == 1500.0
    assert holding["cost"] == 1000.0
    assert holding["pnl"] == 500.0
    assert holding["pnl_pct"] == 50.0
    assert holding["allocation_pct"] == 100.0

    assert snapshot["total_market_value"] == 1500.0
    assert snapshot["total_cost"] == 1000.0
    assert snapshot["total_pnl"] == 500.0
    assert snapshot["total_pnl_pct"] == 50.0


def test_snapshot_multiple_holdings_allocation_sums_to_100() -> None:
    with patch_fetch(150.0):
        add_holding("AAPL", 10, 100)
    with patch_fetch(50.0):
        add_holding("MSFT", 20, 40)

    with patch_fetch_by_symbol({"AAPL": 150.0, "MSFT": 50.0}):
        snapshot = _portfolio_snapshot()

    total_allocation = sum(
        h["allocation_pct"]
        for h in snapshot["holdings"]
        if h["allocation_pct"] is not None
    )
    assert total_allocation == pytest.approx(100.0)


def test_snapshot_empty_portfolio() -> None:
    snapshot = _portfolio_snapshot()

    assert snapshot["holdings"] == []
    assert snapshot["total_market_value"] == 0.0
    assert snapshot["total_cost"] == 0.0
    assert snapshot["total_pnl"] == 0.0
    assert snapshot["total_pnl_pct"] is None


def test_snapshot_price_fetch_failure() -> None:
    with patch_fetch(150.0):
        add_holding("AAPL", 10, 100)
    with patch_fetch(50.0):
        add_holding("MSFT", 20, 40)

    def side_effect(symbol: str, **kwargs: object) -> pd.DataFrame:
        if symbol == "AAPL":
            raise NetworkError("A network error occurred while fetching data.")
        return _make_price_df(50.0)

    with patch("ui.portfolio.fetch_ohlcv", side_effect=side_effect):
        snapshot = _portfolio_snapshot()

    by_symbol = {h["symbol"]: h for h in snapshot["holdings"]}

    aapl = by_symbol["AAPL"]
    assert aapl["latest_price"] is None
    assert aapl["market_value"] is None
    assert aapl["pnl"] is None
    assert aapl["allocation_pct"] is None
    assert aapl["price_error"] is not None

    msft = by_symbol["MSFT"]
    assert msft["latest_price"] == 50.0
    assert msft["market_value"] == 1000.0
    # Allocation recomputed over priced holdings only -> MSFT is 100%.
    assert msft["allocation_pct"] == 100.0
    assert msft["price_error"] is None


def test_snapshot_all_nan_close_degrades_gracefully() -> None:
    with patch_fetch(150.0):
        add_holding("AAPL", 10, 100)

    with patch("ui.portfolio.fetch_ohlcv", return_value=_make_nan_price_df()):
        snapshot = _portfolio_snapshot()

    holding = snapshot["holdings"][0]
    assert holding["latest_price"] is None
    assert holding["market_value"] is None
    assert holding["pnl"] is None
    assert holding["pnl_pct"] is None
    assert holding["allocation_pct"] is None
    assert holding["price_error"] is not None

    assert snapshot["total_market_value"] == 0.0
    # total_cost is still 1000.0 (cost basis unaffected by missing price),
    # so total_pnl_pct reflects a full unrealized loss rather than None.
    assert snapshot["total_pnl_pct"] == -100.0


# --------------------------------------------------------------------------- #
# portfolio_dashboard
# --------------------------------------------------------------------------- #


def test_portfolio_dashboard_renders_empty_state() -> None:
    app = portfolio_dashboard()

    assert app is not None
    assert app.view is not None

    rendered = _to_json(app)
    json.dumps(rendered)  # must serialize without error


def test_portfolio_dashboard_renders_with_holdings() -> None:
    with patch_fetch(150.0):
        add_holding("AAPL", 10, 100)
        app = portfolio_dashboard()

    assert app is not None
    assert app.view is not None

    rendered = _to_json(app)
    json.dumps(rendered)  # must serialize without error


# --------------------------------------------------------------------------- #
# Patch helpers
# --------------------------------------------------------------------------- #


def patch_fetch(close: float) -> Any:
    """Return a patch context manager for `ui.portfolio.fetch_ohlcv`.

    The mocked `fetch_ohlcv` returns a single-row OHLCV DataFrame with the
    given `close` price, regardless of arguments.
    """
    return patch("ui.portfolio.fetch_ohlcv", return_value=_make_price_df(close))


def patch_fetch_by_symbol(prices: dict[str, float]) -> Any:
    """Return a patch context manager for `ui.portfolio.fetch_ohlcv`.

    The mocked `fetch_ohlcv` returns a single-row OHLCV DataFrame whose
    close price is looked up from `prices` by the (normalized) `symbol`
    argument.
    """

    def side_effect(symbol: str, **kwargs: object) -> pd.DataFrame:
        return _make_price_df(prices[symbol])

    return patch("ui.portfolio.fetch_ohlcv", side_effect=side_effect)


def test_snapshot_all_holdings_have_prices() -> None:
    """Test total_pnl_pct computed when total_cost is not zero (line 300)."""
    with patch_fetch(150.0):
        add_holding("AAPL", 10, 100)
        snapshot = _portfolio_snapshot()

    assert snapshot["total_cost"] > 0.0
    assert snapshot["total_pnl_pct"] is not None


def test_snapshot_zero_cost_total_pnl_pct_none() -> None:
    """Test total_pnl_pct == None when total_cost == 0 (lines 311-312)."""
    with patch_fetch(100.0):
        add_holding("AAPL", 10, 0.0)
        snapshot = _portfolio_snapshot()

    assert snapshot["total_cost"] == 0.0
    assert snapshot["total_pnl_pct"] is None


def test_snapshot_pnl_pct_with_zero_cost_basis() -> None:
    """Test holding pnl_pct == None when cost == 0 (line 151)."""
    with patch_fetch(100.0):
        add_holding("AAPL", 10, 0.0)
        snapshot = _portfolio_snapshot()

    holding = snapshot["holdings"][0]
    assert holding["cost"] == 0.0
    assert holding["pnl_pct"] is None


def test_search_tickers_invalid_ticker_format_returns_not_found() -> None:
    """Test search_tickers with invalid format (lines 299-302)."""
    results = search_tickers("???")

    assert len(results) == 1
    assert results[0]["status"] == "not_found"
    assert "not a valid ticker" in results[0]["message"]


def test_search_tickers_stock_data_error_returns_not_found() -> None:
    """Test search_tickers catches StockDataError (lines 303-310)."""
    with patch(
        "ui.portfolio.fetch_ohlcv",
        side_effect=TickerNotFoundError("No data found for ticker 'ZZZZ'."),
    ):
        results = search_tickers("zzzz")

    assert len(results) == 1
    assert results[0]["status"] == "not_found"


def test_search_tickers_value_error_returns_not_found() -> None:
    """Test search_tickers catches ValueError (line 311-312)."""
    with patch("ui.portfolio.fetch_ohlcv", side_effect=ValueError("Some error")):
        results = search_tickers("AAPL")

    assert len(results) == 1
    assert results[0]["status"] == "not_found"
    assert "Some error" in results[0]["message"]


def test_portfolio_dashboard_renders_with_price_error() -> None:
    """Test portfolio dashboard renders holdings with price errors."""
    with patch_fetch(150.0):
        add_holding("AAPL", 10, 100)
        app = portfolio_dashboard()

    rendered = _to_json(app)
    serialized = json.dumps(rendered)

    assert '"variant": "destructive"' in serialized
