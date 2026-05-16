"""
SafeTrade AI - B2B Trust Platform Backend API
Run: uvicorn main:app --reload --host 0.0.0.0 --port 8000
Docs: http://localhost:8000/docs
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import random
import datetime

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

# ---------------------------------------------------------------------------
# Static dummy data pools
# ---------------------------------------------------------------------------

COMPANIES = {
    "comp_001": {
        "name": "Nexora Logistics GmbH",
        "sector": "Logistics & Supply Chain",
        "country": "Germany",
        "founded": 2009,
        "employees": 1240,
        "annual_revenue_usd": 87_400_000,
    },
    "comp_002": {
        "name": "Stellartech Solutions Ltd",
        "sector": "Enterprise SaaS",
        "country": "United Kingdom",
        "founded": 2015,
        "employees": 380,
        "annual_revenue_usd": 22_100_000,
    },
    "comp_003": {
        "name": "Ironclad Manufacturing Co.",
        "sector": "Industrial Manufacturing",
        "country": "United States",
        "founded": 1998,
        "employees": 4700,
        "annual_revenue_usd": 312_000_000,
    },
    "comp_004": {
        "name": "AquaFlow Renewables",
        "sector": "Renewable Energy",
        "country": "Netherlands",
        "founded": 2018,
        "employees": 215,
        "annual_revenue_usd": 11_500_000,
    },
    "comp_005": {
        "name": "PrimeMed Healthcare",
        "sector": "Healthcare & Pharma",
        "country": "Canada",
        "founded": 2003,
        "employees": 2900,
        "annual_revenue_usd": 198_600_000,
    },
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
        {"name": "CargoNexus BV", "market_share_pct": 10.7, "trend": "declining", "hq": "Netherlands"},
        {"name": "LogiStar Corp", "market_share_pct": 9.2, "trend": "growing", "hq": "Singapore"},
        {"name": "TradeLink GmbH", "market_share_pct": 7.8, "trend": "stable", "hq": "Germany"},
    ],
    "Enterprise SaaS": [
        {"name": "CoreSuite Technologies", "market_share_pct": 22.3, "trend": "growing", "hq": "USA"},
        {"name": "FlowWorks Ltd", "market_share_pct": 16.9, "trend": "growing", "hq": "UK"},
        {"name": "OpsMatrix Inc.", "market_share_pct": 12.4, "trend": "stable", "hq": "Canada"},
        {"name": "SyncPlatform AB", "market_share_pct": 8.7, "trend": "declining", "hq": "Sweden"},
        {"name": "VantaCloud GmbH", "market_share_pct": 6.1, "trend": "growing", "hq": "Germany"},
    ],
    "Industrial Manufacturing": [
        {"name": "ForgeTech Industries", "market_share_pct": 24.6, "trend": "stable", "hq": "USA"},
        {"name": "Krauss Precision AG", "market_share_pct": 19.1, "trend": "declining", "hq": "Germany"},
        {"name": "SteelPeak Corp", "market_share_pct": 13.8, "trend": "stable", "hq": "Japan"},
        {"name": "AlloyDynamics Ltd", "market_share_pct": 9.4, "trend": "growing", "hq": "UK"},
        {"name": "MechCore SA", "market_share_pct": 6.2, "trend": "stable", "hq": "France"},
    ],
    "Renewable Energy": [
        {"name": "SolarPeak Energy", "market_share_pct": 20.2, "trend": "growing", "hq": "Denmark"},
        {"name": "WindForce Global", "market_share_pct": 17.5, "trend": "growing", "hq": "Germany"},
        {"name": "HydroGen Systems", "market_share_pct": 11.3, "trend": "stable", "hq": "Norway"},
        {"name": "GreenVolt Partners", "market_share_pct": 8.9, "trend": "growing", "hq": "USA"},
        {"name": "EcoGrid Solutions", "market_share_pct": 5.4, "trend": "stable", "hq": "Netherlands"},
    ],
    "Healthcare & Pharma": [
        {"name": "MediCore International", "market_share_pct": 26.8, "trend": "stable", "hq": "USA"},
        {"name": "BioSynth Laboratories", "market_share_pct": 18.2, "trend": "growing", "hq": "Switzerland"},
        {"name": "PharmaBridge Inc.", "market_share_pct": 14.5, "trend": "declining", "hq": "Ireland"},
        {"name": "LifeGuard Systems", "market_share_pct": 10.1, "trend": "stable", "hq": "Germany"},
        {"name": "VitaCare Ltd", "market_share_pct": 7.3, "trend": "growing", "hq": "UK"},
    ],
}

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
            detail={
                "error": "company_not_found",
                "message": f"No company found with ID '{company_id}'.",
                "valid_ids": list(COMPANIES.keys()),
            },
        )
    return COMPANIES[company_id]

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/", tags=["Health"])
def root():
    return {
        "service": "SafeTrade AI API",
        "version": "1.0.0",
        "status": "operational",
        "timestamp": _now(),
        "endpoints": [
            "/api/v1/trust-score/{company_id}",
            "/api/v1/financial-risk/{company_id}",
            "/api/v1/market-share/{company_id}",
        ],
    }


@app.get("/api/v1/trust-score/{company_id}", response_model=TrustScoreResponse, tags=["Trust Score"])
def get_trust_score(
    company_id: str,
    include_history: Optional[bool] = Query(False, description="Include 12-month score history"),
):
    """
    Returns a composite AI-generated Trust Score (0–100) for a B2B counterparty.
    Factors include payment history, compliance record, operational stability,
    public sentiment, and financial health.
    """
    company = _get_company(company_id)

    rng = random.Random(company_id)
    score = round(rng.uniform(42.0, 94.0), 1)
    grade = _score_to_grade(score)

    breakdown = {
        "payment_behavior": round(rng.uniform(40, 100), 1),
        "financial_health": round(rng.uniform(35, 95), 1),
        "compliance_record": round(rng.uniform(50, 100), 1),
        "operational_stability": round(rng.uniform(45, 98), 1),
        "public_sentiment": round(rng.uniform(30, 95), 1),
        "data_transparency": round(rng.uniform(55, 100), 1),
    }

    recommendations = {
        "AAA": "Highly recommended counterparty. Proceed with standard contract terms.",
        "AA": "Strong trust profile. Minimal due diligence required.",
        "A": "Reliable partner. Routine monitoring advised.",
        "BBB": "Acceptable risk. Enhanced payment terms recommended.",
        "BB": "Moderate risk. Request financial disclosures before proceeding.",
        "B": "Elevated risk. Require collateral or performance bond.",
        "CCC": "High risk. Avoid or require significant risk mitigation.",
    }

    response = {
        "request_id": _request_id(),
        "timestamp": _now(),
        "company_id": company_id,
        "company_name": company["name"],
        "sector": company["sector"],
        "trust_score": score,
        "grade": grade,
        "confidence_level": "HIGH" if score > 60 else "MEDIUM",
        "breakdown": breakdown,
        "recommendation": recommendations[grade],
        "next_review_date": (
            datetime.date.today() + datetime.timedelta(days=90)
        ).isoformat(),
    }

    if include_history:
        history = []
        base_date = datetime.date.today()
        for i in range(12, 0, -1):
            month_date = base_date - datetime.timedelta(days=30 * i)
            history.append({
                "period": month_date.strftime("%Y-%m"),
                "score": round(score + rng.uniform(-8, 8), 1),
                "grade": _score_to_grade(score + rng.uniform(-8, 8)),
            })
        response["score_history"] = history

    return response


@app.get("/api/v1/financial-risk/{company_id}", response_model=FinancialRiskResponse, tags=["Financial Risk"])
def get_financial_risk(
    company_id: str,
    currency: Optional[str] = Query("USD", description="Display currency (ISO 4217)"),
):
    """
    Returns a detailed financial risk assessment including risk score, contributing
    risk factors with severity weights, a financial snapshot, and credit recommendations.
    """
    company = _get_company(company_id)

    rng = random.Random(company_id + "risk")
    risk_score = round(rng.uniform(12.0, 78.0), 1)
    risk_rating = _risk_label(risk_score)

    selected_factors = rng.sample(RISK_FACTORS_POOL, k=rng.randint(3, 6))

    revenue = company["annual_revenue_usd"]
    snapshot = {
        "annual_revenue_usd": revenue,
        "gross_profit_margin_pct": round(rng.uniform(18.0, 52.0), 1),
        "ebitda_margin_pct": round(rng.uniform(8.0, 34.0), 1),
        "debt_to_equity_ratio": round(rng.uniform(0.3, 2.8), 2),
        "current_ratio": round(rng.uniform(0.8, 3.2), 2),
        "days_sales_outstanding": rng.randint(22, 91),
        "cash_reserve_usd": int(revenue * rng.uniform(0.05, 0.22)),
        "credit_utilization_pct": round(rng.uniform(10.0, 85.0), 1),
        "yoy_revenue_growth_pct": round(rng.uniform(-15.0, 32.0), 1),
        "currency": currency,
    }

    credit_limit = int((revenue * rng.uniform(0.04, 0.18)) / 1000) * 1000

    alert_flags = []
    for f in selected_factors:
        if f["severity"] == "high":
            alert_flags.append({
                "code": f"FLAG_{f['factor'][:6].upper().replace(' ', '_')}",
                "message": f["factor"],
                "severity": "HIGH",
                "triggered_at": _now(),
            })

    return {
        "request_id": _request_id(),
        "timestamp": _now(),
        "company_id": company_id,
        "company_name": company["name"],
        "overall_risk_rating": risk_rating,
        "risk_score": risk_score,
        "risk_factors": selected_factors,
        "financial_snapshot": snapshot,
        "credit_limit_recommendation_usd": credit_limit,
        "alert_flags": alert_flags,
    }


@app.get("/api/v1/market-share/{company_id}", response_model=MarketShareResponse, tags=["Competitor Intelligence"])
def get_market_share(
    company_id: str,
    top_n: Optional[int] = Query(5, ge=1, le=10, description="Number of top competitors to return"),
):
    """
    Returns competitor market share analysis for the sector of the specified company,
    including trend indicators, positioning insights, and strategic summary.
    """
    company = _get_company(company_id)
    sector = company["sector"]
    competitors_pool = SECTORS.get(sector, list(SECTORS.values())[0])

    rng = random.Random(company_id + "market")
    company_share = round(rng.uniform(4.5, 15.5), 1)
    company_trend = rng.choice(["growing", "stable", "declining"])

    competitors = competitors_pool[:top_n]

    total_named = company_share + sum(c["market_share_pct"] for c in competitors)
    others_share = round(max(0.0, 100.0 - total_named), 1)

    insights = {
        "total_addressable_market_usd": int(company["annual_revenue_usd"] / (company_share / 100)),
        "market_concentration_index": round(rng.uniform(0.08, 0.35), 3),
        "top_3_combined_share_pct": round(sum(c["market_share_pct"] for c in competitors[:3]), 1),
        "others_combined_share_pct": others_share,
        "sector_growth_rate_yoy_pct": round(rng.uniform(1.2, 18.7), 1),
        "competitive_intensity": rng.choice(["LOW", "MEDIUM", "HIGH", "VERY HIGH"]),
        "strategic_position": (
            "Market Leader" if company_share > 15
            else "Challenger" if company_share > 8
            else "Niche Player"
        ),
        "analysis_note": (
            f"{company['name']} holds a {company_share}% share in a "
            f"{'growing' if rng.random() > 0.4 else 'consolidating'} {sector} market. "
            f"Competitive pressure is {'intensifying' if rng.random() > 0.5 else 'moderate'} "
            f"with {'3' if rng.random() > 0.5 else '2'} dominant players above 15% share."
        ),
    }

    today = datetime.date.today()
    quarter_start = today.replace(day=1, month=((today.month - 1) // 3) * 3 + 1)
    analysis_period = f"{quarter_start.strftime('%Y-Q')}{(today.month - 1) // 3 + 1}"

    return {
        "request_id": _request_id(),
        "timestamp": _now(),
        "sector": sector,
        "analysis_period": analysis_period,
        "target_company": {
            "company_id": company_id,
            "name": company["name"],
            "market_share_pct": company_share,
            "trend": company_trend,
            "hq": company["country"],
        },
        "competitors": competitors,
        "market_insights": insights,
    }


# ---------------------------------------------------------------------------
# Batch endpoint
# ---------------------------------------------------------------------------

@app.post("/api/v1/batch-analysis", tags=["Batch"])
def batch_analysis(company_ids: List[str]):
    """
    Run Trust Score + Financial Risk for multiple company IDs in one call.
    Max 10 companies per request.
    """
    if len(company_ids) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 companies per batch request.")

    results = []
    for cid in company_ids:
        try:
            trust = get_trust_score(cid)
            risk = get_financial_risk(cid)
            results.append({
                "company_id": cid,
                "status": "success",
                "trust_score": trust["trust_score"],
                "trust_grade": trust["grade"],
                "risk_score": risk["risk_score"],
                "risk_rating": risk["overall_risk_rating"],
                "credit_limit_usd": risk["credit_limit_recommendation_usd"],
            })
        except HTTPException as e:
            results.append({"company_id": cid, "status": "error", "detail": e.detail})

    return {
        "request_id": _request_id(),
        "timestamp": _now(),
        "total_requested": len(company_ids),
        "total_processed": len([r for r in results if r["status"] == "success"]),
        "results": results,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
