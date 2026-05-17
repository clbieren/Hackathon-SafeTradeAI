import pytest
from app.repository import create_alert

@pytest.mark.asyncio
async def test_create_alert_success(test_client, auth_headers):
    response = await test_client.post(
        "/alerts",
        json={"company_name": "Test Corp", "full_address": "Test Addr"},
        headers=auth_headers
    )
    assert response.status_code == 201
    data = response.json()
    assert data["company_name"] == "Test Corp"
    assert "id" in data

@pytest.mark.asyncio
async def test_create_alert_unauth(test_client):
    response = await test_client.post(
        "/alerts",
        json={"company_name": "Test Corp", "full_address": "Test Addr"}
    )
    assert response.status_code == 401

@pytest.mark.asyncio
async def test_create_alert_missing_field(test_client, auth_headers):
    response = await test_client.post(
        "/alerts",
        json={"company_name": "Test Corp"}, # Missing full_address
        headers=auth_headers
    )
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_get_alerts_empty(test_client, auth_headers):
    response = await test_client.get("/alerts", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []

@pytest.mark.asyncio
async def test_get_alerts_full(test_client, auth_headers, test_db, test_user_id):
    await create_alert(test_db, user_id=test_user_id, company_name="Corp A", full_address="Addr A")
    
    response = await test_client.get("/alerts", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["company_name"] == "Corp A"

@pytest.mark.asyncio
async def test_toggle_alert_success(test_client, auth_headers, test_db, test_user_id):
    alert = await create_alert(test_db, user_id=test_user_id, company_name="Corp A", full_address="Addr A")
    assert alert.is_active is True
    
    response = await test_client.patch(f"/alerts/{alert.id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["is_active"] is False

@pytest.mark.asyncio
async def test_toggle_alert_unauthorized(test_client, auth_headers, test_db):
    import uuid
    # Create an alert for a DIFFERENT user
    other_user_id = uuid.uuid4()
    alert = await create_alert(test_db, user_id=other_user_id, company_name="Corp B", full_address="Addr B")
    
    response = await test_client.patch(f"/alerts/{alert.id}", headers=auth_headers)
    # The toggle_alert repository method checks for ownership, so it returns None -> 404
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_delete_alert_success(test_client, auth_headers, test_db, test_user_id):
    alert = await create_alert(test_db, user_id=test_user_id, company_name="Corp A", full_address="Addr A")
    
    response = await test_client.delete(f"/alerts/{alert.id}", headers=auth_headers)
    assert response.status_code == 204

@pytest.mark.asyncio
async def test_delete_alert_unauthorized(test_client, auth_headers, test_db):
    import uuid
    other_user_id = uuid.uuid4()
    alert = await create_alert(test_db, user_id=other_user_id, company_name="Corp C", full_address="Addr C")
    
    response = await test_client.delete(f"/alerts/{alert.id}", headers=auth_headers)
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_unsubscribe_alert_success(test_client, test_db, test_user_id):
    alert = await create_alert(test_db, user_id=test_user_id, company_name="Corp A", full_address="Addr A")
    
    response = await test_client.get(f"/alerts/{alert.id}/unsubscribe")
    assert response.status_code == 200
    assert "durduruldu" in response.json()["message"]
    
    await test_db.refresh(alert)
    assert alert.is_active is False

@pytest.mark.asyncio
async def test_unsubscribe_alert_nonexistent(test_client):
    response = await test_client.get("/alerts/9999/unsubscribe")
    assert response.status_code == 404
