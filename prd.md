# Stock MCP Service - Product Requirements Document

## Overview
A FastMCP service that showcases the full range of FastMCP + prefab UI capabilities
through stock-market tooling. It spans both one-shot, read-only tools
(`@mcp.tool(app=True)`) and fully interactive applications (`FastMCPApp` with
`@app.ui()` + `@app.tool()`), demonstrating how an MCP server can fetch data,
render rich visualizations, and let users interact with results directly in the UI.

This is a demo/showcase project: breadth of capability and polish matter more than
production hardening. The bar for "done" is **working, tested, and polished**.

## Target Audience
Developers and power users (the author primarily) exploring what FastMCP + prefab UI
can do. They invoke the service through an MCP client (e.g. Claude) to fetch prices,
run technical analysis, track a portfolio, and compare tickers — and to see the
framework's interaction patterns in action.

## Core Features
1. **Price history + table** — one-shot tool: fetch OHLCV for a ticker over a date
   range, render a price chart and a data table.
2. **Technical analysis snapshot** — one-shot tool: compute RSI, MACD, moving
   averages, and Bollinger Bands (via `ta`) and render a multi-panel indicator
   dashboard.
3. **Interactive portfolio tracker** — `FastMCPApp`: add/remove holdings, search
   tickers, and view live P&L and allocation. Holdings are held **in memory** for
   the session (no persistence by design). Demonstrates the UI calling backend tools.
4. **Multi-ticker compare dashboard** — `FastMCPApp`: search and compare several
   tickers side-by-side with normalized performance, correlation, and key stats.

## Tech Stack
- **Language**: Python 3.13
- **Server framework**: FastMCP (`fastmcp`)
- **UI**: prefab UI (`prefab-ui`)
- **Market data**: yfinance
- **Data/analysis**: pandas, numpy, `ta` (technical-analysis indicators)
- **Tooling**: pytest, pytest-asyncio, coverage, ruff, mypy, isort
- **Package manager**: uv

## Architecture
Single FastMCP server (`main.py`) that aggregates simple tools and interactive apps.

- **Simple tools** live in `tools/<name>.py` and use `@mcp.tool(app=True)` —
  one-shot fetch → render → done, read-only.
- **Interactive apps** live in `ui/<name>.py` as `FastMCPApp` instances using
  `@app.ui()` (model-visible entry point returning a `PrefabApp`), `@app.tool()`
  (UI-only backend), and `@app.tool(model=True)` (exposed to both model and UI).
- Apps are wired into the server via `FastMCP("StockMCP", providers=[...])`.
- Tool references inside the UI use **function references** in `CallTool(fn)`,
  not strings, so they survive namespacing.
- A shared helper module centralizes input validation (ticker/date) and yfinance
  data fetching with graceful error handling, reused by every feature.

## Data Model
No database. Entities are transient/in-memory:
- **Ticker request**: symbol (str), date range / period (validated before fetch).
- **OHLCV frame**: pandas DataFrame returned from yfinance.
- **Indicator set**: derived columns (RSI, MACD, SMA/EMA, Bollinger Bands).
- **Holding** (portfolio tracker, in-memory only): symbol, quantity, cost basis.
- **Comparison set**: list of symbols + their normalized series and summary stats.

## UI/UX Requirements
- All chart/dashboard rendering MUST follow `.claude/skills/stock-data-viz/SKILL.md`
  (read it before writing any chart code).
- Multi-panel dashboards compose metrics + charts + tables cleanly.
- Interactive apps provide search/add/remove affordances and update on interaction.
- Graceful, readable states for invalid tickers, empty data, and API failures.

## Security Considerations
- No authentication (local demo service).
- Validate all inputs (ticker format, date ranges, periods) before calling yfinance.
- Never hardcode tickers or dates — always parameterize.
- No secrets required; do not read `.env`/credential files.

## Third-Party Integrations
- **yfinance** — sole external data source (Yahoo Finance). Network calls must
  degrade gracefully on failure, timeout, or empty result.

## Constraints & Assumptions
- Holdings persistence is intentionally **in-memory only** — resets on restart.
- No new dependencies beyond those already in `pyproject.toml` without asking.
- Type hints everywhere; pass `ruff`, `mypy`, and `isort`.
- Work is executed via the subagent workflow defined in `CLAUDE.md` — never
  implement directly in the orchestration context.

## Success Criteria
- All four features run and render correctly when invoked through an MCP client.
- Inputs are validated; yfinance failures degrade gracefully with clear messaging.
- Charts/dashboards follow the `stock-data-viz` skill and look polished.
- Unit tests pass with reasonable coverage; `ruff`/`mypy`/`isort` are clean.
- Every task in the list below is marked `"passes": true`.

---

## Task List

