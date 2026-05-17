import pytest
from app.repository import (
    create_alert, 
    get_alerts_by_user, 
    toggle_alert, 
    delete_alert, 
    get_due_alerts, 
    update_alert_after_run
)
from app.models import UserAlert
from datetime import datetime, timedelta, timezone

@pytest.mark.asyncio
async def test_create_alert(test_db, test_user_id):
    alert = await create_alert(
        test_db, 
        user_id=test_user_id, 
        company_name="Test Corp", 
        full_address="Test Address 123"
    )
    
    assert alert.id is not None
    assert alert.user_id == test_user_id
    assert alert.company_name == "Test Corp"
    assert alert.full_address == "Test Address 123"
    assert alert.is_active is True
    assert alert.next_run_at is not None

@pytest.mark.asyncio
async def test_get_alerts_by_user(test_db, test_user_id):
    await create_alert(test_db, user_id=test_user_id, company_name="Corp A", full_address="Addr A")
    await create_alert(test_db, user_id=test_user_id, company_name="Corp B", full_address="Addr B")
    
    alerts = await get_alerts_by_user(test_db, test_user_id)
    assert len(alerts) == 2
    # Should be ordered by created_at desc
    assert alerts[0].company_name == "Corp B"
    assert alerts[1].company_name == "Corp A"

@pytest.mark.asyncio
async def test_toggle_alert(test_db, test_user_id):
    alert = await create_alert(test_db, user_id=test_user_id, company_name="Corp A", full_address="Addr A")
    assert alert.is_active is True
    
    toggled = await toggle_alert(test_db, alert.id, test_user_id)
    assert toggled.is_active is False
    
    toggled_again = await toggle_alert(test_db, alert.id, test_user_id)
    assert toggled_again.is_active is True

@pytest.mark.asyncio
async def test_delete_alert(test_db, test_user_id):
    alert = await create_alert(test_db, user_id=test_user_id, company_name="Corp A", full_address="Addr A")
    
    deleted = await delete_alert(test_db, alert.id, test_user_id)
    assert deleted is True
    
    alerts = await get_alerts_by_user(test_db, test_user_id)
    assert len(alerts) == 0

@pytest.mark.asyncio
async def test_get_due_alerts(test_db, test_user_id):
    # Alert 1: Due (next_run_at in the past)
    alert1 = await create_alert(test_db, user_id=test_user_id, company_name="Corp Due", full_address="Addr A")
    alert1.next_run_at = datetime.now(timezone.utc) - timedelta(days=1)
    
    # Alert 2: Not due (next_run_at in the future)
    alert2 = await create_alert(test_db, user_id=test_user_id, company_name="Corp Not Due", full_address="Addr B")
    
    # Alert 3: Due but inactive
    alert3 = await create_alert(test_db, user_id=test_user_id, company_name="Corp Due Inactive", full_address="Addr C")
    alert3.next_run_at = datetime.now(timezone.utc) - timedelta(days=1)
    alert3.is_active = False
    
    await test_db.commit()
    
    due_alerts = await get_due_alerts(test_db)
    
    assert len(due_alerts) == 1
    assert due_alerts[0].company_name == "Corp Due"

@pytest.mark.asyncio
async def test_update_alert_after_run(test_db, test_user_id):
    alert = await create_alert(test_db, user_id=test_user_id, company_name="Corp", full_address="Addr")
    old_next_run = alert.next_run_at
    
    await update_alert_after_run(test_db, alert.id)
    
    await test_db.refresh(alert)
    assert alert.last_run_at is not None
    assert alert.next_run_at > old_next_run
