import pytest
from fastapi.testclient import TestClient
from backend.server import app
from backend.security.auth import create_access_token

client = TestClient(app)

@pytest.fixture
def viewer_token():
    return create_access_token(
        user_id="00000000-0000-0000-0000-000000000004",
        email="viewer.public@gov.in",
        role="VIEWER"
    )

@pytest.fixture
def officer_token():
    return create_access_token(
        user_id="00000000-0000-0000-0000-000000000002",
        email="officer.railways@gov.in",
        role="OFFICER"
    )

@pytest.fixture
def admin_token():
    return create_access_token(
        user_id="00000000-0000-0000-0000-000000000001",
        email="director.infra@mospi.gov.in",
        role="ADMIN"
    )

def test_1_project_loads_correctly():
    """TEST 1: Active project dossier loads valid registered project data from DB."""
    res = client.get("/api/v1/projects/705728")
    assert res.status_code == 200
    data = res.json()
    p = data["project"]
    assert p["project_code"] == 705728
    assert "Mumbai-Ahmedabad" in p["project_name"]
    assert p["sector_name"] == "Railways"
    assert p["original_cost_cr"] == 108000
    assert p["schedule_delay_days"] == 853.0

def test_2_baseline_values_displayed(officer_token):
    """TEST 2: Baseline values match project records and no undefined or NaN values exist."""
    payload = {
        "project_code": 705728,
        "sector_name": "Railways",
        "line_ministry": "Ministry of Railways",
        "original_cost_cr": 108000,
        "planned_end_year": 2029,
        "planned_end_quarter": 4,
        "fast_track_clearance": False,
        "advance_land_row": False,
        "milestone_funding": False,
        "resolve_disputes": False,
        "dbt_compensation_release": False,
        "drone_possession_handover": False
    }
    res = client.post("/api/v1/simulations", json=payload, headers={"Authorization": f"Bearer {officer_token}"})
    assert res.status_code == 200
    data = res.json()
    base = data["baseline"]
    assert base["estimated_delay_days"] == 853
    assert base["cost_cr"] == 108000.0
    assert "risk_tier" in base

