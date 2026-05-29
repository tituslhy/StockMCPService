# Stock MCP Service

## What This Project Does
A FastMCP service that provides stock market tools and prefab UI dashboards.

## Features
1. Fetch stock ticker price data from Yahoo Finance given a ticker name.
2. Return stock price data in a table for the last 10 specified intervals.
3. For multiple tickers across a longer horizon, render an interactive dashboard (prefab UI app) with charts.
4. Run technical analysis using the `ta` library and render results in a prefab UI app.
5. Show portfolio performance: plot amount invested vs. amount gained (total value - invested), and yield % ((gained/invested) * 100). Y-axis in dollars, x-axis in dates.

## Tech Stack
- **FastMCP** — MCP service framework
- **yfinance** — Yahoo Finance data fetching
- **Pandas + NumPy** — data processing
- **ta** (technical analysis library) — technical indicators
- **Prefab UI** — frontend dashboard rendering

## Project Structure (follow this)
- `main.py` — FastMCP server entry point
- `tools/` — one file per MCP tool
- `ui/` — prefab UI app definitions

## Code Rules
- Python 3.13
- Use type hints everywhere
- Keep each tool in its own file under `tools/`
- Never hardcode tickers or dates — always use parameters
- Always validate inputs before calling yfinance

## Before Doing Anything Destructive
- Ask me first before deleting or overwriting files
- Ask me first before installing new dependencies not listed above