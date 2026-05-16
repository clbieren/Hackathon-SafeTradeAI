"""
external_api.py
===============
Harici API entegrasyon servisleri.

Sınıflar:
    NewsService     — NewsAPI.org üzerinden haber çekimi
    FinnhubService   — Finnhub.io üzerinden şirket profil verisi
    CurrencyService  — ExchangeRate-API üzerinden döviz kurları
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, List, Dict, Tuple, Optional, Union

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# Ortak HTTP istemci timeout yapılandırması
# ---------------------------------------------------------------------------
_TIMEOUT = httpx.Timeout(
    timeout=settings.http_timeout_seconds,
    connect=settings.http_connect_timeout_seconds,
)


# ===========================================================================
# NewsService
# ===========================================================================

class NewsService:
    """NewsAPI.org üzerinden şirkete ait son haberleri çeker."""

    BASE_URL = "https://newsapi.org/v2/everything"

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "NewsService":
        self._client = httpx.AsyncClient(timeout=_TIMEOUT)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client:
            return self._client
        return httpx.AsyncClient(timeout=_TIMEOUT)

    async def get_news(
        self,
        company_name: str,
        page_size: int = 20,
    ) -> List[Dict[str, Any]]:
        """Belirtilen şirket adı için son 7 günün haberlerini döner."""
        if not settings.news_api_key:
            logger.warning("NewsService: NEWS_API_KEY tanımlı değil. Boş liste dönüyor.")
            return []

        seven_days_ago = (
            datetime.now(timezone.utc) - timedelta(days=7)
        ).strftime("%Y-%m-%d")

        params = {
            "q": company_name,
            "from": seven_days_ago,
            "sortBy": "publishedAt",
            "language": "en",
            "pageSize": min(page_size, 20),
            "apiKey": settings.news_api_key,
        }

        client = await self._get_client()
        owned = self._client is None
        try:
            response = await client.get(self.BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()

            if data.get("status") != "ok":
                logger.error("NewsService: API hata yanıtı: %s", data.get("message", "bilinmiyor"))
                return []

            articles = data.get("articles", [])
            logger.info("NewsService: '%s' için %d haber alındı.", company_name, len(articles))
            return articles

        except (httpx.HTTPError, Exception) as exc:
            logger.error("NewsService Hata: %s", str(exc))
            return []
        finally:
            if owned:
                await client.aclose()


# ===========================================================================
# FinnhubService
# ===========================================================================

class FinnhubService:
    """Finnhub.io üzerinden şirket temel (profil) verilerini çeker."""

    BASE_URL = "https://finnhub.io/api/v1/stock/profile2"

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "FinnhubService":
        self._client = httpx.AsyncClient(timeout=_TIMEOUT)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client:
            return self._client
        return httpx.AsyncClient(timeout=_TIMEOUT)

    async def get_company_profile(self, symbol: str) ->Optional[ Dict[str, Any] ]:
        """Borsa sembolüne göre şirket temel verilerini döner."""
        if not settings.finnhub_api_key:
            logger.warning("FinnhubService: FINNHUB_API_KEY tanımlı değil.")
            return None

        params = {
            "symbol": symbol.upper(),
            "token": settings.finnhub_api_key,
        }

        client = await self._get_client()
        owned = self._client is None
        try:
            response = await client.get(self.BASE_URL, params=params)
            response.raise_for_status()
            data = response.json()

            if not data:
                logger.warning("FinnhubService: '%s' için veri bulunamadı.", symbol)
                return None

            return data
        except (httpx.HTTPError, Exception) as exc:
            logger.error("FinnhubService Hata: %s", str(exc))
            return None
        finally:
            if owned:
                await client.aclose()


# ===========================================================================
# CurrencyService
# ===========================================================================

class CurrencyService:
    """ExchangeRate-API üzerinden USD bazlı güncel döviz kurlarını çeker."""

    BASE_URL = "https://v6.exchangerate-api.com/v6/{key}/latest/USD"

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "CurrencyService":
        self._client = httpx.AsyncClient(timeout=_TIMEOUT)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client:
            return self._client
        return httpx.AsyncClient(timeout=_TIMEOUT)

    async def get_rates(self, target_currencies:Optional[ List[str] ] = None) ->Optional[ Dict[str, float] ]:
        """USD karşısındaki güncel döviz kurlarını döner."""
        if not settings.exchange_rate_api_key:
            logger.warning("CurrencyService: EXCHANGE_RATE_API_KEY tanımlı değil.")
            return None

        url = self.BASE_URL.format(key=settings.exchange_rate_api_key)

        client = await self._get_client()
        owned = self._client is None
        try:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

            if data.get("result") != "success":
                return None

            all_rates = data.get("conversion_rates", {})

            if target_currencies:
                requested = [c.upper() for c in target_currencies]
                return {code: rate for code, rate in all_rates.items() if code in requested}

            return all_rates
        except (httpx.HTTPError, Exception) as exc:
            logger.error("CurrencyService Hata: %s", str(exc))
            return None
        finally:
            if owned:
                await client.aclose()

