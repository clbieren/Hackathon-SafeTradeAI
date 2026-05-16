from datetime import datetime, timedelta, timezone
from typing import Any, List, Dict, Tuple, Optional, Union
import json
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from app.models import Company, Report, User, UserAlert
from app.schemas import CompanyCreate, CompanyUpdate, ReportCreate, ReportUpdate, UserCreate, AlertCreate

# ---------------------------------------------------------------------------
# Cache TTL — Rapor 7 günden yeniyse yeniden kazıma yapılmaz
# ---------------------------------------------------------------------------
_CACHE_TTL_DAYS = 7


# ===========================================================================
# ŞİRKET (Company) İŞLEMLERİ
# ===========================================================================

async def create_company(db: AsyncSession, data: CompanyCreate, owner_id: Optional["uuid.UUID"] = None) -> Company:
    new_company = Company(**data.model_dump(), owner_id=owner_id)
    db.add(new_company)
    await db.commit()
    await db.refresh(new_company)
    return new_company

async def get_companies(db: AsyncSession, owner_id: "uuid.UUID", offset: int = 0, limit: int = 100):
    result = await db.execute(select(Company).where(Company.owner_id == owner_id).offset(offset).limit(limit))
    return result.scalars().all()

async def get_company(db: AsyncSession, company_id: int, owner_id: "uuid.UUID") ->Optional[ Company ]:
    result = await db.execute(select(Company).where((Company.id == company_id) & (Company.owner_id == owner_id)))
    return result.scalar_one_or_none()

async def update_company(db: AsyncSession, company_id: int, owner_id: "uuid.UUID", data: CompanyUpdate):
    stmt = update(Company).where((Company.id == company_id) & (Company.owner_id == owner_id)).values(**data.model_dump(exclude_unset=True)).returning(Company)
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one_or_none()

async def delete_company(db: AsyncSession, company_id: int, owner_id: "uuid.UUID") -> bool:
    stmt = delete(Company).where((Company.id == company_id) & (Company.owner_id == owner_id))
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0

# ===========================================================================
# RAPOR (Report) İŞLEMLERİ
# ===========================================================================

async def create_report(db: AsyncSession, data: ReportCreate, owner_id: Optional["uuid.UUID"] = None) -> Report:
    new_report = Report(**data.model_dump(), owner_id=owner_id)
    db.add(new_report)
    await db.commit()
    await db.refresh(new_report)
    return new_report

async def get_reports(db: AsyncSession, owner_id: "uuid.UUID", offset: int = 0, limit: int = 100):
    result = await db.execute(select(Report).where(Report.owner_id == owner_id).offset(offset).limit(limit))
    return result.scalars().all()

async def get_report(db: AsyncSession, report_id: int, owner_id: "uuid.UUID") ->Optional[ Report ]:
    result = await db.execute(select(Report).where((Report.id == report_id) & (Report.owner_id == owner_id)))
    return result.scalar_one_or_none()

async def get_reports_by_company(db: AsyncSession, company_id: int, owner_id: "uuid.UUID", offset: int = 0, limit: int = 100):
    result = await db.execute(select(Report).where((Report.company_id == company_id) & (Report.owner_id == owner_id)).offset(offset).limit(limit))
    return result.scalars().all()

async def update_report(db: AsyncSession, report_id: int, data: ReportUpdate):
    stmt = update(Report).where(Report.id == report_id).values(**data.model_dump(exclude_unset=True)).returning(Report)
    result = await db.execute(stmt)
    await db.commit()
    return result.scalar_one_or_none()

async def delete_report(db: AsyncSession, report_id: int, owner_id: "uuid.UUID") -> bool:
    stmt = delete(Report).where((Report.id == report_id) & (Report.owner_id == owner_id))
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0

# ===========================================================================
# AŞAMA 4: AI ANALİZ RAPORU KAYDETME
# ===========================================================================

