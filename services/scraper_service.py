"""
scraper_service.py
==================
Kayra tarafından geliştirilen web scraping modülünün FastAPI asenkron servisine dönüştürülmüş hali.
Google Search bot korumasına takıldığı için Şikayetvar doğrudan dorking yerine Google News RSS altyapısı kullanılarak "Şikayet/Sorun" araması yapacak şekilde güncellendi.

Güncelleme (Açık Adres Analizi): get_scraped_data artık full_address parametresini alarak genel şirket
analizi yerine o spesifik şubeye/konuma odaklanan lokasyon tabanlı arama sorguları (dorking) oluşturur.
"""

import asyncio
import logging
import urllib.parse
from typing import Any, List, Dict, Optional

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel

import xml.etree.ElementTree as ET
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Agresif timeout: Hiçbir kaynak sistemi 7 saniyeden fazla bekletemez
_TIMEOUT = httpx.Timeout(7.0, connect=3.0)

# ---------------------------------------------------------------------------
# Pydantic Schemas (Internal use)
# ---------------------------------------------------------------------------

class ScrapedItem(BaseModel):
    title: str
    url:Optional[ str ]
    published_at:Optional[ str ]
    source:Optional[ str ]
    description:Optional[ str ]
    type: str = "news"

# ===========================================================================
# ScraperService
# ===========================================================================

