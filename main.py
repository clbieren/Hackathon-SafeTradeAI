"""
main.py — SafeTrade AI Data Mining Microservice
------------------------------------------------
Single entry point for the pipeline. Exposes:

  get_company_intelligence(company_name, ticker_symbol)
      Master orchestration function. Gathers news, complaints, stock data,
      and the live USD/TRY exchange rate, then assembles everything into the
      CompanyReport Pydantic schema and returns a clean, API-ready JSON string.

  run_pipeline(company_name, ticker, output_path)
      Thin wrapper that calls get_company_intelligence and also persists the
      JSON to a file on disk. Used by the CLI entry point.

Usage (CLI):
    python main.py --company "Türk Hava Yolları" --ticker THYAO.IS
    python main.py --company "Apple Inc." --ticker AAPL --output apple_report.json
    python main.py --company "Garanti BBVA" --ticker GARAN.IS --mock
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Any

# --- Internal modules ---
from finance_api import get_stock_data, get_usd_try_rate
from scraper import (
    Complaint,
    CompanyReport,
    FinancialMetrics,
    MarketData,
    fetch_complaints,
    fetch_news,
    generate_mock_complaint_data,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Force UTF-8 on the Windows console so Turkish characters and log symbols
# do not cause UnicodeEncodeError on CP1254 / CP1252 terminals.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s - %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Master intelligence function
# ---------------------------------------------------------------------------

def get_company_intelligence(
    company_name: str,
    ticker_symbol: str,
    use_mock_fallback: bool = False,
) -> str:
    """
    Orchestrate the full SafeTrade AI data-gathering pipeline for one company.

    Parameters
    ----------
    company_name : str
        Human-readable company name used for news and complaint searches.
        Example: ``"Türk Hava Yolları"`` or ``"Apple Inc."``.
    ticker_symbol : str
        Stock ticker recognised by Yahoo Finance.
        Example: ``"THYAO.IS"``, ``"GARAN.IS"``, ``"AAPL"``.
    use_mock_fallback : bool
        If ``True``, skip all live scraping and return purely synthetic
        Turkish demo data.  Useful for offline demos and CI smoke-tests.

    Returns
    -------
    str
        A UTF-8 JSON string that conforms to the ``CompanyReport`` Pydantic
        schema.  The string is indented (2 spaces) and safe to pass directly
        to any downstream API endpoint.

    Pipeline steps
    --------------
    1. **News**       — Google News RSS → Bing News → mock fallback
    2. **Complaints** — Şikayetvar (stub) → mock fallback
    3. **Stock data** — yfinance: current price, market cap, 1-month trend
    4. **FX rate**    — Frankfurter ECB → open.er-api.com → fawazahmed0 CDN
    5. **Assemble**   — Merge all data into CompanyReport, validate with Pydantic
    6. **Serialise**  — Return as clean, indented JSON string
    """
    ticker = ticker_symbol.strip().upper()
    logger.info("=" * 60)
    logger.info("get_company_intelligence('%s', '%s')", company_name, ticker)
    logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Step 1 — News
    # ------------------------------------------------------------------
    if use_mock_fallback:
        logger.info("[MOCK] Generating synthetic news …")
        news = generate_mock_complaint_data(company_name)["news"]
    else:
        logger.info("Step 1/4 — Fetching news …")
        news = fetch_news(company_name)
    logger.info("  [OK] %d news items collected.", len(news))

    # ------------------------------------------------------------------
    # Step 2 — Complaints
    # ------------------------------------------------------------------
    if use_mock_fallback:
        logger.info("[MOCK] Generating synthetic complaints …")
        complaints = generate_mock_complaint_data(company_name)["complaints"]
    else:
        logger.info("Step 2/4 — Fetching complaints …")
        complaints = fetch_complaints(company_name)
    logger.info("  [OK] %d complaints collected.", len(complaints))

    # ------------------------------------------------------------------
    # Step 3 — Stock data (yfinance)
    # ------------------------------------------------------------------
    logger.info("Step 3/4 — Fetching stock & financial data for '%s' …", ticker)
    stock: dict[str, Any] = get_stock_data(ticker)

    if stock.get("error"):
        logger.warning("  [WARN] Stock data error: %s", stock["error"])

    # Map finance_api fields → Pydantic FinancialMetrics
    financial_metrics = FinancialMetrics(
        market_cap=stock.get("market_cap"),
        pe_ratio=None,       # not returned by get_stock_data; extend if needed
        eps=None,
        revenue=None,
        net_income=None,
        debt_to_equity=None,
        return_on_equity=None,
    )

    # Map finance_api fields → Pydantic MarketData
    market_data = MarketData(
        ticker=ticker,
        current_price=stock.get("current_price"),
        previous_close=stock.get("previous_close"),
        day_high=None,       # not in get_stock_data summary; available via yf.info
        day_low=None,
        volume=None,
        fifty_two_week_high=None,
        fifty_two_week_low=None,
        beta=None,
        # Extra fields allowed by model_config extra="allow"
        price_change_pct=stock.get("price_change_pct"),
        currency=stock.get("currency"),
        company_name_yf=stock.get("company_name"),
        trend_1m=stock.get("trend_1m") or [],
    )
    logger.info(
        "  [OK] Stock data: price=%s %s, market_cap=%s",
        stock.get("current_price"),
        stock.get("currency", ""),
        stock.get("market_cap"),
    )

    # ------------------------------------------------------------------
    # Step 4 — USD/TRY exchange rate
    # ------------------------------------------------------------------
    logger.info("Step 4/4 — Fetching USD/TRY exchange rate …")
    fx: dict[str, Any] = get_usd_try_rate()

    if fx.get("error"):
        logger.warning("  [WARN] FX rate error: %s", fx["error"])
    else:
        logger.info(
            "  [OK] 1 USD = %.4f TRY (source: %s)",
            fx.get("rate", 0),
            fx.get("provider", "unknown"),
        )

    # ------------------------------------------------------------------
    # Step 5 — Assemble CompanyReport
    # ------------------------------------------------------------------
    logger.info("Assembling CompanyReport …")
    report = CompanyReport(
        company_name=company_name,
        recent_news=news,
        complaints=complaints,
        financial_metrics=financial_metrics,
        market_data=market_data,
        # fx_rate lives in extra fields since it's not in the base schema yet;
        # downstream consumers can read it from the JSON directly.
    )

    # Attach FX data and any pipeline metadata as top-level extra fields.
    # Pydantic v2 model_dump gives us a plain dict we can augment freely.
    report_dict = report.model_dump()
    report_dict["usd_try_rate"] = {
        "rate": fx.get("rate"),
        "provider": fx.get("provider"),
        "error": fx.get("error"),
    }
    report_dict["pipeline_meta"] = {
        "ticker": ticker,
        "stock_data_error": stock.get("error"),
        "mock_mode": use_mock_fallback,
    }

    # ------------------------------------------------------------------
    # Step 6 — Serialise to clean, API-ready JSON
    # ------------------------------------------------------------------
    json_output = json.dumps(report_dict, indent=2, ensure_ascii=False)

    logger.info("=" * 60)
    logger.info("Pipeline complete. Report has %d bytes.", len(json_output.encode("utf-8")))
    logger.info("=" * 60)

    return json_output


# ---------------------------------------------------------------------------
# File-persisting wrapper (used by CLI)
# ---------------------------------------------------------------------------

def run_pipeline(
    company_name: str,
    ticker: str,
    output_path: str,
    use_mock_fallback: bool = False,
) -> str:
    """
    Call get_company_intelligence and also write the JSON to *output_path*.

    Returns the same JSON string so callers can inspect or forward it.
    """
    json_output = get_company_intelligence(company_name, ticker, use_mock_fallback)

    logger.info("Writing report to '%s' …", output_path)
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(json_output)
    logger.info("Saved [OK]")

    return json_output


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="safetrade-miner",
        description="SafeTrade AI — Data Mining Microservice",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
  python main.py --company "Türk Hava Yolları" --ticker THYAO.IS
  python main.py --company "Apple Inc." --ticker AAPL --output apple.json
  python main.py --company "Garanti BBVA" --ticker GARAN.IS --mock
        """,
    )
    parser.add_argument(
        "--company",
        required=True,
        metavar="NAME",
        help="Full company name used for news/complaint searches.",
    )
    parser.add_argument(
        "--ticker",
        required=True,
        metavar="SYMBOL",
        help="Yahoo Finance ticker symbol (e.g. THYAO.IS, AAPL).",
    )
    parser.add_argument(
        "--output",
        default="report.json",
        metavar="FILE",
        help="Output JSON file path (default: report.json).",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Skip live scraping and use synthetic Turkish demo data instead.",
    )
    parser.add_argument(
        "--print",
        dest="print_json",
        action="store_true",
        help="Print the final JSON to stdout in addition to saving it.",
    )
    return parser


if __name__ == "__main__":
    args = _build_arg_parser().parse_args()

    result_json = run_pipeline(
        company_name=args.company,
        ticker=args.ticker.upper(),
        output_path=args.output,
        use_mock_fallback=args.mock,
    )

    if args.print_json:
        print("\n" + "-" * 60)
        print(result_json)