async def create_company_report(
    db: AsyncSession, 
    company_id: int, 
    ai_data: dict, 
    raw_market_data: dict,
    owner_id: Optional["uuid.UUID"] = None
) -> Report:
    """AI tarafından üretilen analizi veritabanına mühürler."""
    
    # Yeni 4 boyutlu skor sisteminden gelen detayları market_data içine gömüyoruz
    extended_market_data = {
        "raw_data": raw_market_data,
        "ai_detailed_scores": {
            "musteri_memnuniyeti_skoru": ai_data.get("musteri_memnuniyeti_skoru", 0),
            "kalite_skoru": ai_data.get("kalite_skoru", 0),
            "operasyon_ve_yonetisim_skoru": ai_data.get("operasyon_ve_yonetisim_skoru", 0),
            "kirmizi_bayraklar": ai_data.get("kirmizi_bayraklar", []),
            "tedarikci_karari": ai_data.get("tedarikci_karari", "")
        }
    }
    
    trust_score = ai_data.get("genel_skor", 0)
    risk_summary = ai_data.get("risk_summary", "Analiz yapılamadı.")
    market_data_json = json.dumps(extended_market_data, ensure_ascii=False)

    # İdempotency guard: aynı şirket için çok kısa sürede aynı raporu tekrar yazma.
    recent_cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    latest_result = await db.execute(
        select(Report)
        .where(Report.company_id == company_id)
        .order_by(Report.created_at.desc())
        .limit(1)
    )
    latest_report = latest_result.scalar_one_or_none()
    if latest_report and latest_report.created_at:
        latest_dt = latest_report.created_at
        if latest_dt.tzinfo is None:
            latest_dt = latest_dt.replace(tzinfo=timezone.utc)
        if (
            latest_dt >= recent_cutoff
            and float(latest_report.trust_score or 0) == float(trust_score or 0)
            and (latest_report.risk_summary or "").strip() == str(risk_summary).strip()
        ):
            return latest_report

    new_report = Report(
        company_id=company_id,
        trust_score=trust_score,
        risk_summary=risk_summary,
        market_data=market_data_json,
        owner_id=owner_id
    )
    db.add(new_report)
    try:
        await db.commit()
        await db.refresh(new_report)
    except Exception:
        await db.rollback()
        raise
    return new_report


async def get_company_by_name(db: AsyncSession, name: str) ->Optional[ Company ]:
    result = await db.execute(select(Company).where(Company.name.ilike(f"%{name}%")))
    return result.scalars().first()


async def get_company_by_tax(db: AsyncSession, tax_number: str) ->Optional[ Company ]:
    """Vergi numarasına göre şirket arar (tam eşleşme)."""
    result = await db.execute(
        select(Company).where(Company.tax_number == tax_number)
    )
    return result.scalar_one_or_none()


# ===========================================================================
# CACHE KATMANI — 7 Günlük TTL
# ===========================================================================

def _is_fresh(report: Report) -> bool:
    """
    Raporun 7 günden yeni olup olmadığını kontrol eder.
    PostgreSQL timezone-aware datetime, SQLite naive datetime ile uyumlu
    şekilde karşılaştırır.
    """
    if report.created_at is None:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(days=_CACHE_TTL_DAYS)
    # SQLite naive datetime → UTC varsay
    report_dt = report.created_at
    if report_dt.tzinfo is None:
        report_dt = report_dt.replace(tzinfo=timezone.utc)
    return report_dt > cutoff


async def get_fresh_report_by_company(
    db: AsyncSession,
    company_id: int,
) ->Optional[ Report ]:
    """
    Şirketin en güncel raporunu döner.
    Rapor 7 günden eskiyse None dönerek yeniden analiz tetiklenmesini sağlar.

    Cache-first akışı:
        1. DB'de şirket var mı? → get_company
        2. Şirketin raporu var mı ve taze mi? → bu fonksiyon
        3. Taze rapor yoksa → pipeline çalıştır → create_company_report
    """
    result = await db.execute(
        select(Report)
        .where(Report.company_id == company_id)
        .order_by(Report.created_at.desc())
        .limit(1)
    )
    report = result.scalar_one_or_none()
    if report is None:
        return None
    return report if _is_fresh(report) else None


async def get_or_create_company_by_tax(
    db: AsyncSession,
    name: str,
    tax_number: str,
) -> Tuple[Company, bool]:
    """
    Vergi numarasına göre şirket varsa getirir, yoksa oluşturur.

    Returns:
        (company, created)  — created=True ise yeni kayıt oluşturuldu.
    """
    existing = await get_company_by_tax(db, tax_number)
    if existing:
        return existing, False

    new_company = Company(name=name, tax_number=tax_number)
    db.add(new_company)
    await db.commit()
    await db.refresh(new_company)
    return new_company, True