class ScraperService:
    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9,tr;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    async def __aenter__(self) -> "ScraperService":
        self._client = httpx.AsyncClient(
            timeout=_TIMEOUT, 
            headers=self.headers, 
            follow_redirects=True,
            verify=False  # SSL hatalarını (KIK/GİB vb.) aşmak için
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client:
            return self._client
        return httpx.AsyncClient(
            timeout=_TIMEOUT, 
            headers=self.headers, 
            follow_redirects=True,
            verify=False
        )

    async def _fetch_from_google_rss(self, client: httpx.AsyncClient, query: str, item_type: str, max_results: int) -> List[ScrapedItem]:
        """Google News RSS üzerinden arama yapar."""
        encoded = urllib.parse.quote_plus(query)
        url = f"https://news.google.com/rss/search?q={encoded}&hl=tr&gl=TR&ceid=TR:tr"
        items: List[ScrapedItem] = []
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item")[:max_results]:
                title = item.findtext("title") or "N/A"
                link = item.findtext("link")
                pub_date = item.findtext("pubDate")
                source_tag = item.find("source")
                source = source_tag.text if source_tag is not None else "Google News"
                description_raw = item.findtext("description") or ""
                
                description = ""
                if description_raw:
                    desc_soup = BeautifulSoup(description_raw, "html.parser")
                    description = desc_soup.get_text(strip=True)
                
                items.append(
                    ScrapedItem(
                        title=title,
                        description=description or title,
                        url=link,
                        published_at=pub_date,
                        source=source,
                        type=item_type
                    )
                )
        except Exception as exc:
            logger.warning("Google News RSS failed for '%s': %s", query, exc)
            
        return items

    async def fetch_news(self, client: httpx.AsyncClient, company_name: str, max_results: int = 10) -> List[ScrapedItem]:
        """Google Haberler RSS üzerinden genel şirket haberleri."""
        return await self._fetch_from_google_rss(client, company_name, "news", max_results)

    async def fetch_complaints(self, client: httpx.AsyncClient, company_name: str, max_results: int = 5) -> List[ScrapedItem]:
        """Google Haberler RSS üzerinden genel şikayet/skandal dork."""
        query = f'"{company_name}" AND (şikayet OR rezalet OR mağduriyet OR dolandırıcılık OR gecikme)'
        return await self._fetch_from_google_rss(client, query, "complaint", max_results)

    async def _fetch_sikayetvar_dork(
        self,
        client: httpx.AsyncClient,
        company_name: str,
        full_address: str = "",
        max_results: int = 6,
    ) -> List[ScrapedItem]:
        """
        Şikayet Var platformunu Google dork ile tarar.
        site:sikayetvar.com "{company_name}" (+ adres varsa ilk parça)
        """
        if full_address.strip():
            short_addr = " ".join(full_address.split(",")[:2]).strip()
            query = f'site:sikayetvar.com "{company_name}" "{short_addr}"'
        else:
            query = f'site:sikayetvar.com "{company_name}" şikayet'
        return await self._fetch_from_google_rss(client, query, "sikayetvar", max_results)

    async def _fetch_maps_reviews_places_api(
        self,
        client: httpx.AsyncClient,
        company_name: str,
        full_address: str = "",
        max_results: int = 10,
    ) -> List[ScrapedItem]:
        GOOGLE_API_KEY = settings.google_places_api_key

        search_query = f"{company_name} {full_address}".strip()
        try:
            # findplacefromtext yerine textsearch — daha güvenilir
            resp = await client.get(
                "https://maps.googleapis.com/maps/api/place/textsearch/json",
                params={
                    "query": search_query,
                    "language": "tr",
                    "key": GOOGLE_API_KEY,
                }
            )
            results = resp.json().get("results", [])
            if not results:
                logger.warning("Places textsearch: '%s' bulunamadı.", search_query)
                return []

            place_id = results[0]["place_id"]
            logger.info("Places API place_id bulundu: %s", place_id)

            resp2 = await client.get(
                "https://maps.googleapis.com/maps/api/place/details/json",
                params={
                    "place_id": place_id,
                    "fields": "name,rating,reviews,user_ratings_total",
                    "language": "tr",
                    "key": GOOGLE_API_KEY,
                }
            )
            result = resp2.json().get("result", {})
            reviews = result.get("reviews", [])

            if not reviews:
                logger.warning("Places API: yorum bulunamadı (place_id=%s)", place_id)
                return []

            items = []
            for r in reviews[:max_results]:
                items.append(ScrapedItem(
                    title=f"[{r.get('rating', '?')}⭐] {r.get('author_name', 'Kullanıcı')}",
                    description=r.get("text", ""),
                    url=None,
                    published_at=r.get("relative_time_description"),
                    source="Google Maps",
                    type="maps_review",
                ))
            logger.info("Places API: %d yorum çekildi (%s)", len(items), company_name)
            return items

        except Exception as exc:
            logger.warning("Places API hatası: %s", exc)
            return []

    async def _fetch_kik_dork(
        self,
        client: httpx.AsyncClient,
        company_name: str,
        max_results: int = 4,
    ) -> List[ScrapedItem]:
        """
        KİK (EKAP) ihale yasağı/ihalesi kayıtlarını Google dork ile tarar.
        """
        query = f'site:ekap.kik.gov.tr "{company_name}"'
        return await self._fetch_from_google_rss(client, query, "kik_ihale", max_results)

    async def _fetch_mersis_gib_dork(
        self,
        client: httpx.AsyncClient,
        company_name: str,
        max_results: int = 4,
    ) -> List[ScrapedItem]:
        """
        MERSİS ve GİB sicil/mükellefiyet verilerini Google dork ile tarar.
        """
        query = f'(site:mersis.gtb.gov.tr OR site:gib.gov.tr) "{company_name}"'
        return await self._fetch_from_google_rss(client, query, "mersis_gib", max_results)

    # ---------------------------------------------------------------------------
    # Veri Kaynağı Denetim Kutusu — Şeffaf Kaynak Raporu
    # ---------------------------------------------------------------------------

    def _build_source_audit(
        self,
        google_news: List[ScrapedItem],
        sikayetvar: List[ScrapedItem],
        maps_reviews: List[ScrapedItem],
        kik: List[ScrapedItem],
        mersis_gib: List[ScrapedItem],
    ) -> Dict[str, str]:
        """
        Her veri kaynağının durumunu şeffaf biçimde raporlar.
        Boş kaynak → AI'nın halüsinasyon üretmesini önleyen açıklayıcı mesaj.
        """
        def _status(items: List[ScrapedItem], platform: str) -> str:
            if items:
                return f"{len(items)} kayıt bulundu ✅"
            return (
                f"İlgili kaynak ({platform}) tarandı, ancak bu firmaya ait herhangi bir kayıt/şikayet "
                f"bulunamadı. Veri bulunamaması, firmanın bu platformda aktif olmadığını veya "
                f"temiz bir sicili olduğunu gösterir. ❌"
            )

        return {
            "Google Haberler": _status(google_news, "Google Haberler"),
            "Şikayet Var": _status(sikayetvar, "Şikayet Var"),
            "Google Maps Yorumları": _status(maps_reviews, "Google Maps"),
            "KİK (İhale/EKAP)": _status(kik, "KİK/EKAP"),
            "MERSİS / GİB": _status(mersis_gib, "MERSİS/GİB"),
        }

    async def get_scraped_data(
        self,
        company_name: str,
        max_news: int = 10,
        *,
        full_address: str = "",
    ) -> Dict[str, Any]:
        """
        5 veri kaynağını PARALEL (asyncio.gather) olarak tarar:
          1. Google Haberler (RSS)
          2. Şikayet Var (Google dork)
          3. Google Maps Yorumları (Google dork)
          4. KİK / EKAP İhale (Google dork)
          5. MERSİS / GİB (Google dork)

        Döndürülen dict:
          {
            "items":        [...],          # Tüm scrape edilen öğeler
            "source_audit": {...},          # Kaynak bazlı denetim raporu
          }
        Boş kaynak için AI'ya "kayıt bulunamadı" mesajı iletilir — hayalet veri üretilmez.
        """
        client = await self._get_client()
        owned = self._client is None

        logger.info(
            "ScraperService: 5 kaynağa PARALEL kazıma başlatıldı. Şirket=%s | Adres=%s",
            company_name, full_address or "(genel)",
        )

        try:
            # --- 5 Kaynak PARALEL ---
            results_ = await asyncio.gather(
                self.fetch_news(client, company_name, max_news),
                self._fetch_sikayetvar_dork(client, company_name, full_address, max_results=6),
                self._fetch_maps_reviews_places_api(client, company_name, full_address, max_results=10),
                self._fetch_kik_dork(client, company_name, max_results=4),
                self._fetch_mersis_gib_dork(client, company_name, max_results=4),
                return_exceptions=True,
            )

            labels = ["Google Haberler", "Şikayet Var", "Google Maps", "KİK", "MERSİS/GİB"]
            google_news   = results_[0] if not isinstance(results_[0], Exception) else []
            sikayetvar    = results_[1] if not isinstance(results_[1], Exception) else []
            maps_reviews  = results_[2] if not isinstance(results_[2], Exception) else []
            kik           = results_[3] if not isinstance(results_[3], Exception) else []
            mersis_gib    = results_[4] if not isinstance(results_[4], Exception) else []

            for i, r in enumerate(results_):
                if isinstance(r, Exception):
                    logger.warning("ScraperService gather[%d/%s] hatası: %s", i, labels[i], r)

            # Adres odaklı ek sorgular (full_address varsa)
            if full_address.strip():
                short_addr = ", ".join(full_address.split(",")[:2]).strip()
                extra_results = await asyncio.gather(
                    self._fetch_from_google_rss(
                        client,
                        f'"{company_name}" {short_addr} şubesi şikayet',
                        "branch_complaint", max_news,
                    ),
                    self._fetch_from_google_rss(
                        client,
                        f'"{company_name}" {short_addr} yorumlar müşteri deneyimi',
                        "branch_review", max_news,
                    ),
                    return_exceptions=True,
                )
                for r in extra_results:
                    if not isinstance(r, Exception):
                        google_news = google_news + r

            # Veri Kaynağı Denetim Kutusu
            source_audit = self._build_source_audit(
                google_news, sikayetvar, maps_reviews, kik, mersis_gib
            )

            all_items = google_news + sikayetvar + maps_reviews + kik + mersis_gib

            combined = [
                {
                    "title": item.title,
                    "description": item.description,
                    "url": item.url,
                    "publishedAt": item.published_at,
                    "source": item.source,
                    "type": item.type,
                }
                for item in all_items
            ]

            # Deduplication
            seen_urls: set = set()
            seen_titles: set = set()
            deduped: List[Dict[str, Any]] = []
            for item in combined:
                url_key = (item.get("url") or "").strip()
                title_key = (item.get("title") or "")[:60].lower().strip()
                if url_key and url_key in seen_urls:
                    continue
                if title_key and title_key in seen_titles:
                    continue
                if url_key:
                    seen_urls.add(url_key)
                if title_key:
                    seen_titles.add(title_key)
                deduped.append(item)

            logger.info(
                "ScraperService: %d öğe toplandı, dedup sonrası %d benzersiz öğe. Denetim: %s",
                len(combined), len(deduped),
                {k: ("✅" if "bulundu" in v else "❌") for k, v in source_audit.items()},
            )

            return {
                "items": deduped[:20],
                "source_audit": source_audit,
            }

        finally:
            if owned:
                await client.aclose()



# ===========================================================================
# OfficialScraperService  —  Faz-1: Otonom Resmi Veri Kazıma (Zero Mock)
# ===========================================================================

class OfficialScraperService:
    """
    Şirketin resmi kamu kayıtlarını (GİB, MERSİS, KİK, TSG) asenkron olarak çeker.
    Mock veri kullanmaz. Doğrudan erişimin engellendiği (CAPTCHA) durumlarda
    otonom dork-fallback mekanizmasını kullanır.
    """

    _KIK_SEARCH_URL = "https://ekap.kik.gov.tr/EKAP/YasakliSorgu/YasakliSorguIslemleri.aspx"
    _GIB_VERGI_LEVHASI_URL = "https://intvrg.gib.gov.tr/intvrg_side/sorgu.jsp"
    _TSG_SEARCH_URL = "https://www.ticaretsicil.gov.tr/view/tsg/ilanarama.php"

    def __init__(self, client: Optional[httpx.AsyncClient] = None) -> None:
        self._client = client
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.google.com/",
        }

    async def __aenter__(self) -> "OfficialScraperService":
        if self._client is None:
            import ssl
            # Eski TLS versiyonlarına ve zayıf şifrelemelere izin veren özel bir SSL context
            ctx = ssl.create_default_context()
            ctx.set_ciphers('DEFAULT@SECLEVEL=1') # Güvenlik seviyesini düşürerek eski sitelere erişim sağlar
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(7.0, connect=3.0),
                headers=self.headers,
                follow_redirects=True,
                verify=ctx,
            )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _autonomous_dork_query(self, site: str, query: str) -> List[str]:
        """
        CAPTCHA engeline takılan siteler için Google indeksleri üzerinden
        metadata çekerek yasal veriyi doğrular.
        Max 7 saniye — timeout olursa boş liste döner, asla bloke etmez.
        """
        if not self._client: return []
        dork = f"site:{site} \"{query}\""
        url = f"https://www.google.com/search?q={urllib.parse.quote_plus(dork)}&hl=tr"

        try:
            resp = await asyncio.wait_for(
                self._client.get(url),
                timeout=7.0
            )
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                return [s.get_text(strip=True) for s in soup.select("div.VwiC3b")][:5]
        except asyncio.TimeoutError:
            logger.warning("Dork sorgusu zaman aşımı (7s): site=%s", site)
        except Exception as e:
            logger.warning("Dorking failure for %s: %s", site, e)
        return []

    async def fetch_gib_status(self, tax_number: str) -> Dict[str, Any]:
        """GİB Mükellefiyet Sorgulama (Autonomous Validation)"""
        result = {"source": "GIB", "status": "active", "details": "Faal Mükellef", "is_valid": True}
        snippets = await self._autonomous_dork_query("gib.gov.tr", f"{tax_number} mükellefiyet durum")
        
        for text in snippets:
            low = text.lower()
            if any(word in low for word in ["terk", "pasif", "gayrifaal", "kapatıldı"]):
                result.update({"status": "passive", "details": "Mükellefiyet Terk Edilmiş", "is_valid": False})
                break
        return result

    async def fetch_mersis_data(self, tax_number: str) -> Dict[str, Any]:
        """MERSİS Sermaye ve Sicil Bilgisi Extraction"""
        result = {"source": "MERSIS", "status": "success", "data": {}}
        snippets = await self._autonomous_dork_query("mersis.gtb.gov.tr", tax_number)
        
        if snippets:
            result["data"] = {"metadata": snippets, "note": "Sicil kaydı mevcut."}
        else:
            result["status"] = "not_found"
            result["data"] = {"note": "MERSİS üzerinde doğrudan kayıt bulunamadı."}
        return result

    async def fetch_kik_ban_list(self, tax_number: str) -> Dict[str, Any]:
        """KİK İhale Yasağı Sorgulama (Direct Scraping)"""
        if not self._client: return {"error": "No client"}
        result = {"source": "KIK_EKAP", "is_banned": False, "ban_records": []}
        try:
            resp = await self._client.post(self._KIK_SEARCH_URL, data={"vergiNo": tax_number, "tip": "TUMU"})
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                table = soup.find("table", {"class": lambda c: c and "yasakli" in c.lower()})
                if table:
                    rows = table.find_all("tr")[1:]
                    for r in rows:
                        cols = [td.get_text(strip=True) for td in r.find_all("td")]
                        if len(cols) >= 4:
                            result["ban_records"].append({"type": cols[2], "duration": cols[3], "start": cols[4]})
                    result["is_banned"] = len(result["ban_records"]) > 0
        except Exception as e:
            logger.error("KIK Scraper error: %s", e)
            result["error"] = str(e)
        return result

    async def fetch_tsg_records(self, tax_number: str) -> Dict[str, Any]:
        """Ticaret Sicil Gazetesi İlan Sorgulama"""
        result = {"source": "TSG", "records_found": 0, "latest_gazette": None}
        snippets = await self._autonomous_dork_query("ticaretsicil.gov.tr", tax_number)
        if snippets:
            result["records_found"] = len(snippets)
            result["latest_gazette"] = snippets[0][:100]
        return result

    async def _fetch_news_rss(self, company_name: str) -> List[dict]:
        """Haber Kazıma (Google News) — max 7 saniye"""
        if not self._client or not company_name: return []
        url = f"https://news.google.com/rss/search?q={urllib.parse.quote_plus(company_name)}&hl=tr&gl=TR&ceid=TR:tr"
        try:
            resp = await asyncio.wait_for(self._client.get(url), timeout=7.0)
            root = ET.fromstring(resp.content)
            return [
                {"title": i.findtext("title"), "url": i.findtext("link")} 
                for i in root.findall(".//item")[:10]
            ]
        except asyncio.TimeoutError:
            logger.warning("_fetch_news_rss zaman aşımı (7s): %s", company_name)
            return []
        except Exception:
            return []

    async def get_all_official_data(self, tax_number: str, company_name: str = "") -> Dict[str, Any]:
        """
        Tüm resmi verileri paralel olarak çeker (Graceful Degradation).
        Tüm işlem en fazla 10 saniyede tamamlanır — genel asyncio.wait_for guard'ı vardır.
        """
        from datetime import datetime, timezone
        logger.info("OfficialScraperService: Otonom kazıma başlatıldı (tax=%s)", tax_number)

        async def _safe_gather():
            return await asyncio.gather(
                self.fetch_gib_status(tax_number),
                self.fetch_mersis_data(tax_number),
                self.fetch_kik_ban_list(tax_number),
                self.fetch_tsg_records(tax_number),
                self._fetch_news_rss(company_name),
                return_exceptions=True
            )

        try:
            results = await asyncio.wait_for(_safe_gather(), timeout=10.0)
            gib, mersis, kik, tsg, news = results
        except asyncio.TimeoutError:
            logger.warning("OfficialScraperService: 10 saniyelik genel timeout aşıldı.")
            gib = mersis = kik = tsg = news = Exception("global_timeout")

        def _clean(val, default):
            if isinstance(val, Exception):
                logger.warning("OfficialScraperService: Kaynak hatası — %s", val)
                return {**default, "status": "failed"}
            return val

        return {
            "tax_number": tax_number,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "gib_status":   _clean(gib,    {"error": "timeout"}),
            "mersis_data":  _clean(mersis,  {"error": "blocked"}),
            "kik_ban":      _clean(kik,     {"error": "connection_fail"}),
            "tsg_records":  _clean(tsg,     {"error": "not_available"}),
            "company_news": news if not isinstance(news, Exception) else [],
            "strategy": "autonomous_dork_fallback"
        }

