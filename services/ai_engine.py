import asyncio
import contextlib
import json
import logging
import random
import time
from types import SimpleNamespace
from typing import Any, AsyncGenerator, List, Dict, Tuple, Optional, Union

from pydantic import BaseModel, Field, ValidationError
from google import genai
from google.genai import types as genai_types

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# Sabitler & Şemalar
# ---------------------------------------------------------------------------
_MODEL_NAME = "gemini-2.5-flash"
_AI_TIMEOUT_SECONDS = 90.0
_MAX_RETRIES = 3
_MAX_PROMPT_CHARS = 12000
_MAX_STREAM_CHUNK_CHARS = 2000
_MAX_STREAM_ACCUMULATED_CHARS = 24000
_CIRCUIT_BREAKER_THRESHOLD = 10
_CIRCUIT_BREAKER_COOLDOWN_SECONDS = 60.0

class CompanyAnalysis(BaseModel):
    genel_skor: int = Field(..., description="Diğer üç skorun ortalaması. Kırmızı bayrak varsa maks 50.")
    musteri_memnuniyeti_skoru: int = Field(..., description="Şiddetli müşteri şikayetleri veya kronik mağduriyetler varsa 10-30 arası.")
    kalite_skoru: int = Field(..., description="Operasyonel başarı, ödül vb. durumlarda 80-95 arası.")
    operasyon_ve_yonetisim_skoru: int = Field(..., description="Asla 0 verme! 1-100 arası.")
    risk_summary: str = Field(..., description="Nesnel istihbarat diliyle Türkçe özet.")
    kirmizi_bayraklar: List[str] = Field(default_factory=list)
    guclu_yonler: List[str] = Field(default_factory=list)
    tedarikci_karari: str = Field(default="🟡 Dikkatli Çalışılmalı")
    veri_kaynaklari_durumu: Dict[str, str] = Field(default_factory=dict)
    resmi_sicil_detaylari: str = Field(default="")
    ne_yapmali: List[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}

class CompetitorItem(BaseModel):
    isim: str = Field(..., description="Rakip firma adı")
    puan: float = Field(..., description="Google Maps puanı")
    yorum_sayisi: int = Field(..., description="Toplam yorum sayısı")
    url: str = Field(..., description="Google Maps URL'i")
    sira: int = Field(..., description="Sıralamadaki yeri")
    place_id: str = Field(..., description="Google Place ID")

    model_config = {"extra": "forbid"}

class MarketAnalysisResult(BaseModel):
    pazar_algisi_skoru: int = Field(..., description="0-100 arası genel itibar skoru")
    guclu_yonler: List[str] = Field(..., description="Çıkan iyi haberlerden elde edilen güçlü yönler")
    zayif_yonler: List[str] = Field(..., description="Şikayetlerden ve olumsuz iddialardan elde edilen zayıf yönler")
    ne_yapmali: List[str] = Field(..., description="Acil düzeltilmesi gerekenler (Do's)")
    ne_yapmamali: List[str] = Field(..., description="Kaçınılması gereken hatalar (Don'ts)")
    stratejik_ozet: str = Field(..., description="Genel özet ve CEO'ya mesaj (TÜRKÇE KARAKTERLİ)")
    rakip_analizi: List[str] = Field(..., description="Firmanın mücadele etmesi gereken potansiyel rakip tipleri veya piyasa tehditleri")
    finansal_tavsiyeler: List[str] = Field(..., description="Ciro artırma, maliyet kısma veya ödeme sistemleri hakkında eyleme geçirilebilir finansal tavsiyeler")
    siralama_tablosu: List[CompetitorItem] = Field(..., description="Bölgesel liderlik tablosu")
    birebir_kiyaslama: str = Field(..., description="Hedef işletme ile 1. sıradaki rakibin ismen birebir kıyaslaması")

    model_config = {"extra": "forbid"}

_FALLBACK = {
    "genel_skor": 0,
    "musteri_memnuniyeti_skoru": 0,
    "kalite_skoru": 0,
    "operasyon_ve_yonetisim_skoru": 0,
    "risk_summary": "Analiz başarısız veya veri çekilemedi.",
    "kirmizi_bayraklar": [],
    "guclu_yonler": [],
    "ne_yapmali": [],
    "tedarikci_karari": "🟡 Dikkatli Çalışılmalı",
    "veri_kaynaklari_durumu": {},
    "resmi_sicil_detaylari": "",
}

