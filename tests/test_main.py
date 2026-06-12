"""Integration smoke tests for `main`.

These tests verify that the four providers (`price_history_mcp`,
`technical_analysis_mcp`, `portfolio_app`, `compare_app`) are wired into
the top-level `mcp` server with unprefixed, model-visible names, and that
the UI-only backend tools remain hidden from `list_tools()`.

Network-free: only `mcp.list_tools()` is awaited, which enumerates already
-registered components without invoking any tool (no `fetch_ohlcv` /
yfinance calls occur).
"""

from __future__ import annotations

import pytest
from fastmcp import FastMCP

from main import mcp

#: Model-visible entry points expected from the four mounted providers:
#: the `price_history` and `technical_analysis` app-tools
#: (`tools/price_history.py`, `tools/technical_analysis.py`), and the
#: `portfolio_dashboard` / `compare_dashboard` `@app.ui()` entry points
#: (`ui/portfolio.py`, `ui/compare.py`).
EXPECTED_MODEL_VISIBLE_NAMES: set[str] = {
    "price_history",
    "technical_analysis",
    "portfolio_dashboard",
    "compare_dashboard",
}

#: UI-only backend tools (`@portfolio_app.tool()` / `@compare_app.tool()`)
#: that must NOT be exposed to the model via `list_tools()`.
BACKEND_TOOL_NAMES: set[str] = {
    "add_holding",
    "remove_holding",
    "search_tickers",
    "add_ticker",
    "remove_ticker",
}


@pytest.mark.asyncio
async def test_model_visible_tools_are_discoverable() -> None:
    """The four entry points are discoverable, unprefixed, by the model."""
    tools = await mcp.list_tools()
    names = {t.name for t in tools}

    assert EXPECTED_MODEL_VISIBLE_NAMES <= names

    # Mounting must not introduce namespaced variants of the entry points.
    for name in names:
        assert "_" + "price_history" not in name or name == "price_history"
    assert "PriceHistory_price_history" not in names
    assert "TechnicalAnalysis_technical_analysis" not in names
    assert "Portfolio_portfolio_dashboard" not in names
    assert "Compare_compare_dashboard" not in names


@pytest.mark.asyncio
async def test_backend_app_tools_are_not_model_visible() -> None:
    """Backend `@app.tool()` functions stay UI-only, not model-visible."""
    tools = await mcp.list_tools()
    names = {t.name for t in tools}

    assert BACKEND_TOOL_NAMES.isdisjoint(names)


def test_server_is_constructed() -> None:
    """`mcp` is a `FastMCP` server named "StockMCP"."""
    assert isinstance(mcp, FastMCP)
    assert mcp.name == "StockMCP"