async def create_company_stub(db: AsyncSession, name: str, place_id: str) -> Company:
    """
    Discovery sırasında Maps'te bulunan ama DB'de olmayan firmayı taslak olarak kaydeder.
    Vergi numarası bilinmediği için place_id üzerinden benzersiz bir placeholder üretilir.
    """
    import uuid
    from app.database import AsyncSessionLocal  # döngüsel import önlemek için lazy

    safe_place_id = place_id if place_id else str(uuid.uuid4())
    placeholder_tax = f"MAPS_{safe_place_id}"[:50]

    existing = await get_company_by_tax(db, placeholder_tax)
    if existing:
        return existing

    new_company = Company(name=name, tax_number=placeholder_tax)
    db.add(new_company)
    try:
        await db.commit()
        await db.refresh(new_company)
        return new_company
    except Exception:
        await db.rollback()
        # Race condition / unique constraint: bozuk session'dan bağımsız taze bağlantı aç
        fallback_tax = f"MAPS_{str(uuid.uuid4())}"[:50]
        async with AsyncSessionLocal() as fresh_db:
            fallback_company = Company(name=name, tax_number=fallback_tax)
            fresh_db.add(fallback_company)
            await fresh_db.commit()
            await fresh_db.refresh(fallback_company)
            return fallback_company



async def get_companies_with_latest_report(
    db: AsyncSession,
    owner_id: "uuid.UUID",
    *,
    offset: int = 0,
    limit: int = 50,
    min_score:Optional[ float ] = None,
    max_score:Optional[ float ] = None,
    q:Optional[ str ] = None,
    city:Optional[ str ] = None,
    district:Optional[ str ] = None,
) -> List[Dict[str, Any]]:
    """
    Keşif (discover) endpoint'i için: her şirketi en güncel raporu ile birlikte döner.
    Kademeli filtreleme (Faceted Search) destekler.
    """
    from sqlalchemy import func, cast, String as SqlString  # noqa: PLC0415

    # En son rapor ID'sini bulmak için lateral/subquery
    latest_report_subq = (
        select(
            Report.company_id,
            func.max(Report.created_at).label("max_created_at"),
        )
        .group_by(Report.company_id)
        .subquery()
    )

    stmt = (
        select(Company, Report)
        .outerjoin(
            latest_report_subq,
            Company.id == latest_report_subq.c.company_id,
        )
        .outerjoin(
            Report,
            (Report.company_id == Company.id)
            & (Report.created_at == latest_report_subq.c.max_created_at),
        )
        .where(Company.owner_id == owner_id)
    )

    # --- DİNAMİK FİLTRELEME ---
    
    # 1. Anahtar Kelime (Şirket Adı)
    if q:
        stmt = stmt.where(Company.name.ilike(f"%{q}%"))

    # 2. Skor Filtreleri
    if min_score is not None:
        stmt = stmt.where(Report.trust_score >= min_score)
    if max_score is not None:
        stmt = stmt.where(Report.trust_score <= max_score)

    # 3. Lokasyon Filtreleri (Report.market_data veya official_records içinde arama)
    if city:
        # market_data JSON string olduğu için CAST yapıp arıyoruz veya official_records üzerinden
        stmt = stmt.where(
            (Report.market_data.ilike(f"%{city}%")) | 
            (cast(Report.official_records, SqlString).ilike(f"%{city}%"))
        )
    
    if district:
        stmt = stmt.where(
            (Report.market_data.ilike(f"%{district}%")) | 
            (cast(Report.official_records, SqlString).ilike(f"%{district}%"))
        )

    stmt = stmt.order_by(Report.trust_score.desc().nullslast()).offset(offset).limit(limit)


    rows = await db.execute(stmt)
    result = []
    for company, report in rows.all():
        entry: Dict[str, Any] = {
            "id": company.id,
            "name": company.name,
            "tax_number": company.tax_number,
            "created_at": company.created_at.isoformat(),
            "report": None,
        }
        if report:
            try:
                market_parsed = json.loads(report.market_data) if report.market_data else {}
            except Exception:
                market_parsed = {}
            entry["report"] = {
                "id": report.id,
                "trust_score": float(report.trust_score) if report.trust_score is not None else None,
                "risk_summary": report.risk_summary,
                "official_records": report.official_records,
                "tedarikci_karari": market_parsed.get("ai_detailed_scores", {}).get("tedarikci_karari"),
                "kirmizi_bayraklar": market_parsed.get("ai_detailed_scores", {}).get("kirmizi_bayraklar", []),
                "created_at": report.created_at.isoformat(),
                "is_cached": _is_fresh(report),
            }
        result.append(entry)
    return result


# ===========================================================================
# KULLANICI (User) İŞLEMLERİ
# ===========================================================================

