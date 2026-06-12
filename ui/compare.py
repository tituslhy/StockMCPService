"""Interactive multi-ticker compare dashboard app.

Exposes a `FastMCPApp` ("Compare") that lets a user build a set of ticker
symbols, search for additional tickers, and view a normalized performance
chart, a return-correlation matrix, and per-ticker key stats over a fixed
lookback window. The compared-ticker set is held **in memory only** for the
lifetime of the process -- there is no persistence by design, and this
module is not thread-safe (a single shared `list` is mutated directly by
backend tool calls).
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Literal, TypedDict

import numpy as np
import pandas as pd
from fastmcp import FastMCPApp
from prefab_ui import PrefabApp
from prefab_ui.actions import SetState, ShowToast
from prefab_ui.actions.mcp import CallTool
from prefab_ui.components import (
    Badge,
    Button,
    Column,
    DataTable,
    DataTableColumn,
    Input,
    Row,
    Separator,
    Text,
)
from prefab_ui.components.charts import ChartSeries, LineChart
from prefab_ui.components.control_flow import ForEach, If
from prefab_ui.rx import RESULT, STATE

from tools._data import (
    InvalidTickerError,
    NetworkError,
    StockDataError,
    TickerNotFoundError,
    fetch_ohlcv,
    validate_ticker,
)

__all__ = [
    "NetworkError",
    "InvalidTickerError",
    "TickerNotFoundError",
]


class FetchFailure(TypedDict):
    """A per-ticker fetch failure, as recorded in `CompareSnapshot.failed`."""

    symbol: str
    message: str


class TickerStats(TypedDict):
    """Summary statistics for a single ticker over the compare window."""

    symbol: str
    latest_close: float
    period_return_pct: float
    annualized_volatility_pct: float
    max_drawdown_pct: float
    best_day_pct: float
    worst_day_pct: float


class CompareSnapshot(TypedDict):
    """A full multi-ticker compare snapshot, returned by `_compare_snapshot`."""

    symbols: list[str]
    failed: list[FetchFailure]
    performance: list[dict[str, float | str]]
    performance_series: list[str]
    correlation_matrix: list[dict[str, float | str]]
    correlation_columns: list[str]
    stats: list[TickerStats]
    correlation_note: str | None
    status: Literal["empty", "insufficient", "ok"]
    message: str | None


# --------------------------------------------------------------------------- #
# Module state
# --------------------------------------------------------------------------- #

#: In-memory ordered set of normalized ticker symbols to compare.
#:
#: NOTE: This is module-level, in-memory, and NOT thread-safe. It is
#: intentionally non-persistent -- the compare set resets whenever the
#: process restarts. This is by design for a single-session demo app.
_COMPARE_SET: list[str] = []

#: Default lookback window (in days) used when computing the compare
#: snapshot. The effective range is always resolved at call-time relative
#: to "today" (UTC) -- never a literal date.
_DEFAULT_LOOKBACK_DAYS: int = 180

#: Maximum span (in days) for which performance dates are rendered as
#: "%b %d" instead of the full "%Y-%m-%d" form.
_SHORT_HORIZON_DAYS: int = 180


def reset_compare() -> None:
    """Clear the compared-ticker set.

    Test helper only -- not exposed as an `@app.tool()`.
    """
    _COMPARE_SET.clear()


compare_app: FastMCPApp = FastMCPApp("Compare")


# --------------------------------------------------------------------------- #
# Data helpers
# --------------------------------------------------------------------------- #


def _resolve_default_range() -> tuple[date, date]:
    """Resolve the default `(start_date, end_date)` compare window.

    Returns:
        A tuple `(start_date, end_date)` where `end_date` is "today" (UTC)
        and `start_date` is `end_date - timedelta(days=_DEFAULT_LOOKBACK_DAYS)`.
        Computed at call-time -- never a literal/hardcoded date.
    """
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=_DEFAULT_LOOKBACK_DAYS)
    return start_date, end_date


def _fetch_close_series(symbol: str, start: date, end: date) -> pd.Series:
    """Fetch a non-NaN close-price series for a single ticker.

    Args:
        symbol: A normalized (validated) ticker symbol, e.g. "AAPL".
        start: Start date of the requested range.
        end: End date of the requested range.

    Returns:
        A `pandas.Series` of close prices, indexed by date, with NaN rows
        dropped.

    Raises:
        StockDataError: Propagated from `fetch_ohlcv` on any fetch failure.
        TickerNotFoundError: If no non-NaN close prices remain after
            dropping NaNs.
    """
    df = fetch_ohlcv(symbol, start=start, end=end, interval="1d")
    closes = df["close"].dropna()
    if closes.empty:
        raise TickerNotFoundError(f"No price data for {symbol}.")
    return closes


def _normalize_performance(
    aligned_closes: dict[str, pd.Series],
    common_index: pd.Index,
    start_date: date,
    end_date: date,
) -> list[dict[str, float | str]]:
    """Build normalized (% return from start) performance records.

    Args:
        aligned_closes: Mapping of normalized ticker symbol to a close-price
            `Series`, all reindexed to `common_index`.
        common_index: The shared `DatetimeIndex` shared by all series.
        start_date: Start date of the compare window (used for date
            formatting only).
        end_date: End date of the compare window (used for date formatting
            only).

    Returns:
        A list of row dicts of the form
        `{"date": str, SYM1: float, SYM2: float, ...}`, one per date in
        `common_index`. Each ticker's value is normalized to
        `(close_t / close_0 - 1) * 100`, rounded to 2 decimal places. If a
        ticker's first close (`close_0`) is `0`, all of its values are
        `0.0`. Contains no `NaN` values.
    """
    span_days = (end_date - start_date).days
    date_fmt = "%b %d" if span_days <= _SHORT_HORIZON_DAYS else "%Y-%m-%d"
    formatted_dates = pd.to_datetime(common_index).strftime(date_fmt)

    first_closes: dict[str, float] = {}
    for symbol, series in aligned_closes.items():
        first = float(series.iloc[0])
        first_closes[symbol] = first if math.isfinite(first) else 0.0

    records: list[dict[str, float | str]] = []
    for i, formatted_date in enumerate(formatted_dates):
        record: dict[str, float | str] = {"date": str(formatted_date)}
        for symbol, series in aligned_closes.items():
            close_0 = first_closes[symbol]
            if close_0 == 0.0:
                normalized = 0.0
            else:
                close_t = float(series.iloc[i])
                if not math.isfinite(close_t):
                    normalized = 0.0
                else:
                    normalized = (close_t / close_0 - 1.0) * 100.0
            if not math.isfinite(normalized):
                normalized = 0.0
            record[symbol] = round(normalized, 2)
        records.append(record)

    return records


def _pairwise_correlation(
    aligned_closes: dict[str, pd.Series],
) -> tuple[list[dict[str, float | str]], list[str], str | None]:
    """Build a pairwise return-correlation matrix across compared tickers.

    Args:
        aligned_closes: Mapping of normalized ticker symbol to a close-price
            `Series`, all reindexed to a shared (common) index.

    Returns:
        A tuple `(matrix, columns, note)`:
            - `matrix`: A list of row dicts, one per ticker, of the form
              `{"ticker": SYM, SYM1: corr, SYM2: corr, ...}`. The diagonal
              is always `1.0`. Off-diagonal values are the Pearson
              correlation of daily returns, rounded to 2 decimal places.
              If a correlation is `NaN`/non-finite or fewer than 2 paired
              return observations are available, `0.0` is used instead.
            - `columns`: The list of ticker symbols (in `aligned_closes`
              order).
            - `note`: `None` if at least 3 common dates are available,
              otherwise a human-readable note explaining that there isn't
              enough overlapping data.
    """
    symbols = list(aligned_closes.keys())
    common_dates = len(next(iter(aligned_closes.values()))) if aligned_closes else 0

    note: str | None = None
    if common_dates < 3:
        note = "Not enough overlapping data to compute correlation."

    returns: dict[str, pd.Series] = {
        symbol: series.pct_change().dropna()
        for symbol, series in aligned_closes.items()
    }

    matrix: list[dict[str, float | str]] = []
    for row_symbol in symbols:
        row: dict[str, float | str] = {"ticker": row_symbol}
        for col_symbol in symbols:
            if row_symbol == col_symbol:
                corr = 1.0
            else:
                row_returns = returns[row_symbol]
                col_returns = returns[col_symbol]
                paired = pd.concat(
                    [row_returns, col_returns], axis=1, join="inner"
                ).dropna()
                if len(paired) < 2:
                    corr = 0.0
                else:
                    # Suppress numpy divide/invalid warnings from np.corrcoef
                    # when dealing with zero-variance series that produce NaN.
                    with np.errstate(invalid="ignore", divide="ignore"):
                        raw_corr = paired.iloc[:, 0].corr(paired.iloc[:, 1])
                    corr = float(raw_corr) if pd.notna(raw_corr) else 0.0
            if not math.isfinite(corr):
                corr = 0.0
            row[col_symbol] = round(corr, 2)
        matrix.append(row)

    return matrix, symbols, note


def _ticker_stats(symbol: str, close: pd.Series) -> TickerStats:
    """Compute summary statistics for a single ticker's close-price series.

    Args:
        symbol: The normalized ticker symbol.
        close: A close-price `Series` (reindexed to the common compare
            window).

    Returns:
        A JSON-safe `TickerStats` dict. All numeric fields are native
        `float`s rounded to 2 decimal places, with `NaN`/non-finite values
        guarded to `0.0`.
    """
    returns = close.pct_change().dropna()

    latest_close = float(close.iloc[-1])

    first_close = float(close.iloc[0])
    if first_close != 0.0:
        period_return_pct = (float(close.iloc[-1]) / first_close - 1.0) * 100.0
    else:
        period_return_pct = 0.0

    if len(returns) >= 2:
        annualized_volatility_pct = float(returns.std(ddof=1)) * math.sqrt(252) * 100.0
    else:
        annualized_volatility_pct = 0.0

    if len(close) == 1:
        max_drawdown_pct = 0.0
    else:
        drawdown = (close / close.cummax()) - 1.0
        max_drawdown_pct = float(drawdown.min()) * 100.0

    if returns.empty:
        best_day_pct = 0.0
        worst_day_pct = 0.0
    else:
        best_day_pct = float(returns.max()) * 100.0
        worst_day_pct = float(returns.min()) * 100.0

    values = {
        "latest_close": latest_close,
        "period_return_pct": period_return_pct,
        "annualized_volatility_pct": annualized_volatility_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "best_day_pct": best_day_pct,
        "worst_day_pct": worst_day_pct,
    }
    for key, value in values.items():
        if pd.isna(value) or not math.isfinite(value):
            values[key] = 0.0
        values[key] = round(values[key], 2)

    return TickerStats(
        symbol=symbol,
        latest_close=values["latest_close"],
        period_return_pct=values["period_return_pct"],
        annualized_volatility_pct=values["annualized_volatility_pct"],
        max_drawdown_pct=values["max_drawdown_pct"],
        best_day_pct=values["best_day_pct"],
        worst_day_pct=values["worst_day_pct"],
    )


def _compare_snapshot() -> CompareSnapshot:
    """Compute a full multi-ticker compare snapshot from `_COMPARE_SET`.

    Fetches close-price history for each compared ticker over the default
    lookback window, aligns them on their common dates, and computes
    normalized performance, return correlation, and per-ticker stats.

    Returns:
        A JSON-safe `CompareSnapshot`. All numeric values are native
        `float`s rounded to 2 decimal places with no `NaN`/`inf` values.

        - `status="empty"` if fewer than 2 tickers are in the compare set.
        - `status="insufficient"` if fewer than 2 tickers have valid price
          data, or if the valid tickers have fewer than 2 overlapping
          dates.
        - `status="ok"` otherwise, with `performance`, `correlation_matrix`,
          and `stats` fully populated.
    """
    symbols = list(_COMPARE_SET)

    if len(symbols) < 2:
        return CompareSnapshot(
            symbols=symbols,
            failed=[],
            performance=[],
            performance_series=[],
            correlation_matrix=[],
            correlation_columns=[],
            stats=[],
            correlation_note=None,
            status="empty",
            message="Add at least 2 tickers to compare.",
        )

    start_date, end_date = _resolve_default_range()

    successes: dict[str, pd.Series] = {}
    failed: list[FetchFailure] = []

    for symbol in symbols:
        try:
            successes[symbol] = _fetch_close_series(symbol, start_date, end_date)
        except StockDataError as exc:
            failed.append(FetchFailure(symbol=symbol, message=exc.user_message))

    if len(successes) < 2:
        return CompareSnapshot(
            symbols=symbols,
            failed=failed,
            performance=[],
            performance_series=[],
            correlation_matrix=[],
            correlation_columns=[],
            stats=[],
            correlation_note=None,
            status="insufficient",
            message="Not enough valid tickers with price data to compare.",
        )

    common_index: pd.Index | None = None
    for series in successes.values():
        if common_index is None:
            common_index = series.index
        else:
            common_index = common_index.intersection(series.index)
    assert common_index is not None
    common_index = common_index.sort_values()

    if len(common_index) < 2:
        return CompareSnapshot(
            symbols=symbols,
            failed=failed,
            performance=[],
            performance_series=[],
            correlation_matrix=[],
            correlation_columns=[],
            stats=[],
            correlation_note=None,
            status="insufficient",
            message="Not enough overlapping price data across the selected tickers.",
        )

    aligned: dict[str, pd.Series] = {
        symbol: series.reindex(common_index) for symbol, series in successes.items()
    }

    performance = _normalize_performance(aligned, common_index, start_date, end_date)
    performance_series = [symbol for symbol in symbols if symbol in successes]

    correlation_matrix, correlation_columns, correlation_note = _pairwise_correlation(
        aligned
    )

    stats = [_ticker_stats(symbol, aligned[symbol]) for symbol in performance_series]

    return CompareSnapshot(
        symbols=symbols,
        failed=failed,
        performance=performance,
        performance_series=performance_series,
        correlation_matrix=correlation_matrix,
        correlation_columns=correlation_columns,
        stats=stats,
        correlation_note=correlation_note,
        status="ok",
        message=None,
    )


# --------------------------------------------------------------------------- #
# Backend tools (UI-only)
# --------------------------------------------------------------------------- #


@compare_app.tool()
def add_ticker(symbol: str) -> CompareSnapshot:
    """Add a ticker to the compare set and return the refreshed snapshot.

    Args:
        symbol: Ticker symbol, e.g. "aapl". Normalized via `validate_ticker`.

    Returns:
        The refreshed `CompareSnapshot`. If `symbol` is already in the
        compare set, this is a no-op (no duplicate is added).

    Raises:
        InvalidTickerError: If `symbol` has an invalid format.
    """
    normalized = validate_ticker(symbol)
    if normalized not in _COMPARE_SET:
        _COMPARE_SET.append(normalized)
    return _compare_snapshot()


@compare_app.tool()
def remove_ticker(symbol: str) -> CompareSnapshot:
    """Remove a ticker from the compare set (idempotent) and return the snapshot.

    Args:
        symbol: Ticker symbol to remove. Normalized via `validate_ticker`.

    Returns:
        The refreshed `CompareSnapshot`. If `symbol` is not in the compare
        set, this is a no-op (no error is raised).

    Raises:
        InvalidTickerError: If `symbol` has an invalid format.
    """
    normalized = validate_ticker(symbol)
    if normalized in _COMPARE_SET:
        _COMPARE_SET.remove(normalized)
    return _compare_snapshot()


@compare_app.tool()
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


@compare_app.ui()
def compare_dashboard() -> PrefabApp:
    """Render the interactive multi-ticker compare dashboard.

    Returns:
        A `PrefabApp` with an add-ticker form, an optional ticker search,
        a list of compared tickers (with per-row remove buttons), and --
        when at least 2 tickers have overlapping price data -- a normalized
        performance line chart, a return-correlation table, and a
        per-ticker key-stats table. Renders correctly for both empty and
        populated compare sets.
    """
    snapshot = _compare_snapshot()

    with PrefabApp(state={"compare": snapshot, "search_results": []}) as app:
        with Column(gap=4, css_class="p-6"):
            # ----------------------------------------------------------- #
            # Add ticker form
            # ----------------------------------------------------------- #
            with Row(gap=2):
                ticker_in = Input(  # type: ignore[call-arg]
                    name="ticker_field",
                    placeholder="Ticker",
                    input_type="text",  # type: ignore[call-arg]
                )
                Button(
                    "Add",
                    on_click=CallTool(
                        add_ticker,
                        arguments={"symbol": ticker_in.rx},
                        on_success=SetState("compare", RESULT),
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
            # Compared tickers
            # ----------------------------------------------------------- #
            with If(STATE.compare.symbols.length() == 0):
                Text("No tickers yet. Add at least 2 tickers above to compare.")
            with ForEach("compare.symbols") as sym:
                with Row(gap=4):
                    Badge(sym)  # type: ignore[arg-type,call-overload]
                    Button(
                        "Remove",
                        variant="destructive",
                        on_click=CallTool(
                            remove_ticker,
                            arguments={"symbol": sym},  # type: ignore[dict-item]
                            on_success=SetState("compare", RESULT),
                        ),
                    )

            # ----------------------------------------------------------- #
            # Failed-fetch badges
            # ----------------------------------------------------------- #
            with If(STATE.compare.failed.length() > 0):
                with ForEach("compare.failed") as failure:
                    # `failure.message` already names the ticker (e.g. "No
                    # price data for AAPL."), so prefixing with
                    # `failure.symbol` would duplicate the ticker mention.
                    Badge(  # type: ignore[arg-type,call-overload]
                        failure.message,  # type: ignore[attr-defined]
                        variant="destructive",
                    )

            # ----------------------------------------------------------- #
            # Status message (non-"ok" states)
            # ----------------------------------------------------------- #
            with If(STATE.compare.status != "ok"):
                # The If-guard above ensures `compare.message` is non-None
                # at runtime for non-"ok" statuses, but mypy can't narrow
                # types through the reactive STATE proxy.
                with Column(gap=2):
                    Badge("Not enough data", variant="secondary")
                    Text(STATE.compare.message)  # type: ignore[arg-type]

            # ----------------------------------------------------------- #
            # Charts / tables -- LITERAL call-time snapshot data, same
            # non-reactive pattern as the portfolio allocation BarChart.
            # These sections only render when the snapshot is "ok" (i.e.
            # at least 2 tickers with >=2 overlapping price observations).
            # ----------------------------------------------------------- #
            if snapshot["status"] == "ok":
                Separator()
                Text("Normalized Performance (% from start)")
                LineChart(
                    data=snapshot["performance"],  # type: ignore[arg-type]
                    series=[
                        ChartSeries(data_key=symbol, label=symbol)  # type: ignore[call-arg]
                        for symbol in snapshot["performance_series"]
                    ],
                    x_axis="date",  # type: ignore[call-arg]
                    show_legend=True,  # type: ignore[call-arg]
                    show_dots=False,  # type: ignore[call-arg]
                )

                Separator()
                Text("Return Correlation")
                if snapshot["correlation_note"]:
                    Text(snapshot["correlation_note"])
                DataTable(
                    columns=[DataTableColumn(key="ticker", header="Ticker")]
                    + [
                        DataTableColumn(key=symbol, header=symbol, format="number:2")
                        for symbol in snapshot["correlation_columns"]
                    ],
                    rows=snapshot["correlation_matrix"],  # type: ignore[arg-type]
                )

                Separator()
                Text("Key Stats")
                DataTable(
                    columns=[
                        DataTableColumn(key="symbol", header="Symbol"),
                        DataTableColumn(
                            key="latest_close",
                            header="Latest Close",
                            format="currency",
                        ),
                        DataTableColumn(
                            key="period_return_pct",
                            header="Period Return %",
                            format="number:2",
                        ),
                        DataTableColumn(
                            key="annualized_volatility_pct",
                            header="Annualized Volatility %",
                            format="number:2",
                        ),
                        DataTableColumn(
                            key="max_drawdown_pct",
                            header="Max Drawdown %",
                            format="number:2",
                        ),
                        DataTableColumn(
                            key="best_day_pct", header="Best Day %", format="number:2"
                        ),
                        DataTableColumn(
                            key="worst_day_pct", header="Worst Day %", format="number:2"
                        ),
                    ],
                    rows=snapshot["stats"],  # type: ignore[arg-type]
                )

    return app
