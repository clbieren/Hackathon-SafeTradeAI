"""
SafeTrade AI - B2B Trust Platform (Merged API & Scraper)
--------------------------------------------------------
Run API: python main.py
Run CLI: python main.py --company "Apple Inc." --ticker AAPL
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import random
import datetime
from typing import Any, Optional, List

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- Internal Scraper Modules ---
try:
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
except ImportError:
    pass # Tolerate missing imports if running only for the mock API

# ---------------------------------------------------------------------------
# Logging Setup
# ---------------------------------------------------------------------------
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
# FastAPI Setup (UI Dashboard Backend)
# ---------------------------------------------------------------------------
app = FastAPI(
    title="SafeTrade AI API",
    description="B2B Trust Platform — Trust Score, Financial Risk & Competitor Intelligence",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static dummy data pools
COMPANIES = {
    "comp_001": {"name": "Nexora Logistics GmbH", "sector": "Logistics & Supply Chain", "country": "Germany", "founded": 2009, "employees": 1240, "annual_revenue_usd": 87_400_000},
    "comp_002": {"name": "Stellartech Solutions Ltd", "sector": "Enterprise SaaS", "country": "United Kingdom", "founded": 2015, "employees": 380, "annual_revenue_usd": 22_100_000},
    "comp_003": {"name": "Ironclad Manufacturing Co.", "sector": "Industrial Manufacturing", "country": "United States", "founded": 1998, "employees": 4700, "annual_revenue_usd": 312_000_000},
    "comp_004": {"name": "AquaFlow Renewables", "sector": "Renewable Energy", "country": "Netherlands", "founded": 2018, "employees": 215, "annual_revenue_usd": 11_500_000},
    "comp_005": {"name": "PrimeMed Healthcare", "sector": "Healthcare & Pharma", "country": "Canada", "founded": 2003, "employees": 2900, "annual_revenue_usd": 198_600_000},
}

RISK_FACTORS_POOL = [
    {"factor": "Late payment history (>30 days)", "severity": "high", "weight": 0.25},
    {"factor": "Debt-to-equity ratio above industry average", "severity": "medium", "weight": 0.18},
    {"factor": "Revenue decline >10% YoY", "severity": "high", "weight": 0.22},
    {"factor": "Pending litigation exposure", "severity": "medium", "weight": 0.15},
    {"factor": "Currency exposure in volatile markets", "severity": "low", "weight": 0.08},
    {"factor": "Concentrated customer base (top 3 > 60% revenue)", "severity": "medium", "weight": 0.14},
    {"factor": "Negative press sentiment (last 90 days)", "severity": "low", "weight": 0.07},
    {"factor": "Regulatory compliance gap identified", "severity": "high", "weight": 0.21},
    {"factor": "Supplier dependency risk", "severity": "medium", "weight": 0.11},
    {"factor": "Insurance coverage below threshold", "severity": "low", "weight": 0.06},
]

SECTORS = {
    "Logistics & Supply Chain": [
        {"name": "GlobalFreight AG", "market_share_pct": 18.4, "trend": "stable", "hq": "Switzerland"},
        {"name": "SwiftRoute Inc.", "market_share_pct": 14.1, "trend": "growing", "hq": "USA"},
    ],
    "Enterprise SaaS": [
        {"name": "CoreSuite Technologies", "market_share_pct": 22.3, "trend": "growing", "hq": "USA"},
    ],
}

class TrustScoreResponse(BaseModel):
    request_id: str
    timestamp: str
    company_id: str
    company_name: str
    sector: str
    trust_score: float
    grade: str
    confidence_level: str
    breakdown: dict
    recommendation: str
    next_review_date: str

class FinancialRiskResponse(BaseModel):
    request_id: str
    timestamp: str
    company_id: str
    company_name: str
    overall_risk_rating: str
    risk_score: float
    risk_factors: list
    financial_snapshot: dict
    credit_limit_recommendation_usd: int
    alert_flags: list

class MarketShareResponse(BaseModel):
    request_id: str
    timestamp: str
    sector: str
    analysis_period: str
    target_company: dict
    competitors: list
    market_insights: dict

def _request_id() -> str:
    import uuid
    return f"req_{uuid.uuid4().hex[:12].upper()}"

def _now() -> str:
    return datetime.datetime.utcnow().isoformat() + "Z"

def _score_to_grade(score: float) -> str:
    if score >= 90: return "AAA"
    if score >= 80: return "AA"
    if score >= 70: return "A"
    if score >= 60: return "BBB"
    if score >= 50: return "BB"
    if score >= 40: return "B"
    return "CCC"

def _risk_label(score: float) -> str:
    if score <= 25: return "LOW"
    if score <= 50: return "MEDIUM"
    if score <= 75: return "HIGH"
    return "CRITICAL"

def _get_company(company_id: str) -> dict:
    if company_id not in COMPANIES:
        raise HTTPException(
            status_code=404,
            detail={"error": "company_not_found", "valid_ids": list(COMPANIES.keys())},
        )
    return COMPANIES[company_id]

@app.get("/", tags=["Health"])
def root():
    return {"service": "SafeTrade AI API", "status": "operational"}

@app.get("/api/v1/trust-score/{company_id}", response_model=TrustScoreResponse, tags=["Trust Score"])
def get_trust_score(company_id: str, include_history: Optional[bool] = Query(False)):
    company = _get_company(company_id)
    rng = random.Random(company_id)
    score = round(rng.uniform(42.0, 94.0), 1)
    grade = _score_to_grade(score)
    
    return {
        "request_id": _request_id(),
        "timestamp": _now(),
        "company_id": company_id,
        "company_name": company["name"],
        "sector": company["sector"],
        "trust_score": score,
        "grade": grade,
        "confidence_level": "HIGH" if score > 60 else "MEDIUM",
        "breakdown": {"payment_behavior": round(rng.uniform(40, 100), 1)},
        "recommendation": "System Recommended.",
        "next_review_date": (datetime.date.today() + datetime.timedelta(days=90)).isoformat(),
    }

@app.get("/api/v1/financial-risk/{company_id}", response_model=FinancialRiskResponse, tags=["Financial Risk"])
def get_financial_risk(company_id: str, currency: Optional[str] = Query("USD")):
    company = _get_company(company_id)
    rng = random.Random(company_id + "risk")
    risk_score = round(rng.uniform(12.0, 78.0), 1)
    revenue = company["annual_revenue_usd"]
    
    return {
        "request_id": _request_id(),
        "timestamp": _now(),
        "company_id": company_id,
        "company_name": company["name"],
        "overall_risk_rating": _risk_label(risk_score),
        "risk_score": risk_score,
        "risk_factors": rng.sample(RISK_FACTORS_POOL, k=3),
        "financial_snapshot": {"annual_revenue_usd": revenue, "currency": currency},
        "credit_limit_recommendation_usd": int((revenue * rng.uniform(0.04, 0.18)) / 1000) * 1000,
        "alert_flags": [],
    }

@app.get("/api/v1/market-share/{company_id}", response_model=MarketShareResponse, tags=["Competitor Intelligence"])
def get_market_share(company_id: str, top_n: Optional[int] = Query(5)):
    company = _get_company(company_id)
    sector = company["sector"]
    competitors = SECTORS.get(sector, list(SECTORS.values())[0])[:top_n]
    
    return {
        "request_id": _request_id(),
        "timestamp": _now(),
        "sector": sector,
        "analysis_period": "2026-Q2",
        "target_company": {"company_id": company_id, "name": company["name"], "market_share_pct": 12.5, "trend": "stable", "hq": company["country"]},
        "competitors": competitors,
        "market_insights": {"total_addressable_market_usd": 1000000},
    }

# ---------------------------------------------------------------------------
# Data Mining Orchestration (Scraper)
# ---------------------------------------------------------------------------
def get_company_intelligence(company_name: str, ticker_symbol: str, use_mock_fallback: bool = False) -> str:
    ticker = ticker_symbol.strip().upper()
    logger.info("=" * 60)
    logger.info("get_company_intelligence('%s', '%s')", company_name, ticker)
    
    if use_mock_fallback:
        news = generate_mock_complaint_data(company_name)["news"]
        complaints = generate_mock_complaint_data(company_name)["complaints"]
    else:
        news = fetch_news(company_name)
        complaints = fetch_complaints(company_name)
        
    stock = get_stock_data(ticker)
    fx = get_usd_try_rate()
    
    report_dict = {
        "company_name": company_name,
        "recent_news": news,
        "complaints": complaints,
        "financial_metrics": {"market_cap": stock.get("market_cap")},
        "market_data": {"ticker": ticker, "current_price": stock.get("current_price")},
        "usd_try_rate": {"rate": fx.get("rate")},
    }
    return json.dumps(report_dict, indent=2, ensure_ascii=False)

def run_pipeline(company_name: str, ticker: str, output_path: str, use_mock_fallback: bool = False) -> str:
    json_output = get_company_intelligence(company_name, ticker, use_mock_fallback)
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(json_output)
    return json_output

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="safetrade-miner", description="SafeTrade AI Data Mining")
    parser.add_argument("--company", required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--output", default="report.json")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--print", dest="print_json", action="store_true")
    return parser

# ---------------------------------------------------------------------------
# Single Entry Point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # If a company name is provided via CLI, run the scraper
    if len(sys.argv) > 1 and "--company" in sys.argv:
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
    else:
        # Otherwise, launch the FastAPI server for the UI
        import uvicorn
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)