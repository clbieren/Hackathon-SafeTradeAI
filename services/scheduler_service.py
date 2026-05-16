"""
scheduler_service.py — APScheduler ile aylık alert job'u

Her gece 02:00'de çalışarak vadesi gelen alertleri işler:
1. Aktif ve next_run_at <= now olan alertleri çek
2. Her biri için generate_market_analysis() çağır
3. Sonucu Resend ile kullanıcının emailine gönder
4. last_run_at = now, next_run_at = now + 30 gün güncelle

Hata toleransı: her alert kendi try/except bloğunda,
bir tanesi hata alırsa diğerleri etkilenmez.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)


class SchedulerService:
    """
    FastAPI lifespan içinde başlatılıp durdurulacak APScheduler servisi.

    Kullanım (main.py lifespan içinde):
        scheduler = SchedulerService()
        scheduler.start()
        yield
        scheduler.stop()
    """

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler(timezone="Europe/Istanbul")

    def start(self) -> None:
        """Scheduler'ı başlatır ve geceleri 02:00'deki job'u kaydeder."""
        self._scheduler.add_job(
            run_due_alerts,
            trigger=CronTrigger(hour=2, minute=0, timezone="Europe/Istanbul"),
            id="monthly_alert_job",
            name="Aylık Pazar Analizi Alert Job'u",
            replace_existing=True,
            misfire_grace_time=3600,  # 1 saat içinde kaçırılmış job yine de çalışır
        )
        self._scheduler.start()
        logger.info("SchedulerService başlatıldı. Günlük 02:00 (Istanbul) alert job'u aktif.")

    def stop(self) -> None:
        """Scheduler'ı durdurur (graceful shutdown)."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("SchedulerService durduruldu.")


async def run_due_alerts() -> None:
    """
    Vadesi gelmiş tüm alertleri işler.
    Her alert için:
      - ScraperService ile veri topla
      - AIService ile pazar analizi üret
      - EmailService ile email gönder
      - DB'de last_run_at / next_run_at güncelle
    Herhangi bir alertte hata olursa loglanır, diğerleri devam eder.
    """
    from app.database import AsyncSessionLocal
    from app.repository import get_due_alerts, update_alert_after_run, get_user_by_email
    from app.models import User
    from sqlalchemy import select

    logger.info("Alert job başladı.")
    processed = 0
    errors = 0

    try:
        async with AsyncSessionLocal() as db:
            alerts = await get_due_alerts(db)
            logger.info("İşlenecek alert sayısı: %d", len(alerts))

            for alert in alerts:
                try:
                    # Kullanıcı email'ini al
                    user_result = await db.execute(
                        select(User).where(User.id == alert.user_id)
                    )
                    user: Optional[User] = user_result.scalar_one_or_none()
                    if not user or not user.is_active:
                        logger.warning(
                            "Alert ID=%d için kullanıcı bulunamadı veya pasif, atlanıyor.",
                            alert.id,
                        )
                        continue

                    logger.info(
                        "Alert işleniyor: id=%d company=%r user=%s",
                        alert.id, alert.company_name, user.email,
                    )

                    analysis = await _run_analysis_for_alert(
                        company_name=alert.company_name,
                        full_address=alert.full_address,
                    )

                    if analysis:
                        from app.services.email_service import EmailService
                        email_svc = EmailService()
                        await email_svc.send_market_report(
                            to_email=user.email,
                            company_name=alert.company_name,
                            analysis_data=analysis,
                            alert_id=alert.id,
                        )

                    # Her durumda zamanları güncelle (email başarısız olsa da)
                    await update_alert_after_run(db, alert.id)
                    processed += 1
                    logger.info("Alert tamamlandı: id=%d", alert.id)

                except Exception as exc:
                    errors += 1
                    logger.error(
                        "Alert işlenirken hata. id=%d company=%r hata=%s",
                        alert.id, alert.company_name, exc,
                        exc_info=True,
                    )
                    # Diğer alertleri engelleme — devam et

    except Exception as exc:
        logger.error("Alert job genel hatası: %s", exc, exc_info=True)

    logger.info(
        "Alert job tamamlandı. İşlenen=%d Hata=%d", processed, errors
    )


async def _run_analysis_for_alert(
    company_name: str,
    full_address: str,
) -> Optional[dict]:
    """
    Tek bir şirket için scraping + AI analizi çalıştırır.
    Hata durumunda None döner.
    """
    from app.services.scraper_service import ScraperService
    from app.services.ai_engine import AIService

    try:
        async with ScraperService() as scraper:
            scraped_payload = await asyncio.wait_for(
                scraper.get_scraped_data(company_name, full_address=full_address),
                timeout=20.0,
            )
        scraped_items = (
            scraped_payload.get("items", [])
            if isinstance(scraped_payload, dict)
            else []
        )

        ai_service = AIService()
        analysis = await asyncio.wait_for(
            ai_service.generate_market_analysis(
                company_name=company_name,
                news_data=scraped_items,
                data_source_type="maps_reviews_only",
            ),
            timeout=120.0,
        )
        return analysis

    except asyncio.TimeoutError:
        logger.error(
            "Analiz zaman aşımı. company=%r address=%r", company_name, full_address
        )
        return None
    except Exception as exc:
        logger.error(
            "Analiz hatası. company=%r hata=%s", company_name, exc, exc_info=True
        )
        return None
