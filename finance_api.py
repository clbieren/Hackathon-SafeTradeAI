"""
finance_api.py — SafeTrade AI Financial Data Module
----------------------------------------------------
Provides two clean, self-contained helpers:

  get_stock_data(ticker)
      Fetches current price, market cap, and a 1-month daily price trend
      for any ticker supported by yfinance (e.g. 'AAPL', 'THYAO.IS').

  get_usd_try_rate()
      Fetches the live USD → TRY exchange rate using a waterfall of free
      public APIs (no API key required for the primary sources).

Both functions return plain dicts and never raise — they log warnings and
return structured error indicators instead, so callers can handle failures
gracefully.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any

import requests
import yfinance as yf

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared HTTP session (browser-spoofed headers, reused across calls)
# ---------------------------------------------------------------------------
_SESSION = requests.Session()
_SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
    }
)


# ---------------------------------------------------------------------------
# 1. Stock data — yfinance
# ---------------------------------------------------------------------------

def get_stock_data(ticker: str) -> dict[str, Any]:
    """
    Fetch key stock data for *ticker* using yfinance.

    Parameters
    ----------
    ticker : str
        A yfinance-compatible ticker symbol.
        Examples: ``'AAPL'`` (NASDAQ), ``'THYAO.IS'`` (Borsa Istanbul),
        ``'GARAN.IS'``, ``'MSFT'``.

    Returns
    -------
    dict with the following keys:

    ``ticker`` : str
        Normalised (upper-case) ticker symbol.
    ``company_name`` : str | None
        Long name of the company as reported by Yahoo Finance.
    ``currency`` : str | None
        Currency the price is quoted in (e.g. ``'USD'``, ``'TRY'``).
    ``current_price`` : float | None
        Latest market price (real-time or 15-min delayed).
    ``previous_close`` : float | None
        Previous session closing price.
    ``price_change_pct`` : float | None
        Percentage change vs. previous close, rounded to 2 dp.
    ``market_cap`` : int | None
        Market capitalisation in the native currency.
    ``trend_1m`` : list[dict] | None
        Daily OHLCV data for the past ~30 calendar days.
        Each element: ``{"date": "YYYY-MM-DD", "open": float,
        "high": float, "low": float, "close": float, "volume": int}``.
    ``error`` : str | None
        Human-readable error message if something went wrong; ``None`` on success.

    Examples
    --------
    >>> data = get_stock_data("THYAO.IS")
    >>> data["current_price"]
    312.5
    >>> data["trend_1m"][0]["date"]
    '2026-04-02'
    """
    ticker_upper = ticker.strip().upper()
    result: dict[str, Any] = {
        "ticker": ticker_upper,
        "company_name": None,
        "currency": None,
        "current_price": None,
        "previous_close": None,
        "price_change_pct": None,
        "market_cap": None,
        "trend_1m": None,
        "error": None,
    }

    try:
        tkr = yf.Ticker(ticker_upper)
        info: dict[str, Any] = tkr.info

        # --- Basic info ---
        result["company_name"] = info.get("longName") or info.get("shortName")
        result["currency"] = info.get("currency")
        result["market_cap"] = info.get("marketCap")

        # --- Price ---
        current = info.get("currentPrice") or info.get("regularMarketPrice")
        prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")
        result["current_price"] = current
        result["previous_close"] = prev_close

        if current is not None and prev_close and prev_close != 0:
            result["price_change_pct"] = round((current - prev_close) / prev_close * 100, 2)

        # --- 1-month daily trend ---
        end_date = date.today()
        start_date = end_date - timedelta(days=30)

        history = tkr.history(start=start_date.isoformat(), end=end_date.isoformat(), interval="1d")

        if not history.empty:
            trend: list[dict[str, Any]] = []
            for ts, row in history.iterrows():
                trend.append(
                    {
                        "date": ts.strftime("%Y-%m-%d"),
                        "open": round(float(row["Open"]), 4),
                        "high": round(float(row["High"]), 4),
                        "low": round(float(row["Low"]), 4),
                        "close": round(float(row["Close"]), 4),
                        "volume": int(row["Volume"]),
                    }
                )
            result["trend_1m"] = trend
            logger.info(
                "yfinance returned %d trend data points for '%s'.",
                len(trend),
                ticker_upper,
            )
        else:
            logger.warning("No historical data returned by yfinance for '%s'.", ticker_upper)

    except Exception as exc:  # noqa: BLE001
        msg = f"yfinance error for '{ticker_upper}': {exc}"
        logger.error(msg)
        result["error"] = msg

    return result


# ---------------------------------------------------------------------------
# 2. USD/TRY exchange rate — free public APIs (waterfall)
# ---------------------------------------------------------------------------

# Each provider is tried in order. The first successful response wins.
# All are key-free for reasonable request volumes.
_EXCHANGE_RATE_PROVIDERS: list[dict[str, Any]] = [
    {
        # Frankfurter — ECB data, reliable, no key required
        "name": "Frankfurter (ECB)",
        "url": "https://api.frankfurter.app/latest?from=USD&to=TRY",
        "parse": lambda data: float(data["rates"]["TRY"]),
    },
    {
        # Open Exchange Rates — free tier, no key for latest base USD
        "name": "ExchangeRate-API (open)",
        "url": "https://open.er-api.com/v6/latest/USD",
        "parse": lambda data: float(data["rates"]["TRY"]),
    },
    {
        # Fawaz Ahmed's free API — community-maintained, no key
        "name": "fawazahmed0/exchange-api",
        "url": "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json",
        "parse": lambda data: float(data["usd"]["try"]),
    },
]


def get_usd_try_rate() -> dict[str, Any]:
    """
    Fetch the current USD → TRY exchange rate from a free public API.

    Tries up to three different providers in order (Frankfurter ECB →
    ExchangeRate-API open endpoint → fawazahmed0 CDN).  The first
    successful response is returned; the others are skipped.

    Returns
    -------
    dict with the following keys:

    ``base`` : str
        Always ``'USD'``.
    ``quote`` : str
        Always ``'TRY'``.
    ``rate`` : float | None
        How many Turkish Lira equal one US Dollar at the time of the call.
        ``None`` if all providers failed.
    ``provider`` : str | None
        Name of the provider that successfully returned the rate.
    ``error`` : str | None
        Combined error message if all providers failed; ``None`` on success.

    Examples
    --------
    >>> result = get_usd_try_rate()
    >>> result["rate"]
    38.42
    >>> result["provider"]
    'Frankfurter (ECB)'
    """
    result: dict[str, Any] = {
        "base": "USD",
        "quote": "TRY",
        "rate": None,
        "provider": None,
        "error": None,
    }

    errors: list[str] = []

    for provider in _EXCHANGE_RATE_PROVIDERS:
        try:
            resp = _SESSION.get(provider["url"], timeout=8)
            resp.raise_for_status()
            data: dict = resp.json()
            rate = provider["parse"](data)

            result["rate"] = round(rate, 4)
            result["provider"] = provider["name"]
            logger.info(
                "USD/TRY rate %.4f fetched from '%s'.",
                rate,
                provider["name"],
            )
            return result  # Early exit on first success

        except Exception as exc:  # noqa: BLE001
            msg = f"{provider['name']}: {exc}"
            logger.warning("Exchange rate provider failed — %s", msg)
            errors.append(msg)

    # All providers failed
    result["error"] = " | ".join(errors)
    logger.error("All USD/TRY exchange rate providers failed: %s", result["error"])
    return result


# ---------------------------------------------------------------------------
# Quick self-test (run: python finance_api.py)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )

    ticker_arg = sys.argv[1] if len(sys.argv) > 1 else "THYAO.IS"
    print(f"\n{'='*60}")
    print(f"  Stock data for: {ticker_arg}")
    print(f"{'='*60}")
    stock = get_stock_data(ticker_arg)
    # Print trend separately to keep output readable
    trend = stock.pop("trend_1m", [])
    print(json.dumps(stock, indent=2, ensure_ascii=False))
    if trend:
        print(f"\n  trend_1m ({len(trend)} data points):")
        for point in trend[:3]:
            print(f"    {point}")
        if len(trend) > 3:
            print(f"    ... ({len(trend) - 3} more)")

    print(f"\n{'='*60}")
    print("  USD/TRY Exchange Rate")
    print(f"{'='*60}")
    fx = get_usd_try_rate()
    print(json.dumps(fx, indent=2, ensure_ascii=False))
