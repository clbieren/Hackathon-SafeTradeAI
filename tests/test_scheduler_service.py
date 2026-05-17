import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.scheduler_service import run_due_alerts

@pytest.fixture
def mock_db():
    with patch('app.database.AsyncSessionLocal') as mock_session_local:
        db_instance = AsyncMock()
        mock_session_local.return_value.__aenter__.return_value = db_instance
        yield db_instance

@pytest.mark.asyncio
@patch('app.repository.get_due_alerts')
async def test_run_due_alerts_no_alerts(mock_get_due_alerts, mock_db):
    mock_get_due_alerts.return_value = []
    
    await run_due_alerts()
    
    mock_get_due_alerts.assert_called_once()
    mock_db.execute.assert_not_called()

@pytest.mark.asyncio
@patch('app.repository.get_due_alerts')
@patch('app.repository.update_alert_after_run')
@patch('app.services.scheduler_service._run_analysis_for_alert')
@patch('app.services.email_service.EmailService')
async def test_run_due_alerts_success(
    mock_email_service, 
    mock_run_analysis, 
    mock_update, 
    mock_get_due_alerts, 
    mock_db
):
    alert_mock = MagicMock()
    alert_mock.id = 1
    alert_mock.company_name = "Test Corp"
    alert_mock.full_address = "Test Addr"
    alert_mock.user_id = 123
    mock_get_due_alerts.return_value = [alert_mock]
    
    user_mock = MagicMock()
    user_mock.email = "test@example.com"
    user_mock.is_active = True
    
    db_result_mock = MagicMock()
    db_result_mock.scalar_one_or_none.return_value = user_mock
    mock_db.execute.return_value = db_result_mock
    
    mock_run_analysis.return_value = {"skor": 100}
    
    email_instance = MagicMock()
    email_instance.send_market_report = AsyncMock()
    mock_email_service.return_value = email_instance
    
    await run_due_alerts()
    
    mock_run_analysis.assert_called_once_with(company_name="Test Corp", full_address="Test Addr")
    email_instance.send_market_report.assert_called_once()
    mock_update.assert_called_once()

@pytest.mark.asyncio
@patch('app.repository.get_due_alerts')
@patch('app.repository.update_alert_after_run')
@patch('app.services.scheduler_service._run_analysis_for_alert')
@patch('app.services.email_service.EmailService')
async def test_run_due_alerts_ai_error(
    mock_email_service, 
    mock_run_analysis, 
    mock_update, 
    mock_get_due_alerts, 
    mock_db
):
    alert_mock1 = MagicMock()
    alert_mock1.id = 1
    alert_mock1.user_id = 123
    
    alert_mock2 = MagicMock()
    alert_mock2.id = 2
    alert_mock2.user_id = 123
    
    mock_get_due_alerts.return_value = [alert_mock1, alert_mock2]
    
    user_mock = MagicMock()
    user_mock.is_active = True
    
    db_result_mock = MagicMock()
    db_result_mock.scalar_one_or_none.return_value = user_mock
    mock_db.execute.return_value = db_result_mock
    
    # First fails, second succeeds
    mock_run_analysis.side_effect = [Exception("AI Error"), {"skor": 100}]
    
    email_instance = MagicMock()
    email_instance.send_market_report = AsyncMock()
    mock_email_service.return_value = email_instance
    
    await run_due_alerts()
    
    # Should be called twice (continues after error)
    assert mock_run_analysis.call_count == 2
    
    # Update shouldn't be called for first, but will be called for the second because the exception is caught in the loop
    # Wait, in the code, if _run_analysis_for_alert throws, it goes to except Exception block and skips update_alert_after_run.
    # Ah, let's check `_run_analysis_for_alert`. It returns None on error, but if it throws an unhandled exception, the alert loop's try/except catches it.
    assert mock_update.call_count == 1

@pytest.mark.asyncio
@patch('app.repository.get_due_alerts')
@patch('app.repository.update_alert_after_run')
@patch('app.services.scheduler_service._run_analysis_for_alert')
@patch('app.services.email_service.EmailService')
async def test_run_due_alerts_email_error(
    mock_email_service, 
    mock_run_analysis, 
    mock_update, 
    mock_get_due_alerts, 
    mock_db
):
    alert_mock1 = MagicMock()
    alert_mock1.id = 1
    alert_mock1.user_id = 123
    
    alert_mock2 = MagicMock()
    alert_mock2.id = 2
    alert_mock2.user_id = 123
    
    mock_get_due_alerts.return_value = [alert_mock1, alert_mock2]
    
    user_mock = MagicMock()
    user_mock.is_active = True
    
    db_result_mock = MagicMock()
    db_result_mock.scalar_one_or_none.return_value = user_mock
    mock_db.execute.return_value = db_result_mock
    
    mock_run_analysis.return_value = {"skor": 100}
    
    email_instance = MagicMock()
    email_instance.send_market_report = AsyncMock(side_effect=[Exception("Email Error"), None])
    mock_email_service.return_value = email_instance
    
    await run_due_alerts()
    
    assert mock_run_analysis.call_count == 2
    assert email_instance.send_market_report.call_count == 2
    # Only the second one successfully reaches update
    assert mock_update.call_count == 1
