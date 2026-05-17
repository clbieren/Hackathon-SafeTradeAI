import pytest
from unittest.mock import patch, MagicMock
from app.services.email_service import EmailService, build_market_report_html

@pytest.fixture
def mock_settings():
    with patch('app.config.get_settings') as mock_get_settings:
        settings_mock = MagicMock()
        settings_mock.resend_api_key = "test_api_key"
        settings_mock.frontend_base_url = "http://localhost:3000"
        mock_get_settings.return_value = settings_mock
        yield settings_mock

@pytest.fixture
def email_service(mock_settings):
    return EmailService()

def test_build_market_report_html():
    analysis = {
        "pazar_algisi_skoru": 85,
        "stratejik_ozet": "Test stratejik özet",
        "guclu_yonler": ["Güçlü 1"],
        "zayif_yonler": ["Zayıf 1"],
        "ne_yapmali": ["Yapmalı 1"]
    }
    html = build_market_report_html("Test Corp", analysis, 1, "http://localhost:3000")
    assert "Test Corp" in html
    assert "Test stratejik özet" in html
    assert "85" in html
    assert "Güçlü 1" in html
    assert "Zayıf 1" in html
    assert "Yapmalı 1" in html
    assert "http://localhost:3000/alerts/1/unsubscribe" in html

@pytest.mark.asyncio
@patch('resend.Emails.send')
async def test_send_market_report_success(mock_resend_send, email_service):
    mock_resend_send.return_value = {"id": "test_email_id"}
    
    analysis = {"pazar_algisi_skoru": 50}
    success = await email_service.send_market_report("test@example.com", "Test Corp", analysis, 1)
    
    assert success is True
    mock_resend_send.assert_called_once()
    args = mock_resend_send.call_args[0][0]
    assert args["to"] == ["test@example.com"]
    assert "[SafeTrade AI] Test Corp" in args["subject"]

@pytest.mark.asyncio
@patch('resend.Emails.send')
async def test_send_market_report_error(mock_resend_send, email_service):
    mock_resend_send.side_effect = Exception("API Error")
    
    analysis = {"pazar_algisi_skoru": 50}
    success = await email_service.send_market_report("test@example.com", "Test Corp", analysis, 1)
    
    assert success is False
    mock_resend_send.assert_called_once()

@pytest.mark.asyncio
async def test_send_market_report_no_api_key():
    with patch('app.config.get_settings') as mock_get_settings:
        settings_mock = MagicMock()
        settings_mock.resend_api_key = None
        mock_get_settings.return_value = settings_mock
        
        service = EmailService()
        success = await service.send_market_report("test@example.com", "Test", {}, 1)
        
        assert success is False
