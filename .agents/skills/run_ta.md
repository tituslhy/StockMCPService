---
name: run-ta-skill
description: Runs technical analysis on stock ticker data and returns the results.
---

## When to Use This
When the user asks for technical analysis, indicators, signals, or TA on any ticker.

## Steps
1. Always run `fetch_data` skill first to get clean DataFrame before doing any TA.
2. Use the `ta` library — import as `import ta`.
3. Always add indicators as new columns on the existing DataFrame — never create a separate DataFrame.
4. Use these standard indicators unless the user specifies otherwise:
   - **Trend**: SMA 20, EMA 20 — `ta.trend.sma_indicator()`, `ta.trend.ema_indicator()`
   - **Momentum**: RSI 14 — `ta.momentum.rsi()`
   - **Volatility**: Bollinger Bands — `ta.volatility.BollingerBands()`
   - **Volume**: OBV — `ta.volume.on_balance_volume()`
5. Drop rows with NaN values AFTER adding all indicators — `df.dropna(inplace=True)`.
6. Return the enriched DataFrame with all original columns + indicator columns.

## Example Signature
```python
def run_technical_analysis(df: pd.DataFrame) -> pd.DataFrame:
```

## Never Do This
- Never run TA on fewer than 30 rows — raise an error: `"Not enough data for reliable TA. Need at least 30 rows."`
- Never rename the Close column — `ta` expects it as `Close`
- Never return just the indicator columns — always return the full DataFrame
