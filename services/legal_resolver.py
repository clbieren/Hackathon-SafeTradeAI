"""
legal_resolver.py
=================
Tabela adından → Yasal MERSİS/KİK unvanına ulaşma servisi.

Akış:
  1. Place Details API → website + phone
  2. Website varsa → /kvkk, /iletisim, footer regex  (Ana Hedef)
  3. Bulamazsa → WHOIS fallback                       (Yedek)
  4. Bulamazsa → Telefon dorking
  5. Bulamazsa → None (raporda uyarı)
"""

import asyncio
import logging
import re
import ssl
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Optional, Dict, Any, List

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# SSL doğrulamasını devre dışı bırakan context — bazı Türk siteleri eski TLS kullanıyor
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

_TIMEOUT = httpx.Timeout(10.0, connect=4.0)

# ---------------------------------------------------------------------------
# Regex kalıpları
# ---------------------------------------------------------------------------
_TAX_NO_PATTERN = re.compile(
    r'(?:Vergi\s*(?:Kimlik\s*)?No|V\.N\.|V\.D\.)\s*[:\-]?\s*(\d{10})',
    re.IGNORECASE,
)
_MERSIS_PATTERN = re.compile(
    r'(?:MERSİS|Mersis)\s*(?:No|Numarası)?\s*[:\-]?\s*(\d{16})',
    re.IGNORECASE,
)
# Hem "© 2024 Acme Ltd. Şti." hem "Tüm hakları saklıdır. Acme A.Ş."
_LEGAL_NAME_PATTERN = re.compile(
    r'(?:©|Copyright|Telif|Tüm hakları|hizmetinizde)\s*.{0,40}?'
    r'([\wÇçĞğİıÖöŞşÜü\s&]{3,60}?'
    r'(?:A\.Ş\.|Ltd\.?\s*Şti\.?|San\.?\s*(?:ve\s*)?Tic\.?|Paz\.?\s*Ltd\.?|Turizm\s*A\.Ş\.))',
    re.IGNORECASE,
)
# "Unvan: Acme Gıda Ltd. Şti." tarzı yapılar
_UNVAN_PATTERN = re.compile(
    r'(?:Unvan|Ticaret\s*Unvanı|Firma\s*Adı)\s*[:\-]\s*'
    r'([\wÇçĞğİıÖöŞşÜü\s&\.]{5,80}?'
    r'(?:A\.Ş\.|Ltd\.?\s*Şti\.?|San\.?\s*Tic\.?|Turizm\s*A\.Ş\.))',
    re.IGNORECASE,
)

_SCRAPE_PATHS = [
    "/kvkk",
    "/gizlilik-politikasi",
    "/gizlilik",
    "/iletisim",
    "/hakkimizda",
    "/hakkimizda.html",
    "/iletisim.html",
    "/aydinlatma-metni",
    "/",
]