# ===========================================================================
# AIService
# ===========================================================================
class AIService:
    """
    Google Gemini API kullanarak şirket güven raporu üreten servis.
    Tam asenkron (aio) ve v1 API kararlılığı ile çalışır.
    """

    _provider_failures: int = 0
    _provider_open_until: float = 0.0

    def __init__(self) -> None:
        self._client: Optional[genai.Client] = None
        self._configured: bool = False

    @classmethod
    def _is_circuit_open(cls) -> bool:
        return time.time() < cls._provider_open_until

    @classmethod
    def _record_provider_failure(cls, reason: str) -> None:
        cls._provider_failures += 1
        if cls._provider_failures >= _CIRCUIT_BREAKER_THRESHOLD:
            cls._provider_open_until = time.time() + _CIRCUIT_BREAKER_COOLDOWN_SECONDS
            logger.error(
                "AIService circuit opened for %.1fs after %s failures; last_reason=%s",
                _CIRCUIT_BREAKER_COOLDOWN_SECONDS,
                cls._provider_failures,
                reason,
            )

    @classmethod
    def _record_provider_success(cls) -> None:
        cls._provider_failures = 0
        cls._provider_open_until = 0.0

    def _ensure_configured(self) -> bool:
        if self._configured:
            return True

        if not settings.gemini_api_key:
            logger.warning("AIService: GEMINI_API_KEY tanımlı değil.")
            return False

        try:
            self._client = genai.Client(
                api_key=settings.gemini_api_key,
                http_options={"api_version": "v1beta"}
            )
            self._configured = True
            logger.info("AIService: Gemini (%s) API'ye başarıyla bağlandı.", _MODEL_NAME)
            return True
        except Exception as exc:
            logger.error("Gemini Yapılandırma Hatası: %s", exc)
            return False

    def _build_prompt(
        self,
        company_name: str,
        news_data: List[Dict[str, Any]],
        financial_data: Dict[str, Any],
        branch_context: Optional[Dict[str, Any]] = None,
        data_source_type: str = "mixed",
        data_sources_status: Optional[Dict[str, str]] = None,
    ) -> str:
        red_flag_keywords = ["taciz", "dolandır", "sahte", "skandal", "mağdur", "rezalet"]
        news_text_combined = " ".join(
            [str(item.get("title", "")) + " " + str(item.get("description", "")) for item in news_data]
        ).lower()
        
        has_red_flag = any(kw in news_text_combined for kw in red_flag_keywords)
        
        system_warning = ""
        if has_red_flag:
            system_warning = "\n\nSİSTEM UYARISI: BU ŞİRKET HAKKINDA CİDDİ OLUMSUZLUKLAR TESPİT EDİLMİŞTİR. NÖTR VE GERÇEKÇİ OL! GENEL SKOR VE MÜŞTERİ SKORUNU KESİNLİKLE 40'IN ALTINDA VER VE RİSK ÖZETİNDE SADECE VERİLEN METİNDEKİ SOMUT ŞİKAYETLERİ YAZ!"

        maps_review_instruction = ""
        if data_source_type == "maps_reviews_only":
            maps_review_instruction = (
                "\n\n## 🗺️ VERİ KAYNAĞI: SADECE GOOGLE MAPS KULLANICI YORUMLARI\n"
                "Sana gelen veriler yalnızca Google Maps kullanıcı yorumlarından oluşmaktadır. "
                "Haber ya da basın kaynağı olmadığı için operasyon_ve_yonetisim_skoru'nu 35 olarak ver (veri eksikliği). "
                "Objektif bir skor üret ve risk_summary'de 'Google Maps kullanıcı yorumlarına göre' ifadesini kullan."
            )

        news_summary_parts: List[str] = []
        for i, article in enumerate(news_data[:15], start=1):
            title = article.get("title") or "Başlıksız"
            desc = (article.get("description") or "Açıklama yok")[:200].strip()
            news_summary_parts.append(f"{i}. {title}\n   → {desc}")

        news_block = "\n".join(news_summary_parts) if news_summary_parts else "Haber yok."

        try:
            financial_block = json.dumps(financial_data, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            financial_block = str(financial_data)
            
        if not financial_data or financial_block.strip() == "{}" or financial_block.strip() == "None":
            financial_block = "FİNANSAL VERİ BULUNAMADI (Şirket şeffaf değil)."
        elif len(financial_block) > 3000:
            financial_block = financial_block[:3000] + "\n... (Veri kısaltıldı)"

        branch_block = ""
        if branch_context:
            branch_name = branch_context.get("branch_name", company_name)
            formatted_address = branch_context.get("formatted_address", "Belirtilmedi")
            legal_name = branch_context.get("legal_name")
            tax_number = branch_context.get("tax_number")
            legal_confidence = branch_context.get("legal_confidence", "none")

            legal_block = ""
            if legal_name or tax_number:
                legal_block = f"\n## ✅ YASAL UNVAN BİLGİSİ (Güven Seviyesi: {legal_confidence})\n  - Yasal Unvan : {legal_name or 'Bulunamadı'}\n  - Vergi No    : {tax_number or 'Bulunamadı'}\nBu bilgileri resmi_sicil_detaylari alanına ekle.\n"

            branch_block = f"## ❗ YEREL ŞUBE ANALİZİ MODU\nBu analiz şu spesifik şubeye aittir:\n  - Şube Adı : {branch_name}\n  - Adres    : {formatted_address}\n{legal_block}\nANALİZİNİ TAMAMEN BU ŞUBENİN PERFORMANSINA GÖRE YAP.\n"

        sources_block = ""
        if data_sources_status:
            sources_lines = ["## 📊 Veri Kaynağı Denetim Kutusu"]
            for src, st in data_sources_status.items():
                sources_lines.append(f"  - {src}: {st}")
            sources_block = "\n".join(sources_lines)

        prompt = f"""## 🎯 ANALİZ VERİLERİ VE TALİMATLAR
Sana verilen veriler dışında KESİNLİKLE bilgi üretme.
{sources_block}

{branch_block}

## 📊 ANALİZ VERİLERİ
### 1. FİNANSAL / SİCİL
{financial_block}

### 2. HABERLER VE YORUMLAR
{news_block}
{maps_review_instruction}
{system_warning}

## 🎯 ANALİZ TALEBİ VE FORMATI
Sen uzman bir kurumsal risk analistisin. Yukarıdaki verilere dayanarak '{company_name}' hakkında Türkçe bir güven raporu hazırla.

JSON FORMATI (KESİNLİKLE BU YAPIDA OLMALI):
{{
  "genel_skor": 75,
  "kalite_skoru": 80,
  "musteri_memnuniyeti_skoru": 70,
  "operasyon_ve_yonetisim_skoru": 75,
  "risk_summary": "Özet metin buraya...",
  "guclu_yonler": ["...", "..."],
  "kirmizi_bayraklar": [],
  "ne_yapmali": ["...", "..."],
  "tedarikci_karari": "🟡 Dikkatli Çalışılmalı",
  "resmi_sicil_detaylari": "Sicil özeti buraya..."
}}

TALİMATLAR:
1. SADECE geçerli bir JSON döndür. JSON dışına açıklama yazma.
2. Skorlar 0-100 arası TAM SAYI olmalıdır.
3. 'resmi_sicil_detaylari' alanına KİK, GİB ve MERSİS verilerini özetleyerek yaz.
4. 'guclu_yonler' ve 'kirmizi_bayraklar' KESİNLİKLE boş kalmamalı.
"""
        if len(prompt) > _MAX_PROMPT_CHARS:
            logger.warning("AI prompt truncated from %s to %s chars", len(prompt), _MAX_PROMPT_CHARS)
            return prompt[:_MAX_PROMPT_CHARS]
        return prompt

    async def _call_with_retries(self, operation_name: str, operation):
        if self._is_circuit_open():
            raise RuntimeError("provider_circuit_open")

        last_exc: Optional[Exception] = None
        for attempt in range(_MAX_RETRIES):
            try:
                result = await operation()
                self._record_provider_success()
                return result
            except Exception as exc:
                last_exc = exc
                self._record_provider_failure(str(exc)[:120])
                if attempt == _MAX_RETRIES - 1:
                    break
                backoff = min(4.0, (2 ** attempt) + random.uniform(0.0, 0.3))
                logger.warning("AIService %s retrying attempt=%s backoff=%.2fs error=%s", operation_name, attempt + 1, backoff, exc)
                await asyncio.sleep(backoff)
        raise RuntimeError(f"{operation_name}_failed") from last_exc

    def _extract_text(self, response: Any) -> str:
        raw_text = ""
        try:
            if hasattr(response, "candidates") and response.candidates:
                candidate = response.candidates[0]
                if hasattr(candidate, "content") and candidate.content.parts:
                    raw_text = "".join(part.text for part in candidate.content.parts if hasattr(part, "text") and part.text)
                if hasattr(candidate, "finish_reason"):
                    logger.info("AI Finish Reason: %s", candidate.finish_reason)
            if not raw_text:
                raw_text = getattr(response, "text", "") or ""
        except Exception:
            raw_text = getattr(response, "text", "") or ""

        raw_text = raw_text.strip()
        if "```" in raw_text:
            parts = raw_text.split("```")
            for part in parts:
                cleaned = part.strip()
                if cleaned.startswith("json"): cleaned = cleaned[4:].strip()
                if cleaned.startswith("{") and cleaned.endswith("}"): return cleaned
            raw_text = parts[1].strip()
            if raw_text.startswith("json"): raw_text = raw_text[4:].strip()

        start = raw_text.find("{")
        end = raw_text.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw_text = raw_text[start:end+1]

        if len(raw_text) > _MAX_STREAM_ACCUMULATED_CHARS:
            raw_text = raw_text[:_MAX_STREAM_ACCUMULATED_CHARS]
        return raw_text

    def _safe_parse_company_analysis(self, raw_text: str) -> Dict[str, Any]:
        text = raw_text.strip()
        try:
            if text.startswith("{") and not text.endswith("}"):
                if text.count('"') % 2 != 0: text += '"'
                if not text.endswith("}"):
                    if text.count("[") > text.count("]"): text += "]"
                    text += " }"
            
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                text = text[start:end+1]
            
            text = text.replace(",\n}", "\n}").replace(",}", "}")
            parsed = json.loads(text, strict=False)
        except Exception as e:
            logger.error(f"JSON parse hatası: {e}. Metin: {text[:500]}")
            fallback = _FALLBACK.copy()
            fallback["risk_summary"] = "Analiz raporu oluşturulurken teknik bir sorun oluştu (JSON Parse Error)."
            return fallback

        alan_duzeltme = {
            "operasyon_ve_yonetim_skoru": "operasyon_ve_yonetisim_skoru",
            "operasyon_yonetim_skoru": "operasyon_ve_yonetisim_skoru",
            "musteri_memnuniyet_skoru": "musteri_memnuniyeti_skoru",
            "musteri_memnuniyeti": "musteri_memnuniyeti_skoru",
        }
        for yanlis, dogru in alan_duzeltme.items():
            if yanlis in parsed and dogru not in parsed:
                parsed[dogru] = parsed.pop(yanlis)

        final_data = _FALLBACK.copy()
        for key in final_data.keys():
            if key in parsed: final_data[key] = parsed[key]
        
        try:
            validated = CompanyAnalysis.model_validate(final_data)
            return _validate_and_sanitize(validated.model_dump())
        except ValidationError as exc:
            logger.error("Validation hatası: %s", exc)
            return _validate_and_sanitize(final_data)

    def _safe_parse_market_analysis(self, raw_text: str) -> Dict[str, Any]:
        text = raw_text.strip()
        try:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start: text = text[start:end+1]
            parsed = json.loads(text, strict=False)
        except Exception as e:
            logger.error(f"Market JSON parse hatası: {e}")
            return {
                "pazar_algisi_skoru": 0, "guclu_yonler": [], "zayif_yonler": [],
                "ne_yapmali": [], "ne_yapmamali": [], "stratejik_ozet": "Hata oluştu.",
                "rakip_analizi": [], "finansal_tavsiyeler": [], "siralama_tablosu": [], "birebir_kiyaslama": "Veri yok."
            }
        for field in ["guclu_yonler", "zayif_yonler", "ne_yapmali", "ne_yapmamali", "rakip_analizi", "finansal_tavsiyeler", "siralama_tablosu"]:
            if not isinstance(parsed.get(field), list): parsed[field] = []
        try:
            return MarketAnalysisResult.model_validate(parsed).model_dump()
        except ValidationError:
            return parsed

    async def generate_trust_report(self, company_name: str, news_data: List[Dict[str, Any]], financial_data: Dict[str, Any], branch_context: Optional[Dict[str, Any]] = None, data_source_type: str = "mixed") -> Dict[str, Any]:
        if not self._ensure_configured() or self._client is None: return _FALLBACK.copy()
        prompt = self._build_prompt(company_name, news_data, financial_data, branch_context, data_source_type)
        try:
            response = await self._call_with_retries("generate_trust_report", lambda: asyncio.wait_for(
                self._client.aio.models.generate_content(model=_MODEL_NAME, contents=prompt, config=genai_types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2, max_output_tokens=8192, safety_settings=[
                    genai_types.SafetySetting(category=genai_types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=genai_types.HarmBlockThreshold.BLOCK_NONE),
                    genai_types.SafetySetting(category=genai_types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=genai_types.HarmBlockThreshold.BLOCK_NONE),
                    genai_types.SafetySetting(category=genai_types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=genai_types.HarmBlockThreshold.BLOCK_NONE),
                    genai_types.SafetySetting(category=genai_types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=genai_types.HarmBlockThreshold.BLOCK_NONE),
                ])), timeout=_AI_TIMEOUT_SECONDS))
            return self._safe_parse_company_analysis(self._extract_text(response))
        except Exception as exc:
            logger.error("AIService Hatası: %s", exc)
            fallback = _FALLBACK.copy()
            fallback["risk_summary"] = f"Analiz Hatası: {str(exc)[:100]}"
            return fallback

    async def stream_trust_report(self, company_name: str, news_data: List[Dict[str, Any]], financial_data: Dict[str, Any], branch_context: Optional[Dict[str, Any]] = None, data_source_type: str = "mixed", data_sources_status: Optional[Dict[str, str]] = None) -> AsyncGenerator[str, None]:
        if not self._ensure_configured() or self._client is None:
            yield f"data: {json.dumps({'type': 'error', 'message': 'AI servisi yapılandırılmamış.'}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
            return
        prompt = self._build_prompt(company_name, news_data, financial_data, branch_context, data_source_type, data_sources_status=data_sources_status)
        accumulated = []
        try:
            stream = await self._call_with_retries("stream_trust_report.open_stream", lambda: asyncio.wait_for(
                self._client.aio.models.generate_content_stream(model=_MODEL_NAME, contents=prompt, config=genai_types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2, safety_settings=[
                    genai_types.SafetySetting(category=genai_types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=genai_types.HarmBlockThreshold.BLOCK_NONE),
                    genai_types.SafetySetting(category=genai_types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=genai_types.HarmBlockThreshold.BLOCK_NONE),
                    genai_types.SafetySetting(category=genai_types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=genai_types.HarmBlockThreshold.BLOCK_NONE),
                    genai_types.SafetySetting(category=genai_types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=genai_types.HarmBlockThreshold.BLOCK_NONE),
                ])), timeout=_AI_TIMEOUT_SECONDS))
            async for chunk in stream:
                text = chunk.text
                if text:
                    accumulated.append(text)
                    yield f"data: {json.dumps({'type': 'chunk', 'text': text}, ensure_ascii=False)}\n\n"
            parsed = self._safe_parse_company_analysis(self._extract_text(SimpleNamespace(text="".join(accumulated))))
            yield f"data: {json.dumps({'type': 'result', 'data': parsed}, ensure_ascii=False)}\n\n"
        except Exception as exc:
            fallback = _FALLBACK.copy()
            fallback["risk_summary"] = f"Stream hatası: {str(exc)[:100]}"
            yield f"data: {json.dumps({'type': 'result', 'data': fallback}, ensure_ascii=False)}\n\n"
        finally:
            yield "data: [DONE]\n\n"

    async def generate_market_analysis(self, company_name: str, news_data: List[Dict[str, Any]], data_source_type: str = "mixed", leaderboard_data: Optional[List[Dict[str, Any]]] = None, competitor_reviews: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        if not self._ensure_configured() or self._client is None: return {"pazar_algisi_skoru": 0, "stratejik_ozet": "Hata."}
        
        news_summary_parts = [f"{i}. {a.get('title')}\n   → {str(a.get('description'))[:300]}" for i, a in enumerate(news_data[:20], 1)]
        news_block = "\n".join(news_summary_parts) if news_summary_parts else "Veri yok."
        
        leaderboard_block = json.dumps(leaderboard_data or [], ensure_ascii=False)
        
        prompt = f"""Sen bir işletme koçusun. '{company_name}' işletmesine pazar stratejisi danışmanlığı yapıyorsun.
Aşağıdaki haberler ve rakip verilerine dayanarak bir pazar analizi raporu hazırla.

HABERLER/YORUMLAR:
{news_block}

RAKİP VERİLERİ:
{leaderboard_block}

JSON FORMATI:
{{
  "pazar_algisi_skoru": 80,
  "guclu_yonler": ["...", "..."],
  "zayif_yonler": ["...", "..."],
  "ne_yapmali": ["...", "..."],
  "ne_yapmamali": ["...", "..."],
  "stratejik_ozet": "...",
  "rakip_analizi": ["...", "..."],
  "finansal_tavsiyeler": ["...", "..."],
  "siralama_tablosu": [],
  "birebir_kiyaslama": "..."
}}

TALİMATLAR:
1. SADECE geçerli bir JSON döndür.
2. stratejik_ozet alanında mutlaka TÜRKÇE karakterler kullan.
3. siralama_tablosu'nu rakip verilerinden doldur.
"""
        try:
            response = await self._call_with_retries("generate_market_analysis", lambda: asyncio.wait_for(
                self._client.aio.models.generate_content(model=_MODEL_NAME, contents=prompt, config=genai_types.GenerateContentConfig(response_mime_type="application/json", temperature=0.3, max_output_tokens=8192)), timeout=_AI_TIMEOUT_SECONDS))
            return self._safe_parse_market_analysis(self._extract_text(response))
        except Exception as exc: 
            logger.error(f"Market Analysis Hatası: {exc}")
            return {"pazar_algisi_skoru": 0, "stratejik_ozet": f"Hata: {str(exc)[:100]}"}

    async def ask_market_consultant(self, prompt: str) -> str:
        if not self._ensure_configured() or self._client is None: return "Hata."
        try:
            response = await self._call_with_retries("ask_market_consultant", lambda: asyncio.wait_for(
                self._client.aio.models.generate_content(model=_MODEL_NAME, contents=prompt, config=genai_types.GenerateContentConfig(temperature=0.3, max_output_tokens=2048, safety_settings=[
                    genai_types.SafetySetting(category=genai_types.HarmCategory.HARM_CATEGORY_HATE_SPEECH, threshold=genai_types.HarmBlockThreshold.BLOCK_NONE),
                    genai_types.SafetySetting(category=genai_types.HarmCategory.HARM_CATEGORY_HARASSMENT, threshold=genai_types.HarmBlockThreshold.BLOCK_NONE),
                    genai_types.SafetySetting(category=genai_types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, threshold=genai_types.HarmBlockThreshold.BLOCK_NONE),
                    genai_types.SafetySetting(category=genai_types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, threshold=genai_types.HarmBlockThreshold.BLOCK_NONE),
                    genai_types.SafetySetting(category=genai_types.HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY, threshold=genai_types.HarmBlockThreshold.BLOCK_NONE),
                ])), timeout=60.0))
            return self._extract_text(response)
        except Exception: return "Hata."

def _validate_and_sanitize(data: Dict[str, Any]) -> Dict[str, Any]:
    def safe_int(key: str) -> int:
        try:
            val = int(data.get(key, 0))
            return max(0, min(100, val))
        except (TypeError, ValueError): return 0
    vkd = {str(k): str(v) for k, v in data.get("veri_kaynaklari_durumu", {}).items()} if isinstance(data.get("veri_kaynaklari_durumu"), dict) else {}
    rsd = data.get("resmi_sicil_detaylari", "")
    if isinstance(rsd, dict): rsd = " | ".join([f"{k}: {v}" for k, v in rsd.items()])
    elif not isinstance(rsd, str): rsd = str(rsd)
    return {
        "genel_skor": safe_int("genel_skor"),
        "musteri_memnuniyeti_skoru": safe_int("musteri_memnuniyeti_skoru"),
        "kalite_skoru": safe_int("kalite_skoru"),
        "operasyon_ve_yonetisim_skoru": safe_int("operasyon_ve_yonetisim_skoru") or safe_int("operasyon_ve_yonetim_skoru"),
        "risk_summary": str(data.get("risk_summary", "Özet üretilemedi.")).strip(),
        "kirmizi_bayraklar": [str(x) for x in data.get("kirmizi_bayraklar", []) if x],
        "guclu_yonler": [str(x) for x in data.get("guclu_yonler", []) if x],
        "tedarikci_karari": str(data.get("tedarikci_karari", "🟡 Dikkatli Çalışılmalı")).strip(),
        "veri_kaynaklari_durumu": vkd,
        "resmi_sicil_detaylari": rsd.strip(),
        "ne_yapmali": [str(x) for x in data.get("ne_yapmali", []) if x],
    }