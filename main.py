import asyncio
import contextlib
import json
import logging
import os
import sys
import time
import uuid
import argparse
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Any, List, Optional, Union

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.config import get_settings
from app.database import AsyncSessionLocal, Base, engine, get_db
from app.models import Company, Report, User
from app.auth import get_current_user
from app.routers.auth import router as auth_router
from app.repository import (
    create_company, get_companies, get_company, update_company, delete_company,
    create_report, get_reports, get_report, get_reports_by_company,
    update_report, delete_report, create_company_report,
    get_fresh_report_by_company, get_companies_with_latest_report, create_company_stub,
    create_alert, get_alerts_by_user, get_alert, get_alert_by_id,
    toggle_alert, delete_alert, deactivate_alert,
)
from app.schemas import (
    CompanyCreate, CompanyResponse, CompanyUpdate, HealthResponse,
    ReportCreate, ReportResponse, ReportUpdate, AlertCreate, AlertResponse,
)
from app.services.ai_engine import AIService, _MODEL_NAME
from google.genai import types as genai_types
from app.services.external_api import NewsService, FinnhubService, CurrencyService
from app.services.matcher_service import MatcherService
from app.services.pdf_engine import PDFService
from app.services.scraper_service import ScraperService

logger = logging.getLogger(__name__)
settings = get_settings()
_OFFICIAL_DATA_CACHE_TTL_SECONDS = 60
_OFFICIAL_DATA_MAX_CONCURRENCY = 4
_STREAM_IDLE_HEARTBEAT_LIMIT = 5

class MarketAnalysisRequest(BaseModel):
    company_name: str
    full_address: str

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    max_retries = 5
    retry_delay = 5
    for attempt in range(max_retries):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database connection successful.")
            break
        except Exception as e:
            logger.error(f"Database connection failed: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
            else:
                raise e
    app.state.background_tasks = set()
    app.state.inflight_report_keys = set()
    app.state.inflight_lock = asyncio.Lock()
    app.state.official_data_semaphore = asyncio.Semaphore(_OFFICIAL_DATA_MAX_CONCURRENCY)
    app.state.official_data_cache = {}

    from app.services.scheduler_service import SchedulerService
    scheduler = SchedulerService()
    scheduler.start()
    app.state.scheduler = scheduler

    yield

    scheduler.stop()
    pending_tasks = list(getattr(app.state, "background_tasks", set()))
    for task in pending_tasks:
        task.cancel()
    if pending_tasks:
        await asyncio.gather(*pending_tasks, return_exceptions=True)
    await engine.dispose()

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="SafeTrade AI: B2B intelligence center",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", 
        "http://localhost:5500", 
        "http://127.0.0.1:5500", 
        "http://localhost:8000", 
        "http://127.0.0.1:8000",
        "https://www.safeai.com.tr",
        "https://safeai.com.tr",
        "https://safetradeai.vercel.app",
        "https://safetradeai-production.up.railway.app"
    ],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)

@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    started_at = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request_failed", extra={"request_id": request_id, "path": request.url.path, "method": request.method})
        raise
    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    response.headers["x-request-id"] = request_id
    response.headers["x-response-time-ms"] = str(elapsed_ms)
    logger.info("request_complete path=%s method=%s status=%s duration_ms=%s request_id=%s", request.url.path, request.method, getattr(response, "status_code", "unknown"), elapsed_ms, request_id)
    return response

@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check() -> HealthResponse:
    db_status = "error"
    detail = None
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        db_status = "ok"
    except SQLAlchemyError as exc:
        if settings.debug: detail = str(exc)
    return HealthResponse(status="ok" if db_status == "ok" else "error", database=db_status, app_name=settings.app_name, app_version=settings.app_version, detail=detail)

