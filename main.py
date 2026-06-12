"""Entry point for the Stock MCP Service.

This module composes the four providers that make up the Stock MCP
Service into a single `FastMCP` server:

- `price_history_mcp` (`tools/price_history.py`) -- the `price_history`
  app-tool, a price history table/chart dashboard.
- `technical_analysis_mcp` (`tools/technical_analysis.py`) -- the
  `technical_analysis` app-tool, a technical analysis snapshot dashboard.
- `portfolio_app` (`ui/portfolio.py`) -- the `portfolio_dashboard`
  interactive portfolio tracker app.
- `compare_app` (`ui/compare.py`) -- the `compare_dashboard` interactive
  multi-ticker compare app.

`FastMCP("StockMCP", providers=[...])` accepts both plain `FastMCP`
instances (auto-wrapped as providers) and `FastMCPApp` instances (already
providers) in the same `providers` list. The default namespace is empty,
so model-visible tool/UI names (`price_history`, `technical_analysis`,
`portfolio_dashboard`, `compare_dashboard`) remain unprefixed. Backend
`@app.tool()` functions on `portfolio_app` and `compare_app` keep working
after mounting because their `CallTool(fn)` wiring is keyed on the
function reference, not on a namespaced string.

Note: both `portfolio_app` and `compare_app` define a UI-only backend
named `search_tickers`, so fastmcp logs a benign "Duplicate list_tools
component 'tool:search_tickers@'" warning at first `list_tools()`. This is
cosmetic only -- each app's `CallTool(search_tickers)` resolves to its own
backend via an app-name-keyed hash (distinct per app), so the two never
collide at dispatch. Do not "fix" it by renaming a backend.

Run directly (`python main.py`) to start the server over stdio.
"""

from __future__ import annotations

from fastmcp import FastMCP

from tools.price_history import price_history_mcp
from tools.technical_analysis import technical_analysis_mcp
from ui.compare import compare_app
from ui.portfolio import portfolio_app

mcp: FastMCP = FastMCP(
    "StockMCP",
    providers=[price_history_mcp, technical_analysis_mcp, portfolio_app, compare_app],
)


if __name__ == "__main__":
    mcp.run()
