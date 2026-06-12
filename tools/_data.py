"""Shared validation and yfinance-fetch helpers for Stock MCP tools.

This module is the single point of contact with `yfinance`. All other
modules that need OHLCV data should call `fetch_ohlcv` instead of using
`yfinance` directly, so that input validation and error handling stay
consistent across the service.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

import pandas as pd
import requests
import urllib3.exceptions
import yfinance as yf
from yfinance.exceptions import (
    YFException,
    YFPricesMissingError,
    YFRateLimitError,
    YFTickerMissingError,
)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

#: Matches normalized (stripped + uppercased) ticker symbols, e.g. "AAPL",
#: "BRK.B", "BF-B".
TICKER_PATTERN: re.Pattern[str] = re.compile(r"^[A-Z0-9]{1,10}([.\-][A-Z0-9]{1,10})?$")

#: Valid `period` values accepted by `yfinance.Ticker.history`.
VALID_PERIODS: frozenset[str] = frozenset(
    {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max"}
)

#: Valid `interval` values accepted by `yfinance.Ticker.history`.
VALID_INTERVALS: frozenset[str] = frozenset(
    {
        "1m",
        "2m",
        "5m",
        "15m",
        "30m",
        "60m",
        "90m",
        "1h",
        "1d",
        "5d",
        "1wk",
        "1mo",
        "3mo",
    }
)

#: Canonical (lowercase) OHLCV column names returned by `fetch_ohlcv`.
OHLCV_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")

#: Default per-request timeout (seconds) passed to `yfinance`.
DEFAULT_TIMEOUT_SECONDS: float = 10.0


# --------------------------------------------------------------------------- #
# Exception hierarchy
# --------------------------------------------------------------------------- #


class StockDataError(Exception):
    """Base exception for all errors raised by `tools._data`.

    Attributes:
        user_message: A human-readable message suitable for surfacing to an
            end user (e.g. via an MCP tool response).
    """

    def __init__(self, user_message: str, *args: object) -> None:
        """Initialize the error with a user-facing message.

        Args:
            user_message: Human-readable description of the problem.
            *args: Additional positional arguments forwarded to
                `Exception.__init__`.
        """
        self.user_message: str = user_message
        super().__init__(user_message, *args)


class DataValidationError(StockDataError):
    """Raised when input fails validation before any yfinance call."""


class InvalidTickerError(DataValidationError):
    """Raised when a ticker symbol has an invalid format."""


class InvalidDateRangeError(DataValidationError):
    """Raised when a date range is malformed or logically invalid."""


class InvalidPeriodError(DataValidationError):
    """Raised when a `period` or `interval` value is not supported."""


class DataFetchError(StockDataError):
    """Base exception for errors raised while fetching data from yfinance."""


class TickerNotFoundError(DataFetchError):
    """Raised when yfinance returns no data for a given ticker/range."""


class NetworkError(DataFetchError):
    """Raised on connectivity, timeout, or rate-limit errors."""


# --------------------------------------------------------------------------- #
# Validation helpers
# --------------------------------------------------------------------------- #


def validate_ticker(ticker: str) -> str:
    """Validate and normalize a ticker symbol.

    The ticker is stripped of surrounding whitespace and uppercased before
    being matched against `TICKER_PATTERN`. This function does NOT check
    whether the ticker actually exists -- that is the responsibility of
    `fetch_ohlcv`.

    Args:
        ticker: Raw ticker symbol, e.g. "aapl", " BRK.B ".

    Returns:
        The normalized (stripped, uppercased) ticker symbol.

    Raises:
        InvalidTickerError: If `ticker` is empty/whitespace-only, longer
            than 10 characters, or does not match `TICKER_PATTERN`.
    """
    normalized = ticker.strip().upper()

    if not normalized:
        raise InvalidTickerError("Ticker symbol cannot be empty.")

    if len(normalized) > 10:
        raise InvalidTickerError(
            f"Ticker symbol '{normalized}' is too long (max 10 characters)."
        )

    if not TICKER_PATTERN.match(normalized):
        raise InvalidTickerError(f"'{ticker}' is not a valid ticker symbol format.")

    return normalized


def validate_date_range(
    start: str | date | datetime, end: str | date | datetime
) -> tuple[date, date]:
    """Validate and normalize a start/end date range.

    Args:
        start: Start date as an ISO "YYYY-MM-DD" string, `date`, or
            `datetime` (datetimes are truncated to their date component).
        end: End date, same accepted types as `start`.

    Returns:
        A tuple of `(start_date, end_date)` as `date` objects.

    Raises:
        InvalidDateRangeError: If either value cannot be parsed, if
            `start >= end`, or if `end` is in the future (relative to
            UTC "today").
    """
    start_date = _coerce_to_date(start)
    end_date = _coerce_to_date(end)

    if start_date >= end_date:
        raise InvalidDateRangeError(
            f"Start date ({start_date.isoformat()}) must be before "
            f"end date ({end_date.isoformat()})."
        )

    today = datetime.now(timezone.utc).date()
    if end_date > today:
        raise InvalidDateRangeError(
            f"End date ({end_date.isoformat()}) cannot be in the future."
        )

    return start_date, end_date


def _coerce_to_date(value: str | date | datetime) -> date:
    """Coerce a string/date/datetime into a `date`.

    Args:
        value: An ISO "YYYY-MM-DD" string, a `date`, or a `datetime`.

    Returns:
        The corresponding `date` object.

    Raises:
        InvalidDateRangeError: If `value` is a string that is not a valid
            ISO "YYYY-MM-DD" date.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise InvalidDateRangeError(
            f"'{value}' is not a valid date in YYYY-MM-DD format."
        ) from exc