class LegalResolver:

    def __init__(self, google_api_key: str) -> None:
        self._api_key = google_api_key

    async def resolve(
        self,
        place_id: str,
        company_name: str,
    ) -> Dict[str, Any]:
        """
        Ana çözüm fonksiyonu.
        Döndürür:
          {
            "legal_name":     str | None,
            "tax_number":     str | None,
            "mersis_number":  str | None,
            "confidence":     "high" | "medium" | "low" | "none",
            "source":         str,
          }
        """
        result: Dict[str, Any] = {
            "legal_name": None,
            "tax_number": None,
            "mersis_number": None,
            "confidence": "none",
            "source": "not_found",
        }

        # SSL doğrulamasını kapatan client — Türk sitelerinde handshake hataları yaygın
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            verify=False,  # <-- KIK / bazı Türk site SSL sorununu çözer
        ) as client:

            # ---------------------------------------------------------------
            # Adım 1: Place Details API → website + phone
            # ---------------------------------------------------------------
            place_data = await self._get_place_details(client, place_id)
            website = place_data.get("website")
            phone   = place_data.get("phone")

            logger.info(
                "LegalResolver [%s]: place_details → website=%s | phone=%s",
                company_name, website, phone,
            )

            # ---------------------------------------------------------------
            # Adım 2 (Ana Hedef): Website scraping
            # ---------------------------------------------------------------
            if website:
                scraped = await self._scrape_website(client, website)
                if scraped.get("tax_number") or scraped.get("legal_name"):
                    result.update(scraped)
                    result["confidence"] = "high"
                    result["source"] = f"website:{website}"
                    logger.info("LegalResolver: Web scraping başarılı → %s", result)
                    return result

            # ---------------------------------------------------------------
            # Adım 2.1 (Yedek): WHOIS fallback
            # ---------------------------------------------------------------
            if website:
                domain = self._extract_domain(website)
                whois_name = await self._whois_lookup(client, domain)
                if whois_name:
                    result["legal_name"] = whois_name
                    result["confidence"] = "medium"
                    result["source"] = f"whois:{domain}"
                    logger.info("LegalResolver: WHOIS buldu → %s", whois_name)
                    return result

            # ---------------------------------------------------------------
            # Adım 3: Telefon dorking (Google News RSS)
            # ---------------------------------------------------------------
            if phone:
                dork_name = await self._phone_dork(client, phone, company_name)
                if dork_name:
                    result["legal_name"] = dork_name
                    result["confidence"] = "low"
                    result["source"] = "phone_dork"
                    logger.info("LegalResolver: Dork buldu → %s", dork_name)
                    return result

            # ---------------------------------------------------------------
            # Adım 4: İsim tabanlı MERSİS dork (son şans)
            # ---------------------------------------------------------------
            mersis_name = await self._mersis_name_dork(client, company_name)
            if mersis_name:
                result["legal_name"] = mersis_name
                result["confidence"] = "low"
                result["source"] = "mersis_dork"
                logger.info("LegalResolver: MERSİS dork buldu → %s", mersis_name)
                return result

        logger.warning("LegalResolver: '%s' için yasal unvan doğrulanamadı.", company_name)
        return result

    # -----------------------------------------------------------------------
    # Adım 1 Yardımcısı: Place Details API
    # -----------------------------------------------------------------------
    async def _get_place_details(
        self,
        client: httpx.AsyncClient,
        place_id: str,
    ) -> Dict[str, Any]:
        """
        Google Place Details API — website ve uluslararası telefon çeker.
        FIX: fields parametresine website ve phone alanları açıkça eklendi.
        """
        try:
            resp = await client.get(
                "https://maps.googleapis.com/maps/api/place/details/json",
                params={
                    "place_id": place_id,
                    "fields": "website,formatted_phone_number,international_phone_number",
                    "key": self._api_key,
                    "language": "tr",
                },
            )
            resp.raise_for_status()
            data = resp.json().get("result", {})
            print(f">>> Place Details ham yanıt: {data}")
            return {
                "website": data.get("website"),
                "phone":   data.get("international_phone_number")
                           or data.get("formatted_phone_number"),
            }
        except Exception as exc:
            print(f">>> Place Details HATA: {exc}")
            logger.warning("Place Details API hatası (place_id=%s): %s", place_id, exc)
            return {}

    # -----------------------------------------------------------------------
    # Adım 2 Yardımcısı: Website Scraping
    # -----------------------------------------------------------------------
    async def _scrape_website(
        self,
        client: httpx.AsyncClient,
        website: str,
    ) -> Dict[str, Any]:
        """
        Sitenin KVKK / iletişim sayfalarını regex ile tara.
        Footer'a öncelik ver — vergi no ve unvan genellikle orada olur.
        """
        result: Dict[str, Any] = {
            "legal_name": None,
            "tax_number": None,
            "mersis_number": None,
        }
        base = website.rstrip("/")

        for path in _SCRAPE_PATHS:
            url = base + path
            try:
                resp = await asyncio.wait_for(client.get(url), timeout=8.0)
                print(f">>> Scrape {url} → status={resp.status_code} len={len(resp.text)}")
                if resp.status_code != 200:
                    continue

                soup = BeautifulSoup(resp.text, "html.parser")
                full_text = resp.text

                # Footer önce — en güvenilir yer
                footer = soup.find("footer")
                search_zones: List[str] = []
                if footer:
                    search_zones.append(footer.get_text(" ", strip=True))
                search_zones.append(full_text)  # tüm sayfa fallback

                for zone in search_zones:
                    if not result["tax_number"]:
                        m = _TAX_NO_PATTERN.search(zone)
                        if m:
                            result["tax_number"] = m.group(1)

                    if not result["mersis_number"]:
                        m = _MERSIS_PATTERN.search(zone)
                        if m:
                            result["mersis_number"] = m.group(1)

                    if not result["legal_name"]:
                        m = _UNVAN_PATTERN.search(zone) or _LEGAL_NAME_PATTERN.search(zone)
                        if m:
                            result["legal_name"] = m.group(1).strip()

                if result["tax_number"] or result["mersis_number"]:
                    logger.info(
                        "LegalResolver scrape [%s]: vergi=%s mersis=%s unvan=%s",
                        url, result["tax_number"],
                        result["mersis_number"], result["legal_name"],
                    )
                    return result  # Yeterince güvenilir, dur

            except asyncio.TimeoutError:
                logger.warning("Scrape timeout (8s): %s", url)
            except Exception as exc:
                logger.warning("Scrape hatası %s: %s", url, exc)

        return result

    # -----------------------------------------------------------------------
    # Adım 2.1 Yardımcısı: WHOIS Fallback
    # -----------------------------------------------------------------------
    def _extract_domain(self, website: str) -> str:
        parsed = urllib.parse.urlparse(website)
        host = parsed.netloc or parsed.path
        return host.replace("www.", "").split("/")[0]

    async def _whois_lookup(
        self,
        client: httpx.AsyncClient,
        domain: str,
    ) -> Optional[str]:
        """RDAP protokolü — ücretsiz, key gerektirmez."""
        if not domain:
            return None
        try:
            # Önce RDAP bootstrap'e sor, hangi sunucu sorumlu?
            resp = await client.get(
                f"https://rdap.org/domain/{domain}",
                timeout=6.0,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            
            # entities içinde registrant ara
            for entity in data.get("entities", []):
                roles = entity.get("roles", [])
                if "registrant" not in roles:
                    continue
                vcard = entity.get("vcardArray", [])
                if len(vcard) < 2:
                    continue
                for field in vcard[1]:
                    if field[0] == "org" and field[3]:
                        org = field[3].strip()
                        skip = ("privacy", "proxy", "protect", "redacted", "whoisguard")
                        if len(org) > 3 and not any(k in org.lower() for k in skip):
                            logger.info("RDAP [%s]: org=%s", domain, org)
                            return org
                    if field[0] == "fn" and field[3]:
                        fn = field[3].strip()
                        skip = ("privacy", "proxy", "protect", "redacted")
                        if len(fn) > 3 and not any(k in fn.lower() for k in skip):
                            logger.info("RDAP [%s]: fn=%s", domain, fn)
                            return fn
        except Exception as exc:
            logger.warning("RDAP hatası (%s): %s", domain, exc)
        return None

    # -----------------------------------------------------------------------
    # Adım 3 Yardımcısı: Telefon Dorking
    # -----------------------------------------------------------------------
    async def _phone_dork(
        self,
        client: httpx.AsyncClient,
        phone: str,
        company_name: str,
    ) -> Optional[str]:
        """
        Telefon numarasını Google News RSS üzerinden çoklu sorgu (dorking) ile
        tarayarak yasal unvan bulmaya çalışır.
        """
        clean_phone = re.sub(r'[\s\-\(\)\+]', '', phone).strip()
        local_phone  = clean_phone.lstrip("90")  # Türkiye ülke kodu

        queries = [
            f'"{company_name}" "Ltd. Şti." "Vergi"',
            f'"{company_name}" "A.Ş." şikayet',
            f'"{phone}" "Ltd. Şti."',
            f'"{phone}" "A.Ş."',
            f'"{local_phone}" "Vergi No"',
            f'"{company_name}" site:sicilgazetesi.gtb.gov.tr',
            f'"{company_name}" site:mersis.gtb.gov.tr',
        ]

        for query in queries:
            encoded = urllib.parse.quote_plus(query)
            url = f"https://news.google.com/rss/search?q={encoded}&hl=tr&gl=TR&ceid=TR:tr"
            try:
                resp = await client.get(url, timeout=6.0)
                root = ET.fromstring(resp.content)
                for item in root.findall(".//item")[:5]:
                    title = item.findtext("title") or ""
                    desc  = item.findtext("description") or ""
                    text  = f"{title} {desc}"
                    m = _UNVAN_PATTERN.search(text) or _LEGAL_NAME_PATTERN.search(text)
                    if m:
                        found = m.group(1).strip()
                        logger.info("Phone dork buldu [%s]: %s", query[:40], found)
                        return found
            except Exception as exc:
                logger.warning("Phone dork hatası (%s…): %s", query[:30], exc)

        return None

    # -----------------------------------------------------------------------
    # Adım 4 Yardımcısı: İsim tabanlı MERSİS Dork
    # -----------------------------------------------------------------------
    async def _mersis_name_dork(
        self,
        client: httpx.AsyncClient,
        company_name: str,
    ) -> Optional[str]:
        """
        Tabela adıyla MERSİS / Ticaret Sicil Gazetesi üzerinde dork atar.
        Website'si olmayan küçük işletmeler için son şans.
        """
        queries = [
            f'"{company_name}" site:sicilgazetesi.gtb.gov.tr',
            f'"{company_name}" "Ltd. Şti." OR "A.Ş." Vergi',
            f'"{company_name}" "ticaret sicil"',
        ]
        for query in queries:
            encoded = urllib.parse.quote_plus(query)
            url = f"https://news.google.com/rss/search?q={encoded}&hl=tr&gl=TR&ceid=TR:tr"
            try:
                resp = await client.get(url, timeout=6.0)
                root = ET.fromstring(resp.content)
                for item in root.findall(".//item")[:5]:
                    title = item.findtext("title") or ""
                    desc  = item.findtext("description") or ""
                    text  = f"{title} {desc}"
                    m = _UNVAN_PATTERN.search(text) or _LEGAL_NAME_PATTERN.search(text)
                    if m:
                        found = m.group(1).strip()
                        logger.info("MERSİS dork buldu [%s]: %s", query[:40], found)
                        return found
            except Exception as exc:
                logger.warning("MERSİS dork hatası: %s", exc)
        return None