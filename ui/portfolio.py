"""Interactive portfolio tracker app.

Exposes a `FastMCPApp` ("Portfolio") that lets a user add/remove holdings,
search for tickers, and view live market value, P&L, and allocation. Holdings
are held **in memory only** for the lifetime of the process -- there is no
persistence by design, and this module is not thread-safe (a single shared
`dict` is mutated directly by backend tool calls).
"""

from __future__ import annotations

from typing import TypedDict

from fastmcp import FastMCPApp
from prefab_ui import PrefabApp
from prefab_ui.actions import SetState, ShowToast
from prefab_ui.actions.mcp import CallTool
from prefab_ui.components import (
    Badge,
    Button,
    Card,
    Column,
    Input,
    Metric,
    Row,
    Separator,
    Text,
)
from prefab_ui.components.charts import BarChart, ChartSeries
from prefab_ui.components.control_flow import Else, ForEach, If
from prefab_ui.rx import RESULT, STATE

from tools._data import InvalidTickerError, StockDataError, fetch_ohlcv, validate_ticker


class Holding(TypedDict):
    """A single portfolio holding, as stored in `_HOLDINGS`."""

    symbol: str
    quantity: float
    cost_basis: float


class HoldingView(TypedDict):
    """A holding enriched with live price/valuation data for rendering."""

    symbol: str
    quantity: float
    cost_basis: float
    latest_price: float | None
    market_value: float | None
    cost: float
    pnl: float | None
    pnl_pct: float | None
    allocation_pct: float | None
    price_error: str | None


class PortfolioSnapshot(TypedDict):
    """A full portfolio snapshot, returned by `_portfolio_snapshot`."""

    holdings: list[HoldingView]
    total_market_value: float
    total_cost: float
    total_pnl: float
    total_pnl_pct: float | None


# --------------------------------------------------------------------------- #
# Module state
# --------------------------------------------------------------------------- #

#: In-memory holdings, keyed by normalized ticker symbol.
#:
#: NOTE: This is module-level, in-memory, and NOT thread-safe. It is
#: intentionally non-persistent -- holdings reset whenever the process
#: restarts. This is by design for a single-session demo app.
_HOLDINGS: dict[str, Holding] = {}


def reset_portfolio() -> None:
    """Clear all holdings.

    Test helper only -- not exposed as an `@app.tool()`.
    """
    _HOLDINGS.clear()


portfolio_app: FastMCPApp = FastMCPApp("Portfolio")


# --------------------------------------------------------------------------- #
# Pricing helpers
# --------------------------------------------------------------------------- #


def _fetch_latest_price(symbol: str) -> tuple[float | None, str | None]:
    """Fetch the latest close price for a normalized ticker symbol.

    Args:
        symbol: A normalized (validated) ticker symbol, e.g. "AAPL".

    Returns:
        A `(price, error_message)` tuple. On success, `(price, None)` where
        `price` is the latest available close as a native `float`. On any
        `StockDataError`, returns `(None, exc.user_message)`. If no
        non-NaN close price is available, returns
        `(None, "No recent price data available.")`. This function NEVER
        raises.
    """
    try:
        df = fetch_ohlcv(symbol, period="5d", interval="1d")
    except StockDataError as exc:
        return None, exc.user_message

    closes = df["close"].dropna()
    if closes.empty:
        return None, "No recent price data available."
    return float(closes.iloc[-1]), None


def _portfolio_snapshot() -> PortfolioSnapshot:
    """Compute a full portfolio snapshot from `_HOLDINGS`.

    For each holding, fetches the latest price (best-effort) and derives
    market value, cost, P&L, P&L %, and allocation %. Allocation is computed
    over the total market value of holdings for which a price was
    successfully fetched.

    Returns:
        A JSON-safe `PortfolioSnapshot`. All numeric values are native
        `float`s rounded to 2 decimal places. If `_HOLDINGS` is empty,
        `holdings` is `[]`, all totals are `0.0`, and `total_pnl_pct` is
        `None`.
    """
    views: list[HoldingView] = []

    for symbol, holding in _HOLDINGS.items():
        quantity = holding["quantity"]
        cost_basis = holding["cost_basis"]
        cost = quantity * cost_basis

        latest_price, price_error = _fetch_latest_price(symbol)

        market_value: float | None
        pnl: float | None
        pnl_pct: float | None
        if latest_price is not None:
            market_value = quantity * latest_price
            pnl = market_value - cost
            pnl_pct = (pnl / cost * 100.0) if cost != 0.0 else None
        else:
            market_value = None
            pnl = None
            pnl_pct = None

        views.append(
            HoldingView(
                symbol=symbol,
                quantity=round(float(quantity), 2),
                cost_basis=round(float(cost_basis), 2),
                latest_price=round(float(latest_price), 2)
                if latest_price is not None
                else None,
                market_value=round(float(market_value), 2)
                if market_value is not None
                else None,
                cost=round(float(cost), 2),
                pnl=round(float(pnl), 2) if pnl is not None else None,
                pnl_pct=round(float(pnl_pct), 2) if pnl_pct is not None else None,
                allocation_pct=None,
                price_error=price_error,
            )
        )

    total_market_value = sum(
        view["market_value"] for view in views if view["market_value"] is not None
    )
    total_cost = sum(view["cost"] for view in views)
    total_pnl = total_market_value - total_cost
    total_pnl_pct: float | None
    total_pnl_pct = (total_pnl / total_cost * 100.0) if total_cost != 0.0 else None

    # Allocation % is computed over priced holdings only.
    if total_market_value != 0.0:
        for view in views:
            if view["market_value"] is not None:
                view["allocation_pct"] = round(
                    view["market_value"] / total_market_value * 100.0, 2
                )

    return PortfolioSnapshot(
        holdings=views,
        total_market_value=round(float(total_market_value), 2),
        total_cost=round(float(total_cost), 2),
        total_pnl=round(float(total_pnl), 2),
        total_pnl_pct=round(float(total_pnl_pct), 2)
        if total_pnl_pct is not None
        else None,
    )


