"""
API Integration Tests — SIH26017
Tests FastAPI v1 endpoints using TestClient for contract fidelity, pagination, and response structures.
"""

import pytest
from fastapi.testclient import TestClient
from backend.server import app
from backend.security.auth import create_access_token

client = TestClient(app)

@pytest.fixture
def analyst_token():
    return create_access_token(
        user_id="00000000-0000-0000-0000-000000000003",
        email="analyst.gatishakti@gov.in",
        role="ANALYST"
    )

def test_health_and_readiness_endpoints():
    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "healthy"

    res_ready = client.get("/ready")
    assert res_ready.status_code == 200
    assert res_ready.json()["status"] == "ready"
    assert res_ready.json()["database"] == "connected"
    assert res_ready.json()["ml_models_loaded"] is True

def test_summary_telemetry():
    res = client.get("/api/v1/summary")
    assert res.status_code == 200
    kpi = res.json()["kpi"]
    assert kpi["total_projects"] == 1981
    assert kpi["delayed_projects"] == 1267
    assert kpi["delay_rate_pct"] == 64.0
    assert len(res.json()["sectors"]) == 22
    assert len(res.json()["states"]) == 34

def test_paginated_projects_explorer():
    res = client.get("/api/v1/projects?page=1&page_size=10")
    assert res.status_code == 200
    data = res.json()
    assert data["page"] == 1
    assert data["page_size"] == 10
    assert data["total_records"] == 1981
    assert len(data["projects"]) == 10

    # Test filtering by query
    res_search = client.get("/api/v1/projects?q=metro&page=1&page_size=25")
    assert res_search.status_code == 200
    assert res_search.json()["total_records"] > 0

def test_project_detail_with_shap():
    res = client.get("/api/v1/projects/400277")
    assert res.status_code == 200
    data = res.json()
    assert data["project"]["project_code"] == 400277
    assert "ai_intelligence" in data
    ai = data["ai_intelligence"]
    assert "delay_probability_pct" in ai
    assert "shap_factors" in ai
    assert len(ai["shap_factors"]) > 0

def test_predictions_endpoint(analyst_token):
    payload = {
        "sector_name": "Railways",
        "line_ministry": "Ministry of Railways",
        "original_cost_cr": 2500.0,
        "planned_end_year": 2028,
        "planned_end_quarter": 2
    }
    headers = {"Authorization": f"Bearer {analyst_token}"}
    res = client.post("/api/v1/predictions", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "delay_probability_pct" in data
    assert "risk_tier" in data
    assert "shap_factors" in data

@pytest.fixture
def officer_token():
    return create_access_token(
        user_id="00000000-0000-0000-0000-000000000002",
        email="officer.railways@gov.in",
        role="OFFICER"
    )

def test_health_and_readiness_aliases():
    """Verify that both /api/health and /api/v1/health return healthy status."""
    for path in ["/api/health", "/api/v1/health"]:
        res = client.get(path)
        assert res.status_code == 200
        assert res.json()["status"] == "healthy"

    for path in ["/api/ready", "/api/v1/ready"]:
        res = client.get(path)
        assert res.status_code == 200
        assert res.json()["status"] == "ready"

def test_simulations_endpoint(analyst_token):
    payload = {
        "sector_name": "Roads & Highways",
        "line_ministry": "Ministry of Road Transport & Highways",
        "original_cost_cr": 1500.0,
        "planned_end_year": 2027,
        "planned_end_quarter": 2,
        "fast_track_clearance": True,
        "advance_land_row": True,
        "milestone_funding": False
    }
    headers = {"Authorization": f"Bearer {analyst_token}"}
    res = client.post("/api/v1/simulations", json=payload, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert "baseline" in data
    assert "simulated" in data
    assert "impact" in data
    assert "assumptions" in data
    assert len(data["assumptions"]) == 3
    assert data["impact"]["days_saved"] >= 0

def test_alerts_endpoint_schema_and_fields():
    """Verify that alerts contain both standard and Phase 9 compliant field names."""
    res = client.get("/api/v1/alerts?limit=5")
    assert res.status_code == 200
    alerts = res.json()["alerts"]
    assert len(alerts) > 0
    first = alerts[0]
    assert "alert_id" in first
    assert "project_code" in first
    assert "severity" in first
    assert "reason" in first
    assert "assigned_authority" in first
    assert "created_at" in first
    assert "status" in first

def test_alert_creation_and_duplicate_prevention(officer_token):
    """Verify alert creation and duplicate prevention for same project and severity."""
    headers = {"Authorization": f"Bearer {officer_token}"}
    payload = {
        "project_code": 400277,
        "severity": "HIGH",
        "reason": "Automated schedule overrun detected on critical path.",
        "assigned_authority": "Project Monitoring Group (PMG)"
    }
    # First creation should succeed or detect existing
    res1 = client.post("/api/v1/alerts", json=payload, headers=headers)
    assert res1.status_code == 200
    status1 = res1.json()["status"]
    assert status1 in ["CREATED", "DUPLICATE_PREVENTED"]

    # Second creation must be recognized as duplicate
    res2 = client.post("/api/v1/alerts", json=payload, headers=headers)
    assert res2.status_code == 200
    assert res2.json()["status"] == "DUPLICATE_PREVENTED"