def test_3_no_intervention_projected_equals_baseline(officer_token):
    """TEST 3: When 0 interventions are selected, projected delay == baseline and days saved == 0."""
    payload = {
        "project_code": 705728,
        "sector_name": "Railways",
        "line_ministry": "Ministry of Railways",
        "original_cost_cr": 108000,
        "planned_end_year": 2029,
        "planned_end_quarter": 4,
        "fast_track_clearance": False,
        "advance_land_row": False,
        "milestone_funding": False,
        "resolve_disputes": False,
        "dbt_compensation_release": False,
        "drone_possession_handover": False
    }
    res = client.post("/api/v1/simulations", json=payload, headers={"Authorization": f"Bearer {officer_token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["simulated"]["estimated_delay_days"] == data["baseline"]["estimated_delay_days"]
    assert data["impact"]["days_saved"] == 0
    assert data["impact"]["cost_averted_cr"] == 0.0
    assert data["institutional_directive"]["recommended_action"] == "Maintain Baseline Statutory Monitoring"

def test_4_select_one_intervention(officer_token):
    """TEST 4: Selecting 1 intervention changes the result correctly."""
    payload = {
        "project_code": 705728,
        "sector_name": "Railways",
        "line_ministry": "Ministry of Railways",
        "original_cost_cr": 108000,
        "planned_end_year": 2029,
        "planned_end_quarter": 4,
        "fast_track_clearance": False,
        "advance_land_row": True,
        "milestone_funding": False,
        "resolve_disputes": False,
        "dbt_compensation_release": False,
        "drone_possession_handover": False
    }
    res = client.post("/api/v1/simulations", json=payload, headers={"Authorization": f"Bearer {officer_token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["impact"]["days_saved"] == 45
    assert data["simulated"]["estimated_delay_days"] == 853 - 45
    assert data["impact"]["cost_averted_cr"] > 0
    assert len(data["selected_interventions"]) == 1
    assert data["selected_interventions"][0]["id"] == "fast_track_land"

def test_5_select_multiple_interventions_aggregate(officer_token):
    """TEST 5: Multiple interventions aggregate schedule effects accurately."""
    payload = {
        "project_code": 705728,
        "sector_name": "Railways",
        "line_ministry": "Ministry of Railways",
        "original_cost_cr": 108000,
        "planned_end_year": 2029,
        "planned_end_quarter": 4,
        "fast_track_clearance": False,
        "advance_land_row": True,
        "milestone_funding": True,
        "resolve_disputes": True,
        "dbt_compensation_release": False,
        "drone_possession_handover": False
    }
    res = client.post("/api/v1/simulations", json=payload, headers={"Authorization": f"Bearer {officer_token}"})
    assert res.status_code == 200
    data = res.json()
    expected_days = 45 + 30 + 60
    assert data["impact"]["days_saved"] == expected_days
    assert data["simulated"]["estimated_delay_days"] == 853 - expected_days
    assert len(data["selected_interventions"]) == 3

def test_6_prevent_impossible_negative_results(officer_token):
    """TEST 6: Recovery cannot exceed baseline delay (prevent negative delays)."""
    payload = {
        "project_code": 701127,
        "sector_name": "Aviation & Aviation Infrastructure",
        "line_ministry": "Ministry of Civil Aviation",
        "original_cost_cr": 480,
        "planned_end_year": 2026,
        "planned_end_quarter": 3,
        "baseline_delay_days": 30.0,
        "fast_track_clearance": True,
        "advance_land_row": True,
        "milestone_funding": True,
        "resolve_disputes": True,
        "dbt_compensation_release": True,
        "drone_possession_handover": True
    }
    res = client.post("/api/v1/simulations", json=payload, headers={"Authorization": f"Bearer {officer_token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["simulated"]["estimated_delay_days"] >= 0
    assert data["impact"]["days_saved"] <= data["baseline"]["estimated_delay_days"]
    assert data["simulated"]["estimated_delay_days"] == 0

def test_7_cost_simulation_calculation(officer_token):
    """TEST 7: Cost escalation averted is calculated properly and never undefined or NaN."""
    cost_cr = 108000.0
    payload = {
        "project_code": 705728,
        "sector_name": "Railways",
        "line_ministry": "Ministry of Railways",
        "original_cost_cr": cost_cr,
        "planned_end_year": 2029,
        "planned_end_quarter": 4,
        "fast_track_clearance": False,
        "advance_land_row": True,
        "milestone_funding": True,
        "resolve_disputes": True,
        "dbt_compensation_release": False,
        "drone_possession_handover": False
    }
    res = client.post("/api/v1/simulations", json=payload, headers={"Authorization": f"Bearer {officer_token}"})
    assert res.status_code == 200
    data = res.json()
    impact = data["impact"]
    assert impact["cost_impact_status"] == "CALCULATED"
    assert impact["cost_averted_cr"] == 3395.34
    assert impact["projected_cost_averted_cr"] == 3395.34

def test_8_dynamic_simulation_confidence(officer_token):
    """TEST 8: Confidence score is dynamically computed and grounded between 50% and 95%."""
    payload = {
        "project_code": 705728,
        "sector_name": "Railways",
        "line_ministry": "Ministry of Railways",
        "original_cost_cr": 108000,
        "planned_end_year": 2029,
        "planned_end_quarter": 4,
        "fast_track_clearance": True,
        "advance_land_row": True,
        "milestone_funding": True,
        "resolve_disputes": True,
        "dbt_compensation_release": False,
        "drone_possession_handover": False
    }
    res = client.post("/api/v1/simulations", json=payload, headers={"Authorization": f"Bearer {officer_token}"})
    assert res.status_code == 200
    data = res.json()
    conf = data["simulation_confidence_pct"]
    assert 50 <= conf <= 95
    assert "Derived from" in data["confidence_rationale"]

def test_9_dynamic_institutional_directive(officer_token):
    """TEST 9: Institutional directive synthesizes chosen vectors and identifies statutory authorities."""
    payload = {
        "project_code": 705728,
        "sector_name": "Railways",
        "line_ministry": "Ministry of Railways",
        "original_cost_cr": 108000,
        "planned_end_year": 2029,
        "planned_end_quarter": 4,
        "fast_track_clearance": False,
        "advance_land_row": True,
        "milestone_funding": False,
        "resolve_disputes": True,
        "dbt_compensation_release": False,
        "drone_possession_handover": False
    }
    res = client.post("/api/v1/simulations", json=payload, headers={"Authorization": f"Bearer {officer_token}"})
    assert res.status_code == 200
    directive = res.json()["institutional_directive"]
    assert "Fast-track Section 3E/3F Possession" in directive["recommended_action"]
    assert "Special Arbitrage" in directive["recommended_action"]
    assert "Empowered Group of Secretaries" in directive["statutory_authority"]

def test_10_egos_submission_workflow(officer_token):
    """TEST 10: EGoS submission returns tracking ID and creates alert record."""
    payload = {
        "project_code": 705728,
        "project_name": "Mumbai-Ahmedabad High Speed Rail Project- 508 km",
        "sector_name": "Railways",
        "line_ministry": "Ministry of Railways",
        "days_saved": 135,
        "cost_averted_cr": 3395.34,
        "selected_knobs": ["Fast-track Section 3E/3F Possession", "Special Court Arbitrage"]
    }
    res = client.post("/api/v1/simulations/dispatch-egos", json=payload, headers={"Authorization": f"Bearer {officer_token}"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUBMITTED"
    assert "EGOS-2026-" in data["tracking_id"]
    assert data["alert_id"] > 0

def test_11_critical_alerts_creation_and_deduplication(officer_token):
    """TEST 11: Critical alerts are created and duplicate submissions are gracefully prevented."""
    alert_payload = {
        "project_code": 706718,
        "severity": "HIGH",
        "category": "POLICY_INTERVENTION",
        "title": "Policy Simulation Alert: #706718 (Imphal Airport)",
        "reason": "Simulation indicates schedule exposure mitigable by up to 135 days. Requires executive review.",
        "assigned_authority": "Project Monitoring Group (PMG)"
    }
    # First creation
    res1 = client.post("/api/v1/alerts", json=alert_payload, headers={"Authorization": f"Bearer {officer_token}"})
    assert res1.status_code == 200
    data1 = res1.json()
    assert data1["status"] in ["CREATED", "DUPLICATE_PREVENTED"]

    # Second creation with identical project code and severity
    res2 = client.post("/api/v1/alerts", json=alert_payload, headers={"Authorization": f"Bearer {officer_token}"})
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["status"] == "DUPLICATE_PREVENTED"
    assert "already exists" in data2["message"]

def test_12_simulation_history_persistence(officer_token):
    """TEST 12: Executed simulations are persisted and retrievable via history endpoint."""
    res = client.get("/api/v1/simulations/history?limit=5", headers={"Authorization": f"Bearer {officer_token}"})
    assert res.status_code == 200
    data = res.json()
    assert "simulations" in data
    assert len(data["simulations"]) > 0
    latest = data["simulations"][0]
    assert "baseline_metrics" in latest
    assert "simulated_metrics" in latest
    assert "impact_metrics" in latest

def test_13_rbac_viewer_restriction(viewer_token, officer_token):
    """TEST 13: VIEWER role receives HTTP 403, OFFICER role succeeds with HTTP 200."""
    payload = {
        "project_code": 705728,
        "sector_name": "Railways",
        "line_ministry": "Ministry of Railways",
        "original_cost_cr": 108000,
        "planned_end_year": 2029,
        "planned_end_quarter": 4,
        "fast_track_clearance": False,
        "advance_land_row": False,
        "milestone_funding": False,
        "resolve_disputes": False,
        "dbt_compensation_release": False,
        "drone_possession_handover": False
    }
    # Viewer attempt: forbidden
    res_viewer = client.post("/api/v1/simulations", json=payload, headers={"Authorization": f"Bearer {viewer_token}"})
    assert res_viewer.status_code == 403

    # Officer attempt: allowed
    res_officer = client.post("/api/v1/simulations", json=payload, headers={"Authorization": f"Bearer {officer_token}"})
    assert res_officer.status_code == 200

def test_14_bottleneck_diagnostics_integration(officer_token):
    """TEST 14: Bottleneck diagnostics are dynamically generated and linked to project telemetry."""
    payload = {
        "project_code": 705728,
        "sector_name": "Railways",
        "line_ministry": "Ministry of Railways",
        "original_cost_cr": 108000,
        "planned_end_year": 2029,
        "planned_end_quarter": 4,
        "fast_track_clearance": True,
        "advance_land_row": True,
        "milestone_funding": True,
        "resolve_disputes": True,
        "dbt_compensation_release": False,
        "drone_possession_handover": False
    }
    res = client.post("/api/v1/simulations", json=payload, headers={"Authorization": f"Bearer {officer_token}"})
    assert res.status_code == 200
    diag = res.json()["bottleneck_diagnostics"]
    assert "land_acquisition" in diag
    assert "environmental_status" in diag
    assert "contractor_cashflow" in diag
    assert diag["contractor_cashflow"] == "Liquidity Injected"

def test_15_provenance_and_statutory_disclaimer(officer_token):
    """TEST 15: Statutory disclaimer and model provenance are strictly attached."""
    payload = {
        "project_code": 705728,
        "sector_name": "Railways",
        "line_ministry": "Ministry of Railways",
        "original_cost_cr": 108000,
        "planned_end_year": 2029,
        "planned_end_quarter": 4,
        "fast_track_clearance": False,
        "advance_land_row": True,
        "milestone_funding": False,
        "resolve_disputes": False,
        "dbt_compensation_release": False,
        "drone_possession_handover": False
    }
    res = client.post("/api/v1/simulations", json=payload, headers={"Authorization": f"Bearer {officer_token}"})
    assert res.status_code == 200
    data = res.json()
    assert "MODEL SIMULATION" in data["provenance_disclaimer"]
    assert "NOT AN OFFICIAL GOVERNMENT FORECAST" in data["provenance_disclaimer"]