def validate_period(period: str, interval: str = "1d") -> tuple[str, str]:
    """Validate and normalize `period` and `interval` values.

    Args:
        period: A yfinance period string, e.g. "1mo", "1y", "max".
        interval: A yfinance interval string, e.g. "1d", "1h". Defaults to
            "1d".

    Returns:
        A tuple of `(period, interval)`, both lowercased.

    Raises:
        InvalidPeriodError: If `period` is not in `VALID_PERIODS` or
            `interval` is not in `VALID_INTERVALS`.
    """
    normalized_period = period.lower()
    normalized_interval = interval.lower()

    if normalized_period not in VALID_PERIODS:
        raise InvalidPeriodError(
            f"'{period}' is not a valid period. "
            f"Must be one of: {sorted(VALID_PERIODS)}."
        )

    if normalized_interval not in VALID_INTERVALS:
        raise InvalidPeriodError(
            f"'{interval}' is not a valid interval. "
            f"Must be one of: {sorted(VALID_INTERVALS)}."
        )

    return normalized_period, normalized_interval


# --------------------------------------------------------------------------- #
# Fetch helper
# --------------------------------------------------------------------------- #


def fetch_ohlcv(
    ticker: str,
    *,
    start: str | date | datetime | None = None,
    end: str | date | datetime | None = None,
    period: str | None = None,
    interval: str = "1d",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> pd.DataFrame:
    """Fetch OHLCV price history for a ticker via yfinance.

    Exactly one of `(start AND end)` or `period` must be provided. Mixing
    both, or providing neither, is a validation error. Providing only one
    of `start`/`end` is also a validation error.

    Args:
        ticker: Ticker symbol to fetch, e.g. "AAPL".
        start: Start date for date-range mode. Must be paired with `end`.
        end: End date for date-range mode. Must be paired with `start`.
        period: Lookback period for period mode, e.g. "1mo", "1y".
        interval: Bar interval, e.g. "1d", "1h". Defaults to "1d".
        timeout: Per-request timeout in seconds passed to yfinance.
            Defaults to `DEFAULT_TIMEOUT_SECONDS`.

    Returns:
        A `pandas.DataFrame` indexed by date/datetime with exactly the
        columns in `OHLCV_COLUMNS` (lowercase: open, high, low, close,
        volume), sorted by index ascending, with duplicate index entries
        removed (keeping the last occurrence).

    Raises:
        DataValidationError: If the start/end/period combination is
            invalid, or if `validate_ticker`/`validate_period`/
            `validate_date_range` fail.
        InvalidTickerError: If `ticker` has an invalid format.
        InvalidDateRangeError: If `start`/`end` are invalid.
        InvalidPeriodError: If `period`/`interval` are invalid.
        TickerNotFoundError: If yfinance returns no data for `ticker`, or
            the returned data is missing expected OHLCV columns.
        NetworkError: If a connectivity, timeout, or rate-limit error
            occurs while contacting yfinance.
        DataFetchError: If an unexpected (non-network, non-missing-data)
            error occurs while fetching or processing data.
    """
    has_start = start is not None
    has_end = end is not None
    has_period = period is not None

    date_mode = has_start and has_end
    if has_start != has_end:
        raise DataValidationError(
            "Both 'start' and 'end' must be provided together for date-range mode."
        )

    if date_mode and has_period:
        raise DataValidationError(
            "Provide either a date range ('start' and 'end') or 'period', not both."
        )

    if not date_mode and not has_period:
        raise DataValidationError(
            "Either a date range ('start' and 'end') or 'period' must be provided."
        )

    normalized_ticker = validate_ticker(ticker)
    # In date-range mode `period` is irrelevant; "1d" is just a placeholder
    # so that `interval` still gets validated.
    normalized_period, normalized_interval = validate_period(period or "1d", interval)

    start_date: date | None = None
    end_date: date | None = None
    range_description: str
    if date_mode:
        assert start is not None and end is not None  # narrowed by date_mode
        start_date, end_date = validate_date_range(start, end)
        range_description = f"{start_date.isoformat()} to {end_date.isoformat()}"
    else:
        range_description = f"period={normalized_period}"

    try:
        yf_ticker = yf.Ticker(normalized_ticker)
        if date_mode:
            df = yf_ticker.history(
                start=start_date,
                end=end_date,
                interval=normalized_interval,
                timeout=timeout,
            )
        else:
            df = yf_ticker.history(
                period=normalized_period,
                interval=normalized_interval,
                timeout=timeout,
            )
    except (YFTickerMissingError, YFPricesMissingError) as exc:
        raise TickerNotFoundError(
            f"No data found for ticker '{normalized_ticker}' ({range_description})."
        ) from exc
    except (
        YFRateLimitError,
        YFException,
        requests.exceptions.RequestException,
        urllib3.exceptions.TimeoutError,
        urllib3.exceptions.ConnectionError,
    ) as exc:
        raise NetworkError(
            f"Failed to fetch data for ticker '{normalized_ticker}' due to "
            f"a network error: {exc}"
        ) from exc
    except Exception as exc:
        raise DataFetchError(
            f"An unexpected error occurred while fetching data for "
            f"'{normalized_ticker}'."
        ) from exc

    if df.empty:
        raise TickerNotFoundError(
            f"No data found for ticker '{normalized_ticker}' ({range_description})."
        )

    df.columns = df.columns.str.lower()

    try:
        df = df[list(OHLCV_COLUMNS)]
    except KeyError as exc:
        raise TickerNotFoundError(
            f"No data found for ticker '{normalized_ticker}' "
            f"({range_description}): missing expected OHLCV columns."
        ) from exc

    df = df.sort_index()
    df = df[~df.index.duplicated(keep="last")]

    return df