# --------------------------------------------------------------------------- #
# Backend tools (UI-only)
# --------------------------------------------------------------------------- #


@portfolio_app.tool()
def add_holding(symbol: str, quantity: float, cost_basis: float) -> PortfolioSnapshot:
    """Add (or top up) a holding and return the refreshed portfolio snapshot.

    If `symbol` already exists in the portfolio, the existing and new
    quantities/cost bases are merged using a weighted-average cost basis.

    Args:
        symbol: Ticker symbol, e.g. "AAPL". Normalized via `validate_ticker`.
        quantity: Number of shares to add. Must be `> 0`.
        cost_basis: Per-share cost basis for this purchase. Must be `>= 0`.

    Returns:
        The refreshed `PortfolioSnapshot`.

    Raises:
        InvalidTickerError: If `symbol` has an invalid format.
        ValueError: If `quantity <= 0` or `cost_basis < 0`.
    """
    normalized = validate_ticker(symbol)

    if quantity <= 0:
        raise ValueError("Quantity must be greater than zero.")
    if cost_basis < 0:
        raise ValueError("Cost basis cannot be negative.")

    quantity = float(quantity)
    cost_basis = float(cost_basis)

    existing = _HOLDINGS.get(normalized)
    if existing is not None:
        old_quantity = existing["quantity"]
        old_cost_basis = existing["cost_basis"]
        new_quantity = old_quantity + quantity
        new_cost_basis = (
            (old_quantity * old_cost_basis) + (quantity * cost_basis)
        ) / new_quantity
        _HOLDINGS[normalized] = Holding(
            symbol=normalized,
            quantity=float(new_quantity),
            cost_basis=float(new_cost_basis),
        )
    else:
        _HOLDINGS[normalized] = Holding(
            symbol=normalized, quantity=quantity, cost_basis=cost_basis
        )

    return _portfolio_snapshot()


@portfolio_app.tool()
def remove_holding(symbol: str) -> PortfolioSnapshot:
    """Remove a holding (idempotent) and return the refreshed snapshot.

    Args:
        symbol: Ticker symbol to remove. Normalized via `validate_ticker`.

    Returns:
        The refreshed `PortfolioSnapshot`. If `symbol` is not in the
        portfolio, this is a no-op (no error is raised).

    Raises:
        InvalidTickerError: If `symbol` has an invalid format.
    """
    normalized = validate_ticker(symbol)
    _HOLDINGS.pop(normalized, None)
    return _portfolio_snapshot()


@portfolio_app.tool()
def search_tickers(query: str) -> list[dict[str, str]]:
    """Search for a ticker symbol and report whether it has price data.

    Args:
        query: Raw ticker query string, e.g. "aapl". Leading/trailing
            whitespace is stripped.

    Returns:
        A list with at most one result dict of the form
        `{"symbol": str, "status": "found" | "not_found", "message": str}`.
        Returns `[]` if `query` is empty/whitespace-only. This function
        NEVER raises -- invalid tickers or fetch failures are reported as
        `"not_found"` results.
    """
    stripped = query.strip()
    if not stripped:
        return []

    try:
        normalized = validate_ticker(stripped)
        fetch_ohlcv(normalized, period="5d")
    except InvalidTickerError as exc:
        return [
            {"symbol": stripped, "status": "not_found", "message": exc.user_message}
        ]
    except StockDataError as exc:
        return [
            {
                "symbol": stripped.upper(),
                "status": "not_found",
                "message": exc.user_message,
            }
        ]
    except ValueError as exc:
        return [{"symbol": stripped, "status": "not_found", "message": str(exc)}]

    return [
        {
            "symbol": normalized,
            "status": "found",
            "message": f"'{normalized}' has price data available.",
        }
    ]


# --------------------------------------------------------------------------- #
# UI entry point
# --------------------------------------------------------------------------- #