async def get_user_by_email(db: AsyncSession, email: str) -> Optional[User]:
    """E-posta adresine göre kullanıcı arar (tam eşleşme, büyük/küçük harf duyarsız)."""
    result = await db.execute(
        select(User).where(User.email == email.lower())
    )
    return result.scalar_one_or_none()


async def create_user(
    db: AsyncSession,
    email: str,
    hashed_password: str,
    full_name: str,
    company_name: Optional[str] = None,
) -> User:
    """Yeni kullanıcı kaydı oluşturur."""
    new_user = User(
        email=email.lower().strip(),
        hashed_password=hashed_password,
        full_name=full_name.strip(),
        company_name=company_name.strip() if company_name else None,
        role="user",
        is_active=True,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user


# ===========================================================================
# ALERT İŞLEMLERİ (UserAlert)
# ===========================================================================

async def create_alert(
    db: AsyncSession,
    user_id: "uuid.UUID",
    company_name: str,
    full_address: str,
) -> UserAlert:
    """Yeni bir alert kaydı oluşturur. next_run_at = şimdi + 30 gün."""
    next_run = datetime.now(timezone.utc) + timedelta(days=30)
    alert = UserAlert(
        user_id=user_id,
        company_name=company_name.strip(),
        full_address=full_address.strip(),
        is_active=True,
        next_run_at=next_run,
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return alert


async def get_alerts_by_user(
    db: AsyncSession,
    user_id: "uuid.UUID",
) -> List[UserAlert]:
    """Kullanıcıya ait tüm alertleri yeniden yeni sırayla döner."""
    result = await db.execute(
        select(UserAlert)
        .where(UserAlert.user_id == user_id)
        .order_by(UserAlert.created_at.desc())
    )
    return list(result.scalars().all())


async def get_alert(
    db: AsyncSession,
    alert_id: int,
    user_id: "uuid.UUID",
) -> Optional[UserAlert]:
    """Belirli bir alertı sahiplik kontrolü ile getirir."""
    result = await db.execute(
        select(UserAlert).where(
            (UserAlert.id == alert_id) & (UserAlert.user_id == user_id)
        )
    )
    return result.scalar_one_or_none()


async def get_alert_by_id(
    db: AsyncSession,
    alert_id: int,
) -> Optional[UserAlert]:
    """Sadece ID ile alert getirir (unsubscribe için, sahiplik kontrolü yok)."""
    result = await db.execute(
        select(UserAlert).where(UserAlert.id == alert_id)
    )
    return result.scalar_one_or_none()


async def toggle_alert(
    db: AsyncSession,
    alert_id: int,
    user_id: "uuid.UUID",
) -> Optional[UserAlert]:
    """Alert'in is_active durumunu tersine çevirir."""
    alert = await get_alert(db, alert_id, user_id)
    if not alert:
        return None
    alert.is_active = not alert.is_active
    await db.commit()
    await db.refresh(alert)
    return alert


async def delete_alert(
    db: AsyncSession,
    alert_id: int,
    user_id: "uuid.UUID",
) -> bool:
    """Kullanıcıya ait alertı siler."""
    stmt = delete(UserAlert).where(
        (UserAlert.id == alert_id) & (UserAlert.user_id == user_id)
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0


async def get_due_alerts(db: AsyncSession) -> List[UserAlert]:
    """
    Scheduler için: is_active=True ve next_run_at <= now olan alertleri döner.
    alert'e ait user'a lazy load yerine join ile erişmek için ekstra sorgu atılacak.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(UserAlert)
        .where(
            (UserAlert.is_active == True)  # noqa: E712
            & (UserAlert.next_run_at <= now)
        )
        .order_by(UserAlert.next_run_at.asc())
    )
    return list(result.scalars().all())


async def update_alert_after_run(
    db: AsyncSession,
    alert_id: int,
) -> None:
    """Scheduler job'u sonrası last_run_at ve next_run_at günceller."""
    now = datetime.now(timezone.utc)
    stmt = (
        update(UserAlert)
        .where(UserAlert.id == alert_id)
        .values(
            last_run_at=now,
            next_run_at=now + timedelta(days=30),
        )
    )
    await db.execute(stmt)
    await db.commit()


async def deactivate_alert(db: AsyncSession, alert_id: int) -> bool:
    """Unsubscribe için: alertı silmeden devre dışı bırakır."""
    stmt = (
        update(UserAlert)
        .where(UserAlert.id == alert_id)
        .values(is_active=False)
    )
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount > 0
