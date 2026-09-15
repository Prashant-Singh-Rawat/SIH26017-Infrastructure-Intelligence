import pytest
from fastapi.testclient import TestClient
from backend.server import app

client = TestClient(app)

def get_auth_token(role="NATIONAL_ADMIN"):
    res = client.post(f"/api/v1/auth/demo-token?role={role}")
    assert res.status_code == 200
    return res.json()["access_token"]

def test_evaluator_valid_normal_project():
    token = get_auth_token("NATIONAL_ADMIN")
    payload = {
        "sector_name": "Roads & Highways",
        "line_ministry": "Ministry of Road Transport & Highways",
        "original_cost_cr": 2500.0,
        "planned_end_year": 2028,
        "current_land_stage": "STAGE_COMPENSATION",
        "land_required_acres": 125.0,
        "land_acquired_pct": 52.0,
        "compensation_disbursed_pct": 42.0,
        "active_legal_disputes": 2,
        "affected_families_count": 180,
        "rehabilitation_package_cr": 8.5
    }
    res = client.post("/api/v1/predictions", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert "risk_tier" in data
    assert "Risk" in data["risk_tier"]
    assert data["delay_probability_pct"] >= 0 and data["delay_probability_pct"] <= 100
    assert data["estimated_delay_days"] >= 0
    assert data["bottleneck_stage_id"] in ["COMPENSATION", "STAGE_COMPENSATION"]
    assert "shap_factors" in data
    assert len(data["shap_factors"]) > 0

def test_evaluator_land_acquired_zero_pct():
    token = get_auth_token("NATIONAL_ADMIN")
    payload = {
        "sector_name": "Railways",
        "line_ministry": "Ministry of Railways",
        "original_cost_cr": 3500.0,
        "planned_end_year": 2029,
        "current_land_stage": "STAGE_VALUATION",
        "land_required_acres": 200.0,
        "land_acquired_pct": 0.0,
        "compensation_disbursed_pct": 0.0,
        "active_legal_disputes": 0,
        "affected_families_count": 50,
        "rehabilitation_package_cr": 2.0
    }
    res = client.post("/api/v1/predictions", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert "bottleneck_stage_id" in data
    assert data["delay_probability_pct"] >= 0

def test_evaluator_land_acquired_100_pct():
    token = get_auth_token("NATIONAL_ADMIN")
    payload = {
        "sector_name": "Power",
        "line_ministry": "Ministry of Power",
        "original_cost_cr": 1200.0,
        "planned_end_year": 2027,
        "current_land_stage": "STAGE_POSSESSION",
        "land_required_acres": 80.0,
        "land_acquired_pct": 100.0,
        "compensation_disbursed_pct": 100.0,
        "active_legal_disputes": 0,
        "affected_families_count": 0,
        "rehabilitation_package_cr": 0.0
    }
    res = client.post("/api/v1/predictions", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    data = res.json()
    assert "Risk" in data["risk_tier"]

def test_evaluator_compensation_zero_vs_100():
    token = get_auth_token("NATIONAL_ADMIN")
    base = {
        "sector_name": "Roads & Highways",
        "line_ministry": "Ministry of Road Transport & Highways",
        "original_cost_cr": 2000.0,
        "planned_end_year": 2028,
        "current_land_stage": "STAGE_COMPENSATION",
        "land_required_acres": 100.0,
        "land_acquired_pct": 50.0,
        "active_legal_disputes": 0,
        "affected_families_count": 100,
        "rehabilitation_package_cr": 5.0
    }
    res0 = client.post("/api/v1/predictions", json={**base, "compensation_disbursed_pct": 0.0}, headers={"Authorization": f"Bearer {token}"})
    assert res0.status_code == 200
    data0 = res0.json()

    res100 = client.post("/api/v1/predictions", json={**base, "compensation_disbursed_pct": 100.0}, headers={"Authorization": f"Bearer {token}"})
    assert res100.status_code == 200
    data100 = res100.json()

    # Disbursing 100% compensation should yield equal or lower delay probability than 0%
    assert data100["delay_probability_pct"] <= data0["delay_probability_pct"]

def test_evaluator_high_legal_disputes_escalates_risk():
    token = get_auth_token("NATIONAL_ADMIN")
    base = {
        "sector_name": "Roads & Highways",
        "line_ministry": "Ministry of Road Transport & Highways",
        "original_cost_cr": 2000.0,
        "planned_end_year": 2028,
        "current_land_stage": "STAGE_LEGAL_DISPUTES",
        "land_required_acres": 150.0,
        "land_acquired_pct": 40.0,
        "compensation_disbursed_pct": 30.0,
        "affected_families_count": 120,
        "rehabilitation_package_cr": 4.0
    }
    res_low = client.post("/api/v1/predictions", json={**base, "active_legal_disputes": 0}, headers={"Authorization": f"Bearer {token}"})
    assert res_low.status_code == 200

    res_high = client.post("/api/v1/predictions", json={**base, "active_legal_disputes": 8}, headers={"Authorization": f"Bearer {token}"})
    assert res_high.status_code == 200
    data_high = res_high.json()

    assert data_high["bottleneck_stage_id"] in ["LEGAL_DISPUTES", "STAGE_LEGAL_DISPUTES"]
    assert data_high["bottleneck_severity"] == "CRITICAL"

def test_evaluator_invalid_negative_cost():
    token = get_auth_token("NATIONAL_ADMIN")
    payload = {
        "sector_name": "Roads & Highways",
        "line_ministry": "Ministry of Road Transport & Highways",
        "original_cost_cr": -500.0,
        "planned_end_year": 2028
    }
    res = client.post("/api/v1/predictions", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 422

def test_evaluator_invalid_percentage_bounds():
    token = get_auth_token("NATIONAL_ADMIN")
    # > 100%
    res_over = client.post("/api/v1/predictions", json={
        "sector_name": "Roads & Highways",
        "line_ministry": "Ministry of Road Transport & Highways",
        "original_cost_cr": 1000.0,
        "planned_end_year": 2028,
        "land_acquired_pct": 120.0
    }, headers={"Authorization": f"Bearer {token}"})
    assert res_over.status_code == 422

    # < 0%
    res_under = client.post("/api/v1/predictions", json={
        "sector_name": "Roads & Highways",
        "line_ministry": "Ministry of Road Transport & Highways",
        "original_cost_cr": 1000.0,
        "planned_end_year": 2028,
        "land_acquired_pct": -5.0
    }, headers={"Authorization": f"Bearer {token}"})
    assert res_under.status_code == 422

def test_evaluator_missing_required_field():
    token = get_auth_token("NATIONAL_ADMIN")
    payload = {
        "original_cost_cr": 1000.0
        # missing sector_name, line_ministry, and planned_end_year
    }
    res = client.post("/api/v1/predictions", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 422

def test_evaluator_auditor_read_only_can_evaluate():
    token = get_auth_token("AUDITOR")
    payload = {
        "sector_name": "Roads & Highways",
        "line_ministry": "Ministry of Road Transport & Highways",
        "original_cost_cr": 1500.0,
        "planned_end_year": 2027,
        "land_required_acres": 50.0,
        "land_acquired_pct": 80.0,
        "compensation_disbursed_pct": 75.0
    }
    res = client.post("/api/v1/predictions", json=payload, headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert "risk_tier" in res.json()
