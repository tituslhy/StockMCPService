"""Shared pytest configuration: hard-block all live network access.

Every test in this suite must mock data fetching; none may call Yahoo
Finance. As defense-in-depth, this autouse fixture replaces the single
yfinance entry point used by the whole codebase (`tools._data.yf.Ticker`)
with a stub that raises immediately if any test reaches it without mocking
first. A forgotten mock then fails loudly and instantly instead of
silently hitting the network (and hanging on retries/timeouts).

Layering:
- Tests that mock at a higher layer -- e.g. ``patch("ui.compare.fetch_ohlcv",
  ...)`` or ``patch("tools.price_history.fetch_ohlcv", ...)`` -- never reach
  this boundary at all.
- Tests that exercise ``tools._data.fetch_ohlcv`` directly install their own
  ``patch("tools._data.yf.Ticker", ...)``, which takes precedence inside its
  ``with`` block.
- Anything that slips through both gets a clear RuntimeError, not a network
  call.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import patch

import pytest


def _blocked_ticker(*args: object, **kwargs: object) -> object:
    """Stand-in for ``yfinance.Ticker`` that refuses to run during tests."""
    raise RuntimeError(
        "Live network access (yfinance) is blocked during tests. "
        "Mock `fetch_ohlcv` at the call site (e.g. "
        '`patch("ui.compare.fetch_ohlcv", ...)`) or '
        '`patch("tools._data.yf.Ticker", ...)` in this test.'
    )


@pytest.fixture(autouse=True)
def _block_live_network() -> Iterator[None]:
    """Autouse guard: no test may reach the real yfinance boundary."""
    with patch("tools._data.yf.Ticker", side_effect=_blocked_ticker):
        yield
