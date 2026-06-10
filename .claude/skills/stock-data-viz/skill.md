---
name: stock-data-viz
description: |
  Use this skill for ALL chart and dashboard rendering in this project.
  Triggers when:
  - Any tool needs to return a chart, dashboard, or visual for stock data
  - Rendering price history, technical indicators, or portfolio performance
  - Composing multi-panel dashboards with metrics + charts + tables
  Always read this skill before writing any prefab_ui chart code.
---

# Stock Data Visualization Skill

## Library reference

- Package: `prefab-ui` (pin version in pyproject.toml)
- Docs: https://prefab.prefect.io/docs/components/charts.md
- Full component index: https://prefab.prefect.io/docs/llms.txt

## FastMCP integration pattern

Every tool that returns a visual MUST use `app=True`:

```python
from fastmcp import FastMCP
from prefab_ui.components import (
    PrefabApp, Column, Row,
    LineChart, AreaChart, BarChart,
    ChartSeries, DataTable, DataTableColumn,
    Metric, Badge, Separator, Card
)

mcp = FastMCP("StockMCP")

@mcp.tool(app=True)
def my_chart_tool(...) -> PrefabApp:
    with PrefabApp() as app:
        with Column(gap=4, css_class="p-6"):
            ...
    return app
```

## ⚠️ No candlestick chart

Prefab does NOT have a `CandlestickChart` component. Do not hallucinate one.
For OHLCV data, use the patterns below.

---

## Chart patterns by use case

### 1. Single ticker price history (close price)

Use `LineChart` with `show_dots=False` for clean line.
Volume goes in a separate `BarChart` below, same x-axis key.

```python
# Prepare data: list of dicts from DataFrame
rows = df.reset_index().rename(columns={"Date": "date"})
data = rows[["date", "close", "volume"]].copy()
data["date"] = data["date"].dt.strftime("%b %d")
records = data.to_dict(orient="records")

with PrefabApp() as app:
    with Column(gap=4, css_class="p-6"):
        Metric(label=ticker, value=f"${records[-1]['close']:.2f}")
        LineChart(
            data=records,
            series=[ChartSeries(data_key="close", label="Close")],
            x_axis="date",
            show_legend=False,
            show_dots=False,
        )
        BarChart(
            data=records,
            series=[ChartSeries(data_key="volume", label="Volume")],
            x_axis="date",
            show_legend=False,
        )
return app
```

### 2. Multiple tickers (comparison)

Use `LineChart` with one `ChartSeries` per ticker.
Normalise to % return from first data point so tickers are comparable.

```python
# data rows: [{"date": "Jan 01", "AAPL": 0.0, "MSFT": 0.0, ...}, ...]
LineChart(
    data=records,
    series=[
        ChartSeries(data_key="AAPL", label="AAPL"),
        ChartSeries(data_key="MSFT", label="MSFT"),
    ],
    x_axis="date",
    show_legend=True,
    show_dots=False,
)
```

### 3. Technical indicators

**Bollinger Bands** — on-chart overlay: three LineChart series (upper, mid, lower)
in the same chart as close price. Use muted series colors for bands.

```python
LineChart(
    data=records,  # cols: date, close, bb_upper, bb_mid, bb_lower
    series=[
        ChartSeries(data_key="close",    label="Close"),
        ChartSeries(data_key="bb_upper", label="Upper Band"),
        ChartSeries(data_key="bb_mid",   label="Mid Band"),
        ChartSeries(data_key="bb_lower", label="Lower Band"),
    ],
    x_axis="date",
    show_legend=True,
    show_dots=False,
)
```

**RSI** — separate sub-panel below price chart. Always add reference lines at
70 (overbought) and 30 (oversold) as annotations in the title or a Metric badge,
since Prefab charts don't support drawn reference lines.

```python
with Column(gap=2):
    LineChart(
        data=records,
        series=[ChartSeries(data_key="close", label="Close")],
        x_axis="date", show_dots=False,
    )
    LineChart(
        data=records,
        series=[ChartSeries(data_key="rsi", label="RSI")],
        x_axis="date", show_dots=False, show_legend=False,
    )
    Row(gap=4):
        Badge("Overbought > 70", variant="destructive")
        Badge("Oversold < 30", variant="secondary")
```

**MACD** — separate sub-panel. Plot `macd` and `signal` as LineChart series,
`histogram` as BarChart below.

### 4. Portfolio performance

Use `AreaChart` for cumulative value over time.
Show two series: `invested` and `total_value`. The gap between them is the gain.

