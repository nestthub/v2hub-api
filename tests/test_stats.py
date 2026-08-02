import pytest
from httpx import AsyncClient, ASGITransport

from v2hub_api.main import app
from v2hub_api.api.endpoints.admin import verify_request_signature, verify_internal_ip
from v2hub_api.api.dependencies import get_stats_service
from v2hub_api.schemas import StatsResponse, GeneralStats, ProviderStats

# 1. Override the security dependencies
app.dependency_overrides[verify_request_signature] = lambda: None
app.dependency_overrides[verify_internal_ip] = lambda: None

# 2. Mock the Database Service so we don't need PostgreSQL running locally
async def mock_stats_service():
    class MockService:
        async def get_statistics(self, start_date=None, end_date=None, period=None):
            # Return fake data instead of querying a real database
            return StatsResponse(
                general=GeneralStats(total_users=100, new_users=10, new_subscriptions=5, new_providers=2),
                providers=ProviderStats(active_providers=50, users_connected_to_providers=80)
            )
    return MockService()

app.dependency_overrides[get_stats_service] = mock_stats_service

@pytest.mark.asyncio
async def test_get_statistics_success():
    """Test the 'Happy Path' - requesting stats without filters should return 200 OK."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/v1/admin/stats")
        
        assert response.status_code == 200
        data = response.json()
        
        assert "general" in data
        # Verify our mock data came through successfully!
        assert data["general"]["total_users"] == 100

@pytest.mark.asyncio
async def test_get_statistics_date_validation():
    """Test the 'Unhappy Path' - the fail-fast date validation mechanism."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            "/api/v1/admin/stats", 
            params={"start_date": "2026-12-31", "end_date": "2026-01-01"}
        )
        
        assert response.status_code == 400
        assert response.json()["detail"] == "start_date cannot be after end_date"