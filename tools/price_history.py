"""Price history table and chart dashboard tool.

Exposes a single FastMCP app-tool, `price_history`, that renders a price
history dashboard (key metrics, a close-price line chart, a volume bar
chart, and a sortable/searchable OHLCV table) for a given ticker and date
range.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

import pandas as pd
from fastmcp import FastMCP
from prefab_ui import PrefabApp
from prefab_ui.components import (
    Badge,
    Card,
    Column,
    DataTable,
    DataTableColumn,
    Metric,
    Row,
    Separator,
    Text,
)
from prefab_ui.components.charts import BarChart, ChartSeries, LineChart

from tools._data import StockDataError, TickerNotFoundError, fetch_ohlcv

#: Default number of days to look back when no `start` date is provided.
DEFAULT_LOOKBACK_DAYS: int = 90

#: Maximum span (in days) for which dates are rendered as "%b %d" instead
#: of the full "%Y-%m-%d" form.
SHORT_HORIZON_DAYS: int = 180

price_history_mcp: FastMCP = FastMCP("PriceHistory")


def _resolve_date_range(start: str | None, end: str | None) -> tuple[date, date]:
    """Resolve the effective `(start_date, end_date)` range.

    Args:
        start: Optional ISO "YYYY-MM-DD" start date. If `None`, defaults to
            `end_date - timedelta(days=DEFAULT_LOOKBACK_DAYS)`.
        end: Optional ISO "YYYY-MM-DD" end date. If `None`, defaults to
            today (UTC).

    Returns:
        A tuple of `(start_date, end_date)` as `date` objects.

    Raises:
        ValueError: If `start` or `end` is not a valid ISO "YYYY-MM-DD"
            date string. Propagates from `date.fromisoformat`.
    """
    today = datetime.now(timezone.utc).date()
    end_date = date.fromisoformat(end) if end else today
    start_date = (
        date.fromisoformat(start)
        if start
        else end_date - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    )
    return start_date, end_date


def _prepare_records(
    df: pd.DataFrame, start_date: date, end_date: date
) -> list[dict[str, Any]]:
    """Convert a raw OHLCV DataFrame into chart/table-ready records.

    Args:
        df: OHLCV DataFrame indexed by date/datetime, as returned by
            `fetch_ohlcv`.
        start_date: Start of the requested date range (used to choose the
            date display format).
        end_date: End of the requested date range (used to choose the date
            display format).

    Returns:
        A list of row dicts with columns `date`, `open`, `high`, `low`,
        `close`, `volume`, ready to feed directly into Prefab charts and
        `DataTable`.

    Raises:
        TickerNotFoundError: If no rows remain after dropping rows with
            missing values.
    """
    df = df.reset_index()
    df = df.rename(columns={df.columns[0]: "date"})
    df.columns = df.columns.str.lower()

    span_days = (end_date - start_date).days
    fmt = "%b %d" if span_days <= SHORT_HORIZON_DAYS else "%Y-%m-%d"
    df["date"] = pd.to_datetime(df["date"]).dt.strftime(fmt)

    for col in ("open", "high", "low", "close"):
        df[col] = df[col].round(2)

    df = df.dropna()

    if df.empty:
        raise TickerNotFoundError("No price data available for the requested range.")

    df["volume"] = df["volume"].round(0).astype("int64")

    return df.to_dict(orient="records")


def _render_error_app(message: str) -> PrefabApp:
    """Render an error-state Prefab app.

    Args:
        message: Human-readable error message to display.

    Returns:
        A `PrefabApp` showing a destructive badge and the error message.
    """
    with PrefabApp() as app:
        with Column(gap=4, css_class="p-6"):
            with Card(css_class="p-6"):
                with Column(gap=2):
                    Badge("Unable to load price history", variant="destructive")
                    Text(message)
    return app


@price_history_mcp.tool(app=True)
def price_history(
    ticker: str, start: str | None = None, end: str | None = None
) -> PrefabApp:
    """Render a price history dashboard for a ticker.

    Args:
        ticker: Ticker symbol to fetch, e.g. "AAPL".
        start: Optional ISO "YYYY-MM-DD" start date. Defaults to
            `DEFAULT_LOOKBACK_DAYS` days before `end`.
        end: Optional ISO "YYYY-MM-DD" end date. Defaults to today (UTC).

    Returns:
        A `PrefabApp` showing summary metrics, a close-price line chart, a
        volume bar chart, and a sortable/searchable OHLCV table. If the
        request fails, an error-state app is returned instead.
    """
    try:
        start_date, end_date = _resolve_date_range(start, end)
        df = fetch_ohlcv(ticker, start=start_date, end=end_date, interval="1d")
        records = _prepare_records(df, start_date, end_date)
    except StockDataError as exc:
        return _render_error_app(exc.user_message)
    except ValueError as exc:
        return _render_error_app(f"Invalid date: {exc}. Use YYYY-MM-DD format.")

    latest_close = float(records[-1]["close"])
    first_close = float(records[0]["close"])
    latest_volume = int(records[-1]["volume"])

    if first_close != 0.0:
        pct_change = (latest_close - first_close) / first_close * 100.0
    else:
        pct_change = 0.0

    trend: Literal["up", "down", "neutral"]
    if pct_change > 0:
        trend = "up"
    elif pct_change < 0:
        trend = "down"
    else:
        trend = "neutral"

    with PrefabApp() as app:
        with Column(gap=4, css_class="p-6"):
            with Row(gap=6):
                Metric(label=ticker, value=f"${latest_close:.2f}")
                Metric(
                    label="Change",
                    value=f"{pct_change:+.2f}%",
                    trend=trend,
                )
                Metric(label="Volume", value=f"{latest_volume:,}")
            Separator()
            LineChart(
                data=records,
                series=[ChartSeries(data_key="close", label="Close")],  # type: ignore[call-arg]
                x_axis="date",  # type: ignore[call-arg]
                show_legend=False,  # type: ignore[call-arg]
                show_dots=False,  # type: ignore[call-arg]
            )
            BarChart(
                data=records,
                series=[ChartSeries(data_key="volume", label="Volume")],  # type: ignore[call-arg]
                x_axis="date",  # type: ignore[call-arg]
                show_legend=False,  # type: ignore[call-arg]
            )
            Separator()
            DataTable(
                columns=[
                    DataTableColumn(key="date", header="Date", sortable=True),
                    DataTableColumn(key="open", header="Open", sortable=True),
                    DataTableColumn(key="high", header="High", sortable=True),
                    DataTableColumn(key="low", header="Low", sortable=True),
                    DataTableColumn(key="close", header="Close", sortable=True),
                    DataTableColumn(key="volume", header="Volume", sortable=True),
                ],
                rows=records,  # type: ignore[arg-type]
                search=True,
                paginated=True,
            )

    return app
