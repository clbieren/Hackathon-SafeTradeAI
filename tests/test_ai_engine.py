import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from app.services.ai_engine import AIService, _FALLBACK, _validate_and_sanitize

@pytest.fixture
def mock_genai_client():
    with patch('app.services.ai_engine.genai.Client') as MockClient:
        client_instance = MagicMock()
        client_instance.aio = AsyncMock()
        client_instance.aio.models = AsyncMock()
        client_instance.aio.models.generate_content = AsyncMock()
        MockClient.return_value = client_instance
        yield client_instance

@pytest.fixture
def ai_service(mock_genai_client):
    service = AIService()
    service._client = mock_genai_client
    service._configured = True
    return service

def test_validate_and_sanitize():
    # Valid data
    valid_data = {
        "genel_skor": 85,
        "musteri_memnuniyeti_skoru": 90,
        "kalite_skoru": "80", # string to int
        "operasyon_ve_yonetisim_skoru": 75,
        "risk_summary": "Test summary",
        "kirmizi_bayraklar": ["Flag 1", None, ""], # Empty strings/None should be filtered
        "tedarikci_karari": "🟢 Tedarik İçin Uygun",
        "veri_kaynaklari_durumu": {"GIB": "OK"}
    }
    sanitized = _validate_and_sanitize(valid_data)
    assert sanitized["kalite_skoru"] == 80
    assert sanitized["kirmizi_bayraklar"] == ["Flag 1"]
    
    # Missing/Invalid data
    invalid_data = {
        "genel_skor": "not an int",
        "musteri_memnuniyeti_skoru": -10, # Should be capped to 0
        "kalite_skoru": 150, # Should be capped to 100
    }
    sanitized = _validate_and_sanitize(invalid_data)
    assert sanitized["genel_skor"] == 0
    assert sanitized["musteri_memnuniyeti_skoru"] == 0
    assert sanitized["kalite_skoru"] == 100
    assert sanitized["risk_summary"] == "Özet üretilemedi."

@pytest.mark.asyncio
async def test_generate_trust_report_valid_json(ai_service):
    valid_json = json.dumps(_FALLBACK)
    response_mock = MagicMock()
    response_mock.text = valid_json
    ai_service._client.aio.models.generate_content.return_value = response_mock

    res = await ai_service.generate_trust_report("Test Corp", [], {})
    assert res["genel_skor"] == _FALLBACK["genel_skor"]

@pytest.mark.asyncio
async def test_generate_trust_report_markdown_json(ai_service):
    markdown_json = f"```json\n{json.dumps(_FALLBACK)}\n```"
    response_mock = MagicMock()
    response_mock.text = markdown_json
    ai_service._client.aio.models.generate_content.return_value = response_mock

    res = await ai_service.generate_trust_report("Test Corp", [], {})
    assert res["genel_skor"] == _FALLBACK["genel_skor"]

@pytest.mark.asyncio
async def test_generate_trust_report_broken_json(ai_service):
    response_mock = MagicMock()
    response_mock.text = "{ \"genel_skor\": 50, \"broken: "
    ai_service._client.aio.models.generate_content.return_value = response_mock

    res = await ai_service.generate_trust_report("Test Corp", [], {})
    # Should fallback on JSONDecodeError
    assert res["genel_skor"] == _FALLBACK["genel_skor"]
    assert "Analiz raporu" in res["risk_summary"]

@pytest.mark.asyncio
async def test_generate_market_analysis_valid_json(ai_service):
    valid_data = {
        "pazar_algisi_skoru": 80,
        "guclu_yonler": [],
        "zayif_yonler": [],
        "ne_yapmali": [],
        "ne_yapmamali": [],
        "stratejik_ozet": "Test",
        "rakip_analizi": [],
        "finansal_tavsiyeler": [],
        "siralama_tablosu": [],
        "birebir_kiyaslama": "Test"
    }
    response_mock = MagicMock()
    response_mock.text = json.dumps(valid_data)
    ai_service._client.aio.models.generate_content.return_value = response_mock

    res = await ai_service.generate_market_analysis("Test Corp", [])
    assert res["pazar_algisi_skoru"] == 80

@pytest.mark.asyncio
async def test_generate_market_analysis_markdown_json(ai_service):
    valid_data = {
        "pazar_algisi_skoru": 75,
        "stratejik_ozet": "Test"
    }
    response_mock = MagicMock()
    response_mock.text = f"```json\n{json.dumps(valid_data)}\n```"
    ai_service._client.aio.models.generate_content.return_value = response_mock

    res = await ai_service.generate_market_analysis("Test Corp", [])
    assert res["pazar_algisi_skoru"] == 75

@pytest.mark.asyncio
async def test_generate_market_analysis_broken_json(ai_service):
    response_mock = MagicMock()
    response_mock.text = "{ \"pazar_algisi_skoru\": 50, "
    ai_service._client.aio.models.generate_content.return_value = response_mock

    res = await ai_service.generate_market_analysis("Test Corp", [])
    assert res["pazar_algisi_skoru"] == 0
    assert "Analiz raporu" in res["stratejik_ozet"]

@pytest.mark.asyncio
async def test_generate_market_analysis_api_error(ai_service):
    ai_service._client.aio.models.generate_content.side_effect = Exception("API Timeout")

    res = await ai_service.generate_market_analysis("Test Corp", [])
    assert res["pazar_algisi_skoru"] == 0
    assert "Hata" in res["stratejik_ozet"]
