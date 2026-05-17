"""
matcher_service.py
==================
SafeTrade AI — Google Places API entegrasyonu.

Görevleri:
  1. resolve_entity(target_name, target_address) → verilen isim + adrese en uygun
     Google Maps işletmesini döndürür (place_id, formatted_address, name, rating vb.)
  2. get_place_reviews(place_id) → Place Details API üzerinden son 5 yorumu çeker.
     Bu yorumlar, internet haberi/şikayet bulunamadığında AI'ya fallback veri olarak
     gönderilmek üzere ScrapedItem formatında dönüştürülür.
"""

import difflib
import logging
import math
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, List, Dict, Tuple, Optional, Union

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_PLACES_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
_PLACE_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"
_NEARBY_SEARCH_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"


class MatcherService:
    """
    Google Places API üzerinden işletme eşleştirme ve yorum çekme servisi.
    """

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._api_key:Optional[ str ] = getattr(settings, "google_places_api_key", None)

    async def __aenter__(self) -> "MatcherService":
        self._client = httpx.AsyncClient(timeout=_TIMEOUT)
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Private: Tekrarlayan "owned client" pattern'ini merkezileştir
    # ------------------------------------------------------------------
    @asynccontextmanager
    async def _client_ctx(self) -> AsyncGenerator[httpx.AsyncClient, None]:
        """
        Eğer context manager içinde kullanılıyorsa mevcut client'i döndür.
        Dışarıdaysa geçici bir client açıp kapat.
        Bu sayede 'owned = self._client is None' pattern'i 3 metotta tekrarlanmıyor.
        """
        if self._client:
            yield self._client
        else:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                yield client

    # ------------------------------------------------------------------
    # 1. İşletme Eşleştirme
    # ------------------------------------------------------------------

    async def resolve_entity(
        self,
        target_name: str,
        target_address: str,
    ) -> Dict[str, Any]:
        """
        Verilen işletme adı ve açık adrese göre Google Places'tan en uygun kaydı bulur.
        """
        if not self._api_key:
            logger.warning("MatcherService: GOOGLE_PLACES_API_KEY tanımlı değil.")
            return {}

        query = f"{target_name} {target_address}"
        params = {
            "input": query,
            "inputtype": "textquery",
            # Sadece gerekli alanlar — gereksiz fields billing'i artırır
            "fields": "place_id,name,formatted_address,rating,user_ratings_total,types,geometry",
            "key": self._api_key,
            "language": "tr",
        }

        try:
            async with self._client_ctx() as client:
                resp = await client.get(_PLACES_SEARCH_URL, params=params)
                resp.raise_for_status()
                data = resp.json()

            candidates = data.get("candidates", [])
            if not candidates:
                logger.info("MatcherService: '%s' için eşleşme bulunamadı.", query)
                return {}

            if len(candidates) > 1:
                logger.warning("MatcherService: %d aday bulundu. Conflict döndürülüyor.", len(candidates))
                return {
                    "conflict": True,
                    "candidates": [
                        {"place_id": c.get("place_id"), "name": c.get("name"), "address": c.get("formatted_address")}
                        for c in candidates
                    ],
                }

            best = candidates[0]
            best_name = best.get("name", "")

            if best_name:
                similarity = difflib.SequenceMatcher(None, target_name.lower(), best_name.lower()).ratio()
                if similarity < 0.3:
                    logger.warning(
                        "MatcherService: Benzerlik çok düşük (%.2f). Hedef='%s', Bulunan='%s'. RED.",
                        similarity, target_name, best_name,
                    )
                    return {}

                logger.info(
                    "MatcherService: Eşleşme bulundu (%.2f). Hedef='%s', Bulunan='%s'.",
                    similarity, target_name, best_name,
                )

            geom = best.get("geometry", {}).get("location", {})
            return {
                "place_id": best.get("place_id", ""),
                "name": best_name or target_name,
                "formatted_address": best.get("formatted_address", target_address),
                "rating": best.get("rating"),
                "user_ratings_total": best.get("user_ratings_total"),
                "types": best.get("types", []),
                "lat": geom.get("lat"),
                "lng": geom.get("lng"),
            }

        except Exception as exc:
            logger.error("MatcherService.resolve_entity hatası: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # 2. Google Maps Yorumları (Fallback Veri Kaynağı)
    # ------------------------------------------------------------------

    async def get_competitors_leaderboard(
        self,
        lat: float,
        lng: float,
        place_type: str,
        target_place_id: str,
        radius: int = 2000,
        max_competitors: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Koordinatları ve işletme türünü kullanarak 2km çapında Nearby Search yapar.
        Weighted score ile sıralar: rating * log1p(yorum_sayısı)
        """
        if not self._api_key or not lat or not lng:
            return []

        params = {
            "location": f"{lat},{lng}",
            "radius": radius,
            "type": place_type or "establishment",
            "key": self._api_key,
            "language": "tr",
        }

        try:
            async with self._client_ctx() as client:
                resp = await client.get(_NEARBY_SEARCH_URL, params=params)
                resp.raise_for_status()
                data = resp.json()

            results = data.get("results", [])
            if not results:
                return []

            # Weighted score: rating * log1p(yorum_sayısı)
            # 4.9 ★ / 3 yorum < 4.2 ★ / 1500 yorum — daha güvenilir skor
            def weighted_score(place: dict) -> float:
                r = place.get("rating", 0.0)
                c = place.get("user_ratings_total", 0)
                return r * math.log1p(c)

            sorted_results = sorted(results, key=weighted_score, reverse=True)

            leaderboard: List[dict] = []
            target_rank = -1
            rank = 1
            for place in sorted_results:
                pid = place.get("place_id")
                if pid == target_place_id:
                    target_rank = rank
                    rank += 1
                    continue
                leaderboard.append({
                    "isim": place.get("name", "Bilinmeyen İşletme"),
                    "puan": place.get("rating", 0.0),
                    "yorum_sayisi": place.get("user_ratings_total", 0),
                    "url": f"https://www.google.com/maps/place/?q=place_id:{pid}",
                    "sira": rank,
                    "place_id": pid,
                })
                rank += 1

            logger.info(
                "MatcherService: %d rakip bulundu. Hedef sırası: %s",
                len(leaderboard),
                target_rank if target_rank != -1 else "Bulunamadı",
            )
            return leaderboard[:max_competitors]

        except Exception as exc:
            logger.error("MatcherService.get_competitors_leaderboard hatası: %s", exc)
            return []

    async def get_place_reviews(
        self,
        place_id: str,
        max_reviews: int = 5,
    ) -> List[Dict[str, Any]]:
        """Verilen place_id için Google Place Details API üzerinden son yorumları çeker."""
        if not self._api_key or not place_id:
            logger.warning("MatcherService.get_place_reviews: API anahtarı veya place_id eksik.")
            return []

        params = {
            "place_id": place_id,
            "fields": "name,reviews",
            "key": self._api_key,
            "language": "tr",
            "reviews_sort": "newest",
        }

        try:
            async with self._client_ctx() as client:
                resp = await client.get(_PLACE_DETAILS_URL, params=params)
                resp.raise_for_status()
                data = resp.json()

            raw_reviews = data.get("result", {}).get("reviews", [])[:max_reviews]
            formatted = [
                {
                    "title": f"Google Maps Yorumu — {r.get('author_name', 'Anonim')} ({r.get('rating', 0)}⭐)",
                    "description": r.get("text", "").strip(),
                    "url": r.get("author_url"),
                    "publishedAt": r.get("relative_time_description", ""),
                    "source": "Google Maps",
                    "type": "maps_review",
                    "rating": r.get("rating", 0),
                }
                for r in raw_reviews
                if r.get("text", "").strip()  # boş yorumları filtrele
            ]
            logger.info("MatcherService.get_place_reviews: %d yorum çekildi (place_id=%s).", len(formatted), place_id)
            return formatted

        except Exception as exc:
            logger.error("MatcherService.get_place_reviews hatası: %s", exc)
            return []

    # ------------------------------------------------------------------
    # 3. Toplu İşletme Arama (Growth Hack - Discovery)
    # ------------------------------------------------------------------

    async def search_places(self, query: str, location: str = "") -> List[Dict[str, Any]]:
        """
        Google Places Text Search API kullanarak toplu işletme araması yapar.
        DB'de olmayan firmaları keşfetmek için kullanılır.
        """
        # --- DEBUG: API Key ve parametre kontrolü ---
        if not self._api_key:
            logger.error(
                "[DISCOVER-DEBUG] search_places ATLADI: GOOGLE_PLACES_API_KEY tanımlı değil! "
                "Lütfen .env dosyasında GOOGLE_PLACES_API_KEY değişkenini kontrol edin."
            )
            return []
        if not query:
            logger.warning("[DISCOVER-DEBUG] search_places: query parametresi boş, atlanıyor.")
            return []

        full_query = f"{query} {location}".strip()
        url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        params = {
            "query": full_query,
            "key": self._api_key,
            "language": "tr",
        }

        logger.info(
            "[DISCOVER-DEBUG] search_places isteği: url=%s | query='%s' | api_key_prefix='%s...'",
            url,
            full_query,
            self._api_key[:8] if self._api_key else "YOK",
        )

        try:
            async with self._client_ctx() as client:
                resp = await client.get(url, params=params)

            logger.info(
                "[DISCOVER-DEBUG] search_places HTTP yanıt: status_code=%d",
                resp.status_code,
            )
            resp.raise_for_status()
            data = resp.json()

            # Google kendi API hatasını 200 OK + "status" alanıyla döner
            api_status = data.get("status", "UNKNOWN")
            error_message = data.get("error_message", "")
            logger.info(
                "[DISCOVER-DEBUG] Google API yanıtı: status='%s' | error_message='%s' | sonuç_sayısı=%d",
                api_status,
                error_message,
                len(data.get("results", [])),
            )
            if api_status not in ("OK", "ZERO_RESULTS"):
                logger.error(
                    "[DISCOVER-DEBUG] Google Places API hata kodu: '%s' — Açıklama: '%s'. "
                    "Olası nedenler: hatalı API Key, fatura etkinleştirilmemiş, Places API aktif değil.",
                    api_status,
                    error_message,
                )

            results = data.get("results", [])
            formatted = []
            for r in results:
                location = r.get("geometry", {}).get("location", {})
                formatted.append({
                    "name": r.get("name"),
                    "formatted_address": r.get("formatted_address"),
                    "place_id": r.get("place_id"),
                    "rating": r.get("rating", 0.0),
                    "user_ratings_total": r.get("user_ratings_total", 0),
                    "types": r.get("types", []),
                    "lat": location.get("lat"),
                    "lng": location.get("lng"),
                })

            logger.info(
                "[DISCOVER-DEBUG] search_places tamamlandı: '%s' için %d taze sonuç döndürüldü.",
                full_query, len(formatted),
            )
            return formatted

        except Exception as e:
            logger.error("[DISCOVER-DEBUG] MatcherService.search_places beklenmedik hata: %s", e, exc_info=True)
            return []