@app.post("/companies", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED, tags=["Companies"])
async def api_create_company(data: CompanyCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return await create_company(db, data, owner_id=current_user.id)

@app.get("/companies", response_model=List[CompanyResponse], tags=["Companies"])
async def api_list_companies(offset: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return await get_companies(db, owner_id=current_user.id, offset=offset, limit=limit)

@app.get("/companies/search", response_model=Optional[CompanyResponse], tags=["Companies"])
async def api_search_company(name: str = Query(..., min_length=2), db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    companies = await get_companies(db, owner_id=current_user.id, offset=0, limit=500)
    return next((c for c in companies if c.name.lower() == name.lower()), None)

@app.get("/companies/{company_id}", response_model=CompanyResponse, tags=["Companies"])
async def api_get_company(company_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    company = await get_company(db, company_id, owner_id=current_user.id)
    if not company: raise HTTPException(status_code=404, detail="Company not found.")
    return company

@app.patch("/companies/{company_id}", response_model=CompanyResponse, tags=["Companies"])
async def api_update_company(company_id: int, data: CompanyUpdate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    company = await update_company(db, company_id, owner_id=current_user.id, data=data)
    if not company: raise HTTPException(status_code=404, detail="Company not found.")
    return company

@app.delete("/companies/{company_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Companies"])
async def api_delete_company(company_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not await delete_company(db, company_id, owner_id=current_user.id): raise HTTPException(status_code=404, detail="Company not found.")

async def _save_report_background(company_id: int, ai_data: dict, raw_market_data: dict, owner_id: Optional["uuid.UUID"] = None) -> None:
    try:
        async with AsyncSessionLocal() as db:
            await asyncio.wait_for(create_company_report(db=db, company_id=company_id, ai_data=ai_data, raw_market_data=raw_market_data, owner_id=owner_id), timeout=20)
    except Exception as exc:
        logger.error("Background save error for company_id=%s: %s", company_id, exc)

async def _retry_once(coro_factory, timeout_seconds: float):
    last_exc: Optional[Exception] = None
    for _ in range(2):
        try:
            return await asyncio.wait_for(coro_factory(), timeout=timeout_seconds)
        except (asyncio.TimeoutError, HTTPException) as exc:
            last_exc = exc
    if isinstance(last_exc, HTTPException): raise last_exc
    raise HTTPException(status_code=504, detail="External data sources timed out.")

def _track_background_task(task: asyncio.Task[Any]) -> None:
    task_set = getattr(app.state, "background_tasks", None)
    if task_set is None: return
    task_set.add(task)
    task.add_done_callback(task_set.discard)

def _serialize_sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

def _report_key(company_id: int, full_address: str, branch_name: str) -> str:
    return f"{company_id}:{full_address.strip().lower()}:{branch_name.strip().lower()}"

async def _fetch_official_data_safely(tax_number: str, company_name: str) -> dict:
    from app.services.scraper_service import OfficialScraperService
    try:
        async with OfficialScraperService() as offsvc:
            return await asyncio.wait_for(offsvc.get_all_official_data(tax_number, company_name), timeout=8.0)
    except Exception:
        return {"status": "official_data_unavailable", "reason": "timeout_or_failure"}

@app.post("/generate-report/{company_id}", tags=["Intelligence"])
async def api_generate_report(company_id: int, request: Request, background_tasks: BackgroundTasks, full_address: str = Query(""), branch_name: str = Query(""), db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    request_id = getattr(request.state, "request_id", "unknown")
    company = await get_company(db, company_id, owner_id=current_user.id)
    if not company: raise HTTPException(status_code=404, detail="Company not found.")

    if not full_address.strip():
        cached_report = await get_fresh_report_by_company(db, company_id)
        if cached_report:
            report_dict = ReportResponse.model_validate(cached_report).model_dump(mode="json")
            report_dict["cache_hit"] = True
            return JSONResponse(content=report_dict)

    has_address = bool(full_address.strip())
    inflight_key = _report_key(company_id, full_address, branch_name or company.name)

    async def _fetch_news() -> list:
        async with NewsService() as svc: return await svc.get_news(company.name)
    async def _fetch_profile() -> dict:
        async with FinnhubService() as svc: return await svc.get_company_profile("")
    async def _fetch_rates() -> dict:
        async with CurrencyService() as svc: return await svc.get_rates(target_currencies=["TRY", "EUR"])
    async def _fetch_scraped() -> list:
        async with ScraperService() as svc:
            res = await svc.get_scraped_data(company.name, full_address=full_address)
            return res.get("items", []) if isinstance(res, dict) else res
    async def _fetch_place() -> dict:
        if not has_address or not settings.google_places_api_key: return {}
        try:
            async with MatcherService() as svc: return await svc.resolve_entity(target_name=branch_name or company.name, target_address=full_address) or {}
        except Exception: return {}

    async def _event_stream() -> AsyncGenerator[str, None]:
        stream_started_at = time.monotonic()
        active_tasks: List[asyncio.Task[Any]] = []
        stream_terminated = False

        if await request.is_disconnected(): return

        async with app.state.inflight_lock:
            if inflight_key in app.state.inflight_report_keys:
                yield _serialize_sse({"type": "status", "message": "Aynı rapor şu an üretiliyor, sonuçlar bekleniyor."})
            else:
                app.state.inflight_report_keys.add(inflight_key)

        yield _serialize_sse({"type": "status", "message": "Veri toplama başlıyor..."})
        news_task = asyncio.create_task(_fetch_news())
        profile_task = asyncio.create_task(_fetch_profile())
        rates_task = asyncio.create_task(_fetch_rates())
        scraped_task = asyncio.create_task(_fetch_scraped())
        place_task = asyncio.create_task(_fetch_place())
        active_tasks.extend([news_task, profile_task, rates_task, scraped_task, place_task])

        tax_number = getattr(company, "tax_number", None) or ""
        official_task = asyncio.create_task(_fetch_official_data_safely(tax_number, company.name)) if tax_number.strip() else None
        if official_task: active_tasks.append(official_task)

        try:
            yield _serialize_sse({"type": "status", "message": "Resmi veriler sorgulanıyor..."})
            done, pending = await asyncio.wait(active_tasks, timeout=20.0)
            for pt in pending: pt.cancel()

            def _safe_result(task: Optional[asyncio.Task[Any]], default: Any) -> Any:
                if task is None or task not in done or task.cancelled() or task.exception(): return default
                return task.result()

            news_res = _safe_result(news_task, [])
            profile_res = _safe_result(profile_task, {})
            scraped_res = _safe_result(scraped_task, [])
            place_res = _safe_result(place_task, {})

            legal_info = {}
            if place_res and place_res.get("place_id"):
                from app.services.legal_resolver import LegalResolver
                try:
                    resolver = LegalResolver(settings.google_places_api_key)
                    legal_info = await asyncio.wait_for(resolver.resolve(place_id=place_res["place_id"], company_name=company.name), timeout=25.0)
                except Exception: pass

            branch_context = {
                "branch_name": branch_name or company.name,
                "formatted_address": full_address,
                "legal_name": legal_info.get("legal_name"),
                "tax_number": legal_info.get("tax_number"),
                "mersis_number": legal_info.get("mersis_number"),
                "legal_confidence": legal_info.get("confidence", "none"),
                "legal_source": legal_info.get("source", "not_found"),
            }

            yield _serialize_sse({"type": "data_sources", "sources": {"GIB": "OK", "KIK": "OK", "MERSIS": "OK", "HABERLER": "OK"}})
            
            ai_service = AIService()
            parsed_result = {}
            yield _serialize_sse({"type": "status", "message": "Yapay zeka analiz ediyor..."})
            try:
                parsed_result = await asyncio.wait_for(ai_service.generate_trust_report(company.name, news_res + scraped_res, profile_res, branch_context if has_address else None, "mixed"), timeout=90.0)
                yield _serialize_sse({"type": "result", "data": parsed_result})
                stream_terminated = True
            except Exception as exc:
                yield _serialize_sse({"type": "error", "error_code": "ai_failed", "message": str(exc)[:200]})

            if parsed_result:
                _track_background_task(asyncio.create_task(_save_report_background(company_id, parsed_result, {"news": news_res, "profile": profile_res, "scraped_data": scraped_res}, current_user.id)))
        except Exception:
            yield _serialize_sse({"type": "error", "error_code": "provider_stream_failure", "message": "Streaming pipeline failed."})
        finally:
            for task in active_tasks:
                if not task.done(): task.cancel()
            async with app.state.inflight_lock:
                app.state.inflight_report_keys.discard(inflight_key)
            if not stream_terminated:
                with contextlib.suppress(Exception): yield "data: [DONE]\n\n"

    return StreamingResponse(_event_stream(), media_type="text/event-stream")

@app.get("/discover", tags=["Intelligence"])
async def api_discover(q: Optional[str] = None, city: Optional[str] = None, district: Optional[str] = None, offset: int = 0, limit: int = 50, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    db_results = await get_companies_with_latest_report(db, owner_id=current_user.id, offset=offset, limit=limit, q=q, city=city, district=district)
    places_results = []
    if q and settings.google_places_api_key:
        location = " ".join(filter(None, [district, city])).strip()
        try:
            async with MatcherService() as matcher:
                raw = await matcher.search_places(query=q, location=location)
            for r in raw:
                places_results.append({
                    "id": None, "name": r.get("name"), "formatted_address": r.get("formatted_address"),
                    "place_id": r.get("place_id"), "rating": r.get("rating", 0.0),
                    "user_ratings_total": r.get("user_ratings_total", 0), "source": "google_places",
                    "report": None, "lat": r.get("lat"), "lng": r.get("lng"),
                })
        except Exception: pass
    return JSONResponse(content={"count": len(places_results + list(db_results)), "results": places_results + list(db_results)})

@app.post("/market-analysis", tags=["Intelligence"])
async def api_market_analysis(payload: MarketAnalysisRequest, current_user: User = Depends(get_current_user)):
    if not payload.company_name.strip() or not payload.full_address.strip(): raise HTTPException(status_code=422, detail="company_name and full_address required.")
    async def _collect_data():
        async with ScraperService() as svc: return await svc.get_scraped_data(payload.company_name.strip(), full_address=payload.full_address.strip())
    scraped_payload = await _retry_once(_collect_data, timeout_seconds=15)
    scraped_items = scraped_payload.get("items", []) if isinstance(scraped_payload, dict) else []
    
    ai_service = AIService()
    analysis = await _retry_once(lambda: ai_service.generate_market_analysis(company_name=payload.company_name.strip(), news_data=scraped_items, data_source_type="maps_reviews_only" if payload.full_address.strip() else "mixed"), timeout_seconds=120)
    return JSONResponse(content=analysis)

class MarketChatRequest(BaseModel):
    question: str
    context: Optional[dict] = None

@app.post("/market-chat", tags=["Intelligence"])
async def api_market_chat(payload: MarketChatRequest, current_user: User = Depends(get_current_user)):
    if not payload.question.strip(): raise HTTPException(status_code=422, detail="Soru boş olamaz.")
    context_str = f"Firma: {payload.context.get('company_name', 'Bilinmiyor')}\nStratejik Özet: {payload.context.get('stratejik_ozet', '')}"
    prompt = f"Sen SafeTrade AI danışmanısın. Rapor:\n{context_str}\n\nSoru: {payload.question.strip()}"
    try:
        answer = await AIService().ask_market_consultant(prompt)
    except Exception:
        answer = "Şu an yanıt üretilemedi, lütfen tekrar deneyin."
    return JSONResponse(content={"answer": answer})

@app.get("/reports/{report_id}", response_model=ReportResponse, tags=["Reports"])
async def api_get_report(report_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    report = await get_report(db, report_id, owner_id=current_user.id)
    if not report: raise HTTPException(status_code=404, detail="Report not found.")
    return report

@app.get("/reports/{report_id}/pdf", tags=["Reports"])
async def api_download_report_pdf(report_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    report = await get_report(db, report_id, owner_id=current_user.id)
    if not report: raise HTTPException(status_code=404, detail="Report not found.")
    company = await get_company(db, report.company_id, owner_id=current_user.id)
    pdf_path = await PDFService.generate_report_pdf(company.name, int(report.trust_score), {}, report.risk_summary, "Medium")
    return FileResponse(path=pdf_path, filename=os.path.basename(pdf_path), media_type="application/pdf")

@app.post("/alerts", response_model=AlertResponse, status_code=status.HTTP_201_CREATED, tags=["Alerts"])
async def api_create_alert(data: AlertCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return await create_alert(db, user_id=current_user.id, company_name=data.company_name, full_address=data.full_address)

@app.get("/alerts", response_model=List[AlertResponse], tags=["Alerts"])
async def api_list_alerts(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return await get_alerts_by_user(db, user_id=current_user.id)

@app.patch("/alerts/{alert_id}", response_model=AlertResponse, tags=["Alerts"])
async def api_toggle_alert(alert_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    alert = await toggle_alert(db, alert_id=alert_id, user_id=current_user.id)
    if not alert: raise HTTPException(status_code=404, detail="Alert bulunamadı.")
    return alert

@app.delete("/alerts/{alert_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Alerts"])
async def api_delete_alert(alert_id: int, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not await delete_alert(db, alert_id=alert_id, user_id=current_user.id): raise HTTPException(status_code=404, detail="Alert bulunamadı.")

@app.get("/alerts/{alert_id}/unsubscribe", tags=["Alerts"])
async def api_unsubscribe_alert(alert_id: int, db: AsyncSession = Depends(get_db)):
    alert = await get_alert_by_id(db, alert_id=alert_id)
    if not alert: return JSONResponse(status_code=404, content={"message": "Alert bulunamadı."})
    await deactivate_alert(db, alert_id=alert_id)
    return JSONResponse(content={"message": "Otomatik raporlar durduruldu.", "alert_id": alert_id})

frontend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../Kiren"))
if os.path.exists(frontend_path) and not os.environ.get("RAILWAY_ENVIRONMENT"):
    app.mount("/", StaticFiles(directory=frontend_path, html=True), name="frontend")
else:
    @app.get("/")
    async def root():
        return {"message": "SafeTrade AI API is running. Visit https://www.safeai.com.tr"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)