```json
[
  {
    "category": "setup",
    "description": "Scaffold the FastMCP server and package layout",
    "steps": [
      "Replace the stub main.py with a FastMCP('StockMCP') server entry point that runs the server",
      "Create tools/__init__.py and ui/__init__.py package markers",
      "Confirm `fastmcp` and `prefab-ui` import and the server boots with no tools yet",
      "Run ruff, mypy, and isort clean on the scaffold"
    ],
    "passes": true
  },
  {
    "category": "setup",
    "description": "Build a shared validation + yfinance fetch helper",
    "steps": [
      "Create a helper module (e.g. tools/_data.py) with typed functions to validate ticker symbols, date ranges, and periods",
      "Add a wrapper around yfinance that returns an OHLCV DataFrame and handles invalid tickers, empty results, timeouts, and network errors gracefully",
      "Raise/return clear, typed error signals the feature tools can surface to the UI",
      "Add unit tests covering valid input, invalid ticker, empty result, and fetch failure (mock yfinance)"
    ],
    "passes": true
  },
  {
    "category": "feature",
    "description": "Price history + table tool",
    "steps": [
      "Read .claude/skills/stock-data-viz/SKILL.md before writing chart code",
      "Create tools/price_history.py with an @mcp.tool(app=True) that takes a ticker and date range, fetches OHLCV via the shared helper, and renders a price chart plus a data table",
      "Validate inputs before fetching; surface graceful messaging on bad ticker / no data",
      "Add unit tests for the tool's data shaping and validation paths"
    ],
    "passes": true
  },
  {
    "category": "feature",
    "description": "Technical analysis snapshot tool",
    "steps": [
      "Read .claude/skills/stock-data-viz/SKILL.md before writing chart code",
      "Create tools/technical_analysis.py with an @mcp.tool(app=True) that computes RSI, MACD, moving averages (SMA/EMA), and Bollinger Bands via `ta`",
      "Render a multi-panel indicator dashboard (price + overlays, plus oscillator panels)",
      "Validate inputs and degrade gracefully on insufficient/empty data",
      "Add unit tests for indicator computation and edge cases (short series, NaNs)"
    ],
    "passes": true
  },
  {
    "category": "feature",
    "description": "Interactive portfolio tracker app (in-memory)",
    "steps": [
      "Read .claude/skills/stock-data-viz/SKILL.md before writing dashboard code",
      "Create ui/portfolio.py as a FastMCPApp with an @app.ui() entry point returning a PrefabApp",
      "Add @app.tool() backend tools to add/remove holdings (symbol, quantity, cost basis) and search tickers, holding state in memory for the session",
      "Render live P&L and allocation; wire UI->backend with CallTool(fn) using function references",
      "Add unit tests for add/remove/search and P&L/allocation math"
    ],
    "passes": true
  },
  {
    "category": "feature",
    "description": "Multi-ticker compare dashboard app",
    "steps": [
      "Read .claude/skills/stock-data-viz/SKILL.md before writing dashboard code",
      "Create ui/compare.py as a FastMCPApp with an @app.ui() entry point and @app.tool() search/compare backends",
      "Compute normalized performance, pairwise correlation, and key stats across the selected tickers",
      "Render a side-by-side comparison dashboard; wire UI->backend with CallTool(fn) function references",
      "Add unit tests for normalization, correlation, and stat computation"
    ],
    "passes": true
  },
  {
    "category": "integration",
    "description": "Wire all tools and apps into the server",
    "steps": [
      "Mount the price_history and technical_analysis tools and the portfolio and compare apps in main.py via FastMCP('StockMCP', providers=[...])",
      "Verify namespacing does not break UI->backend CallTool references",
      "Smoke-test that the server boots and all four features are discoverable",
      "Run ruff, mypy, and isort clean across the project"
    ],
    "passes": true
  },
  {
    "category": "styling",
    "description": "Cross-cutting polish pass",
    "steps": [
      "Audit every chart/dashboard against .claude/skills/stock-data-viz/SKILL.md for consistent, polished visuals",
      "Ensure invalid-ticker, empty-data, and API-failure states render clear, user-friendly messages everywhere",
      "Standardize labels, titles, and number/date formatting across features",
      "Confirm no hardcoded tickers or dates remain anywhere"
    ],
    "passes": true
  },
  {
    "category": "testing",
    "description": "Coverage and quality gate",
    "steps": [
      "Run the full pytest suite and a coverage report; fill gaps to reach reasonable coverage on tools/ and ui/",
      "Verify ruff, mypy, and isort all pass clean",
      "Confirm all four features run and render when invoked through the server",
      "Mark remaining tasks complete only after reviewer approval and passing tests"
    ],
    "passes": true
  }
]
```

---

## Agent Instructions

This project uses the subagent workflow defined in `CLAUDE.md`. Do not implement in
the orchestration context. For each task:

1. Read `activity.md` to find current state
2. Find the next task with `"passes": false`
3. Spawn **planner** — task description + relevant context → returns spec + file manifest
4. Spawn **code-developer** — spec only → returns implemented files
5. Spawn **code-reviewer** — implemented files → returns findings
6. If findings are non-trivial, spawn **code-developer** again with the diff
7. Spawn **unit-tester** — implemented files → returns test results
8. Mark the task `"passes": true` only when the reviewer approves and tests pass
9. Log completion in `activity.md`
10. Repeat

Return one-line summaries only. Do not paste specs, implementation, or test output
into the orchestration context.

---

## Completion Criteria
All tasks marked with `"passes": true`, reviewer-approved, with passing tests and
clean ruff/mypy/isort.
