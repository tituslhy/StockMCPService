---
name: render-ui-skill
description: Renders prefab UI for stock data.
---

## When to Use This
When the user asks for a chart, dashboard, visualization, or UI for any stock data.

## Steps
1. Always receive a clean Pandas DataFrame as input — never fetch data inside a render function.
2. Single ticker, short horizon → render a **data table** (last 10 rows).
3. Multiple tickers OR long horizon → render an **interactive dashboard** with charts.
4. Portfolio view → render three panels:
   - Amount invested (flat line or input value)
   - Amount gained (total ticker value - invested)
   - Yield % ((gained / invested) * 100)
   - Y-axis: dollars. X-axis: dates.
5. Always label axes clearly — include ticker name and date range in the chart title.
6. Always make charts interactive — use the Prefab UI charting primitives, not static images.

## Layout Rules
- Dashboard: sidebar for ticker selector, main panel for charts
- TA view: price chart on top, indicator panels below (RSI, Bollinger Bands separate panels)
- Portfolio view: summary card at top showing total yield %, charts below

## Example Signature
```python
def render_dashboard(data: dict[str, pd.DataFrame], mode: str = "dashboard") -> PrefabApp:
```

## Never Do This
- Never hardcode colors — use the Prefab UI theme tokens
- Never render without a title
- Never mix portfolio and TA views in the same dashboard