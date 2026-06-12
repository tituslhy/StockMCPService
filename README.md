# Stock MCP Service

A [FastMCP](https://github.com/jlowin/fastmcp) server that turns natural‑language
stock questions into **rich, interactive dashboards** rendered right inside your
MCP client. Ask Claude for a price history, a technical‑analysis snapshot, a
portfolio tracker, or a multi‑ticker comparison — and get back a real charted UI
(powered by [prefab‑ui](https://pypi.org/project/prefab-ui/)), not a wall of text.

Market data comes from [yfinance](https://pypi.org/project/yfinance/) (Yahoo
Finance). No API keys, no database — holdings live in memory for the session.

---

## Contents

- [What you can do with it](#what-you-can-do-with-it)
- [Important: every tool returns a UI app, not a text reply](#important-every-tool-returns-a-ui-app-not-a-text-reply)
- [Requirements](#requirements)
- [Setup](#setup)
- [Connect it to the Claude desktop app (stdio)](#connect-it-to-the-claude-desktop-app-stdio)
- [Example queries & expected results](#example-queries--expected-results)
- [Architecture (brief)](#architecture-brief)
- [Development](#development)
- [Project layout](#project-layout)
- [Notes & constraints](#notes--constraints)

---

## What you can do with it

| # | Feature | Model‑visible tool | What it renders |
|---|---------|--------------------|-----------------|
| 1 | **Price history** | `price_history` | One‑shot dashboard: summary metrics + close‑price line chart + volume bar chart + sortable/searchable OHLCV table |
| 2 | **Technical analysis** | `technical_analysis` | One‑shot dashboard: latest indicator metrics + price chart with Bollinger Bands & moving‑average overlays + RSI panel (70/30 bands) + MACD panel (line + histogram) |
| 3 | **Portfolio tracker** | `portfolio_dashboard` | **Interactive** app: add/remove holdings, search tickers, live P&L and allocation — all inside the UI |
| 4 | **Compare dashboard** | `compare_dashboard` | **Interactive** app: add/remove tickers, normalized %‑performance line chart, pairwise return‑correlation matrix, per‑ticker key stats |

Indicators (feature 2) are computed with the [`ta`](https://pypi.org/project/ta/)
library: RSI(14), MACD(12/26/9), SMA(20 & 50), EMA(20), Bollinger Bands(20, 2σ).

---

## Important: every tool returns a UI app, not a text reply

This is the part to understand for a good demo.

- **All four model‑visible tools return a prefab UI app.** When Claude calls
  `price_history`, `technical_analysis`, `portfolio_dashboard`, or
  `compare_dashboard`, the result is an interactive dashboard, not prose. To
  *see* it rendered you need an MCP client that supports interactive UI / "apps"
  (the Claude desktop app is the target here).
- **The data‑returning functions are UI‑only.** Inside the portfolio and compare
  apps there are backend tools — `add_holding`, `remove_holding`, `add_ticker`,
  `remove_ticker`, `search_tickers` — that return plain data (dicts/lists). These
  are **not exposed to Claude**; they are invoked by the dashboard itself when you
  click "Add", "Remove", or "Search", and their results flow back into the UI to
  update P&L, allocation, correlations, etc. You won't see them as text replies.

So: **Claude → renders a dashboard. You → interact with the dashboard.** There is
no model‑visible tool in this project that returns a plain‑text/data answer to
Claude — the design deliberately favours visual, interactive results.

---

## Requirements

- **Python 3.13**
- **[uv](https://docs.astral.sh/uv/)** (package manager / runner)
- Internet access at *runtime* (yfinance calls Yahoo Finance when a tool is
  actually invoked). The test suite never touches the network.

---

## Setup

```bash
# from the project root
uv sync          # install all dependencies from pyproject.toml / uv.lock
```

### Run it standalone (sanity check)

```bash
uv run python main.py
# or, equivalently:
uv run fastmcp run main.py
```

The server starts on **stdio** transport (via `mcp.run()`), which is exactly what
the Claude desktop app expects for a local MCP server. It will sit waiting for an
MCP client to connect — that's normal. Press `Ctrl‑C` to stop.

To confirm everything is wired without a client, run the tests (see
[Development](#development)).

---

## Connect it to the Claude desktop app (stdio)

Because you're running locally, **stdio is the right transport** — Claude launches
`main.py` as a subprocess and talks to it over stdin/stdout.

### 1. Find your Claude config file

- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

(Create the file if it doesn't exist.)

### 2. Add this server

```jsonc
{
  "mcpServers": {
    "stock-mcp": {
      "command": "uv",
      "args": [
        "--directory",
        "/Users/tituslim/Documents/2. Personal Learning Folder/Personal Projects/StockMCPService",
        "run",
        "python",
        "main.py"
      ]
    }
  }
}
```

Notes:
- The `--directory` flag points `uv` at this project regardless of where Claude
  launches it from. Keep the absolute path (spaces are fine inside the JSON
  string). Adjust it if you move the project.
- If `uv` isn't on Claude's `PATH`, use its full path as `"command"` (find it with
  `which uv`), e.g. `"/Users/tituslim/.local/bin/uv"`.

### 3. Restart Claude

Fully quit and reopen the Claude desktop app. The four tools should appear in the
tools/menu (look for the MCP/tools indicator). When Claude calls one, the
dashboard renders inline.

> **Rendering note:** these tools return prefab UI "apps." Seeing them as live
> dashboards requires a Claude surface with interactive‑app/MCP‑UI rendering
> enabled. If your client can't render UI, it will still receive the tool result —
> you just won't get the charted view. stdio + a UI‑capable Claude desktop build
> is the intended demo setup.

---

## Example queries & expected results

Try these in the Claude desktop app once connected. "Result type" tells you what
to expect on screen.

### 1. Price history → one‑shot dashboard app

> **"Show me Apple's price history for the last 3 months."**
> **"Plot TSLA from 2024-01-01 to 2024-06-01."**
> **"What has NVDA's price done lately?"**

- **Tool:** `price_history(ticker, start?, end?)`
- **Result:** an **app** — metrics row (last price, % change, latest volume), a
  close‑price line chart, a volume bar chart, and a searchable OHLCV table.
- Dates are optional; with none given it defaults to the **last ~90 days** (today
  back 90 days, computed live — nothing is hardcoded).

### 2. Technical analysis → one‑shot dashboard app

> **"Give me a technical analysis snapshot for MSFT."**
> **"Show RSI, MACD and Bollinger Bands for AMZN over the past year."**

- **Tool:** `technical_analysis(ticker, start?, end?)`
- **Result:** an **app** — indicator metrics (latest RSI, MACD signal state,
  SMA/EMA), a price chart with Bollinger Band + moving‑average overlays, an RSI
  sub‑panel with Overbought/Oversold badges, and a MACD line + histogram panel.
- Default window is ~250 days so indicators have enough warm‑up data.

### 3. Portfolio tracker → interactive app

> **"Open a portfolio tracker."**
> **"I want to track a stock portfolio."**

- **Tool:** `portfolio_dashboard()`
- **Result:** an **interactive app**. Claude renders an empty tracker; **you**
  then use the in‑UI form to add holdings (symbol, quantity, cost basis), search
  tickers, and remove positions. Each action calls a UI‑only backend
  (`add_holding` / `remove_holding` / `search_tickers`) that returns updated data
  *to the dashboard* — live total value, total P&L, P&L %, and per‑holding
  allocation update in place. Holdings are in‑memory for the session (reset on
  restart — by design).

### 4. Compare dashboard → interactive app

> **"Compare AAPL, MSFT and GOOG."**
> **"Open a tool to compare a few tickers side by side."**

- **Tool:** `compare_dashboard()`
- **Result:** an **interactive app**. Add two or more tickers in the UI to get a
  normalized %‑from‑start performance line chart (so different price levels are
  comparable), a pairwise **return‑correlation matrix**, and a key‑stats table
  (period return, annualized volatility, max drawdown, best/worst day). Needs ≥2
  tickers; with fewer it shows a friendly "add at least 2 tickers" message.

### Edge cases (also rendered as graceful app states — never crashes)

| Query | What you get |
|-------|--------------|
| **"Price history for ZZZZ"** (bad/unknown ticker) | An app showing a clear "unable to load" error card with the reason |
| **"Technical analysis for a brand‑new ticker with 5 days of data"** | An app showing an "insufficient data — needs ≥35 trading days" notice |
| Yahoo Finance unreachable / times out | A graceful "network error, try again later" card — not a stack trace |
| **"Compare just AAPL"** | The compare app prompting you to add at least 2 tickers |

> Reminder on "app vs text": in every row above, the **answer is an app**. The
> only place data (not UI) is returned is *inside* the portfolio/compare apps when
> their Add/Remove/Search buttons call backend tools — and that data goes to the
> dashboard, not to Claude's chat reply.

---

## Architecture (brief)

- `main.py` — composes everything into one server:
  `FastMCP("StockMCP", providers=[price_history_mcp, technical_analysis_mcp, portfolio_app, compare_app])`.
- `tools/` — one‑shot, read‑only tools using `@mcp.tool(app=True)`:
  - `price_history.py`, `technical_analysis.py`
  - `_data.py` — the **single** yfinance entry point: validates tickers/dates and
    fetches OHLCV, mapping every failure (invalid ticker, no data, timeout, rate
    limit) to a typed, UI‑safe error. Every other module fetches through this.
- `ui/` — interactive `FastMCPApp`s using `@app.ui()` (model‑visible entry) +
  `@app.tool()` (UI‑only backends):
  - `portfolio.py`, `compare.py`
- Tool/UI names are unprefixed and discoverable as `price_history`,
  `technical_analysis`, `portfolio_dashboard`, `compare_dashboard`.

---

## Development

All commands run through `uv`:

```bash
uv run pytest                 # full test suite (fast, fully network-mocked)
uv run coverage run -m pytest && uv run coverage report   # coverage
uv run ruff check .           # lint
uv run ruff format --check .  # format check
uv run isort --check-only .   # import order
uv run mypy .                 # type check
```

The suite is **network‑guarded**: `tests/conftest.py` blocks the yfinance boundary
so no test can ever hit Yahoo Finance — a forgotten mock fails loudly instead of
making a live call. Current coverage is ~99% across `tools/` and `ui/`.

---

## Project layout

```
StockMCPService/
├── main.py                     # server entry point (composes all providers)
├── tools/
│   ├── _data.py                # shared validation + yfinance fetch (sole network door)
│   ├── price_history.py        # @mcp.tool(app=True) price_history
│   └── technical_analysis.py   # @mcp.tool(app=True) technical_analysis
├── ui/
│   ├── portfolio.py            # FastMCPApp: portfolio_dashboard (+ UI-only backends)
│   └── compare.py              # FastMCPApp: compare_dashboard (+ UI-only backends)
├── tests/                      # pytest suite + conftest network guard
├── pyproject.toml              # deps + tooling config
└── prd.md / activity.md        # product spec + build log
```

---

## Notes & constraints

- **No persistence:** portfolio holdings and the compare set are in‑memory for the
  session and reset when the server restarts. This is intentional (a demo of
  FastMCP + prefab‑ui interaction patterns).
- **No secrets:** no auth, no API keys. yfinance is the only external dependency.
- **Inputs are validated** before any network call; tickers and date ranges are
  never hardcoded.