```python
AreaChart(
    data=records,  # cols: date, invested, total_value
    series=[
        ChartSeries(data_key="total_value", label="Total Value"),
        ChartSeries(data_key="invested",    label="Invested"),
    ],
    x_axis="date",
    show_legend=True,
)
```

Yield % as a `Metric` with trend indicator:

```python
yield_pct = ((total_value - invested) / invested) * 100
Metric(
    label="Yield",
    value=f"{yield_pct:.2f}%",
    trend="up" if yield_pct >= 0 else "down",
)
```

---

## Dashboard layout pattern

Always wrap multi-panel dashboards in `PrefabApp > Column > ...`.
Use `Row` for side-by-side metrics at the top. Use `Separator` between sections.

```python
with PrefabApp() as app:
    with Column(gap=4, css_class="p-6"):
        # Top metrics row
        with Row(gap=6):
            Metric(label="Last Price", value=f"${last:.2f}")
            Metric(label="Change",     value=f"{chg:+.2f}%",
                   trend="up" if chg >= 0 else "down")
            Metric(label="Volume",     value=f"{vol:,}")
        Separator()
        # Price chart
        LineChart(...)
        # Volume chart
        BarChart(...)
        Separator()
        # Data table
        DataTable(
            columns=[
                DataTableColumn(key="date",   header="Date",   sortable=True),
                DataTableColumn(key="open",   header="Open",   sortable=True),
                DataTableColumn(key="high",   header="High",   sortable=True),
                DataTableColumn(key="low",    header="Low",    sortable=True),
                DataTableColumn(key="close",  header="Close",  sortable=True),
                DataTableColumn(key="volume", header="Volume", sortable=True),
            ],
            rows=records,
            search=True,
        )
return app
```

## Data prep rules

- Always call `df.reset_index()` before converting to records — yfinance
  returns DataFrames with DatetimeIndex, not a column
- Format dates as strings before passing to charts:
  `df["date"] = df["date"].dt.strftime("%b %d")` for short horizon,
  `"%Y-%m-%d"` for long horizon
- Round floats to 2dp: `df = df.round(2)`
- Drop NaN rows before converting: `df = df.dropna()`
- Column names must be lowercase strings — yfinance returns mixed case;
  always `df.columns = df.columns.str.lower()` after fetching

## Imports cheatsheet

```python
from prefab_ui.components import (
    PrefabApp, Column, Row, Card,
    LineChart, AreaChart, BarChart, ScatterChart,
    ChartSeries,
    DataTable, DataTableColumn,
    Metric, Badge, Separator,
)
```

### 5. Price table with sparklines (10-interval history)

Use `DataTable` with an inline `Sparkline` in the price column.
Shows the mini trend at a glance without needing a full chart panel.

```python
from prefab_ui.components import Sparkline

# Build sparkline data: list of dicts with a single value key
def make_sparkline(prices: list[float]) -> Sparkline:
    return Sparkline(
        data=[{"v": p} for p in prices],
        data_key="v",
        trend=True,   # colors the line green/red based on first vs last
    )

# One row per ticker
rows = [
    {
        "ticker":  ticker,
        "latest":  f"${prices[-1]:.2f}",
        "change":  f"{((prices[-1] - prices[0]) / prices[0]) * 100:+.2f}%",
        "trend":   make_sparkline(prices),   # Sparkline component as cell value
        "high":    f"${max(prices):.2f}",
        "low":     f"${min(prices):.2f}",
    }
    for ticker, prices in ticker_price_map.items()
]

with PrefabApp() as app:
    with Column(gap=4, css_class="p-6"):
        DataTable(
            columns=[
                DataTableColumn(key="ticker", header="Ticker",  sortable=True),
                DataTableColumn(key="latest", header="Price",   sortable=True),
                DataTableColumn(key="change", header="Change",  sortable=True),
                DataTableColumn(key="trend",  header="10 Intervals"),
                DataTableColumn(key="high",   header="High",    sortable=True),
                DataTableColumn(key="low",    header="Low",     sortable=True),
            ],
            rows=rows,
            search=True,
        )
return app
```

**Data prep for sparklines:**

```python
# From a yfinance DataFrame, extract close prices as a plain list
def extract_close_prices(df: pd.DataFrame, n: int = 10) -> list[float]:
    df.columns = df.columns.str.lower()
    return df["close"].dropna().tail(n).round(2).tolist()
```

**Trend coloring note:** `trend=True` on `Sparkline` colors the line
green if `last >= first`, red if `last < first`. This is automatic —
do not try to pass color manually.