@portfolio_app.ui()
def portfolio_dashboard() -> PrefabApp:
    """Render the interactive portfolio tracker dashboard.

    Returns:
        A `PrefabApp` with an add-holding form, an optional ticker search,
        summary P&L metrics, a holdings list (with per-row remove buttons),
        and an allocation bar chart. Renders correctly for both empty and
        populated portfolios.
    """
    snapshot = _portfolio_snapshot()

    with PrefabApp(state={"portfolio": snapshot, "search_results": []}) as app:
        with Column(gap=4, css_class="p-6"):
            # ----------------------------------------------------------- #
            # Add holding form
            # ----------------------------------------------------------- #
            with Row(gap=2):
                symbol_in = Input(  # type: ignore[call-arg]
                    name="symbol_field",
                    placeholder="Ticker",
                    input_type="text",  # type: ignore[call-arg]
                )
                qty_in = Input(  # type: ignore[call-arg]
                    name="qty_field",
                    placeholder="Qty",
                    input_type="number",  # type: ignore[call-arg]
                    min=0,
                )
                cost_in = Input(  # type: ignore[call-arg]
                    name="cost_field",
                    placeholder="Cost basis",
                    input_type="number",  # type: ignore[call-arg]
                    min=0,
                )
                Button(
                    "Add",
                    on_click=CallTool(
                        add_holding,
                        arguments={
                            "symbol": symbol_in.rx,
                            "quantity": qty_in.rx,
                            "cost_basis": cost_in.rx,
                        },
                        on_success=SetState("portfolio", RESULT),
                        on_error=ShowToast("{{ $error }}", variant="error"),  # type: ignore[call-arg]
                    ),
                )

            # ----------------------------------------------------------- #
            # Ticker search
            # ----------------------------------------------------------- #
            with Row(gap=2):
                search_in = Input(  # type: ignore[call-arg]
                    name="search_field",
                    placeholder="Search ticker",
                    input_type="text",  # type: ignore[call-arg]
                )
                Button(
                    "Search",
                    on_click=CallTool(
                        search_tickers,
                        arguments={"query": search_in.rx},
                        on_success=SetState("search_results", RESULT),
                        on_error=ShowToast("{{ $error }}", variant="error"),  # type: ignore[call-arg]
                    ),
                )
            with ForEach("search_results") as result:
                Badge(result.symbol)  # type: ignore[attr-defined,call-overload]

            Separator()

            # ----------------------------------------------------------- #
            # Summary metrics
            # ----------------------------------------------------------- #
            with Row(gap=6):
                Metric(
                    label="Total Value",
                    value=STATE.portfolio.total_market_value.currency(),  # type: ignore[call-arg]
                )
                Metric(
                    label="Total Cost",
                    value=STATE.portfolio.total_cost.currency(),  # type: ignore[call-arg]
                )
                Metric(
                    label="Total P&L",
                    value=STATE.portfolio.total_pnl.currency(),  # type: ignore[call-arg]
                    trend="up" if snapshot["total_pnl"] >= 0 else "down",
                )
                Metric(
                    label="Total P&L %",
                    value=STATE.portfolio.total_pnl_pct.percent(),  # type: ignore[call-arg]
                )

            Separator()

            # ----------------------------------------------------------- #
            # Holdings list
            # ----------------------------------------------------------- #
            with If(STATE.portfolio.holdings.length() == 0):
                Text("No holdings yet. Add a ticker above to get started.")
            with Else():
                with ForEach("portfolio.holdings") as holding:
                    with Card(css_class="p-4"):
                        with Row(gap=4):
                            Text(holding.symbol)  # type: ignore[attr-defined,arg-type]
                            Text("Qty: " + holding.quantity)  # type: ignore[attr-defined,arg-type]
                            Text(
                                "Value: "  # type: ignore[attr-defined,arg-type]
                                + holding.market_value.currency()
                            )
                            Text("P&L: " + holding.pnl.currency())  # type: ignore[attr-defined,arg-type]
                            Text("P&L %: " + holding.pnl_pct.percent())  # type: ignore[attr-defined,arg-type]
                            Text(
                                "Allocation: "  # type: ignore[attr-defined,arg-type]
                                + holding.allocation_pct.percent()
                            )
                            with If(holding.price_error != None):  # noqa: E711  # type: ignore[attr-defined]
                                Badge(holding.price_error, variant="destructive")  # type: ignore[attr-defined,call-overload]
                            Button(
                                "Remove",
                                variant="destructive",
                                on_click=CallTool(
                                    remove_holding,
                                    arguments={"symbol": holding.symbol},  # type: ignore[attr-defined]
                                    on_success=SetState("portfolio", RESULT),
                                ),
                            )

            Separator()

            # ----------------------------------------------------------- #
            # Allocation chart
            # ----------------------------------------------------------- #
            allocation_data = [
                {
                    "symbol": view["symbol"],
                    "allocation_pct": view["allocation_pct"] or 0.0,
                }
                for view in snapshot["holdings"]
            ]
            BarChart(
                data=allocation_data,
                series=[ChartSeries(data_key="allocation_pct", label="Allocation %")],  # type: ignore[call-arg]
                x_axis="symbol",  # type: ignore[call-arg]
                show_legend=False,  # type: ignore[call-arg]
            )

    return app
