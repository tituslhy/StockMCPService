---
name: fetch-data-skill
description: Fetch stock price data for any ticker.
---

## When to Use This
When the user asks to fetch, pull, get, or retrieve stock price data for any ticker.

## Steps
1. Always use `yfinance` — never scrape Yahoo Finance directly.
2. Validate the ticker symbol first — if it returns empty data, raise a clear error: `"Ticker {symbol} not found or delisted."`
3. Use the `period` and `interval` parameters explicitly — never rely on yfinance defaults.
4. Always return the last 10 rows unless the user specifies otherwise.
5. Return a clean Pandas DataFrame with columns: `Date`, `Open`, `High`, `Low`, `Close`, `Volume`.
6. Strip timezone info from the index — use `.tz_localize(None)`.
7. Always reset the index so `Date` is a column, not the index.

## Example Signature
```python
def fetch_ticker_data(symbol: str, interval: str = "1d", period: str = "3mo") -> pd.DataFrame:
```

## Never Do This
- Never use `auto_adjust=False` — keep it True (default)
- Never return raw yfinance objects — always convert to DataFrame
- Never swallow exceptions silently — always surface errors to the MCP caller