import pytest
from fastapi.testclient import TestClient
from backend.server import app
from backend.security.auth import create_access_token
from backend.land_engine import evaluate_land_acquisition_bottleneck, get_land_action_recommendations, LAND_STAGES

client = TestClient(app)

@pytest.fixture
def analyst_token():
    return create_access_token(
        user_id="00000000-0000-0000-0000-000000000003",
        email="analyst.gatishakti@gov.in",
        role="ANALYST"
    )

@pytest.fixture
def officer_token():
    return create_access_token(
        user_id="00000000-0000-0000-0000-000000000002",
        email="officer.railways@gov.in",
        role="OFFICER"
    )

def test_land_engine_statutory_bottleneck_detection():
    # Test compensation bottleneck: land acquired is low and compensation lags
    eval_result = evaluate_land_acquisition_bottleneck(
        land_required_acres=150.0,
        land_acquired_pct=25.0,
        compensation_disbursed_pct=15.0,
        active_legal_disputes=0,
        affected_families_count=50,
        land_clearance_status="In Progress"
    )
    assert eval_result["bottleneck_stage_id"] in ["ADMIN_APPROVAL", "COMPENSATION"]
    assert "statutory_act_reference" in eval_result
    assert eval_result["confidence_score"] >= 0.85
    assert len(eval_result["stage_breakdown"]) == 5

    # Test legal dispute bottleneck: disputes present
    lit_result = evaluate_land_acquisition_bottleneck(
        land_required_acres=200.0,
        land_acquired_pct=85.0,
        compensation_disbursed_pct=85.0,
        active_legal_disputes=5,
        affected_families_count=30,
        land_clearance_status="High Court Litigation Pending"
    )
    assert lit_result["bottleneck_stage_id"] == "LEGAL_DISPUTES"
    assert lit_result["bottleneck_severity"] == "CRITICAL"
    assert "Section 64" in lit_result["stage_evidence"]

def test_land_engine_action_recommendations():
    recs = get_land_action_recommendations(
        bottleneck_stage="LEGAL_DISPUTES",
        land_required_acres=200.0,
        land_acquired_pct=80.0,
        active_legal_disputes=4,
        affected_families_count=120,
        rehabilitation_package_cr=25.0,
        sector="Roads & Highways"
    )
    assert len(recs) >= 2
    priorities = [r["priority"] for r in recs]
    assert any("CRITICAL" in p for p in priorities)
    assert any("Lok Adalat" in r["action"] for r in recs)

def test_gis_drilldown_hierarchy():
    # Level 1: National (no params) -> returns state summaries
    res_nat = client.get("/api/v1/gis/drilldown")
    assert res_nat.status_code == 200
    data_nat = res_nat.json()
    assert data_nat["level"] == "NATIONAL"
    assert len(data_nat["states"]) > 0
    first_state = data_nat["states"][0]["state_name"]
    assert "project_count" in data_nat["states"][0]
    assert "dominant_delay_driver" in data_nat["states"][0]

    # Level 2: State -> returns district summaries
    res_state = client.get(f"/api/v1/gis/drilldown?state={first_state}")
    assert res_state.status_code == 200
    data_state = res_state.json()
    assert data_state["level"] == "STATE"
    assert data_state["state"] == first_state
    assert len(data_state["districts"]) > 0
    first_district = data_state["districts"][0]["district_name"]

    # Level 3: District -> returns project list
    res_dist = client.get(f"/api/v1/gis/drilldown?state={first_state}&district={first_district}")
    assert res_dist.status_code == 200
    data_dist = res_dist.json()
    assert data_dist["level"] == "DISTRICT"
    assert data_dist["district"] == first_district
    assert len(data_dist["projects"]) > 0
    assert "project_code" in data_dist["projects"][0]

def test_prediction_with_land_statutory_payload(analyst_token):
    payload = {
        "sector_name": "Roads & Highways",
        "line_ministry": "Ministry of Road Transport & Highways",
        "original_cost_cr": 450.0,
        "planned_end_year": 2028,
        "planned_end_quarter": 3,
        "current_land_stage": "COMPENSATION",
        "land_required_acres": 120.0,
        "land_acquired_pct": 37.5,
        "compensation_disbursed_pct": 35.0,
        "active_legal_disputes": 3,
        "affected_families_count": 220
    }
    headers = {"Authorization": f"Bearer {analyst_token}"}
    res = client.post("/api/v1/predictions", json=payload, headers=headers)
    assert res.status_code == 200
    pred = res.json()
    assert "delay_probability_pct" in pred
    assert "risk_tier" in pred
    assert "bottleneck_stage_id" in pred
    assert pred["bottleneck_stage_id"] in [s["stage_id"] for s in LAND_STAGES]
    assert "statutory_act_reference" in pred
    assert "confidence_score" in pred
    assert "stage_breakdown" in pred
    assert len(pred["stage_breakdown"]) == 5

def test_policy_simulation_with_land_interventions(analyst_token):
    payload = {
        "sector_name": "Roads & Highways",
        "line_ministry": "Ministry of Road Transport & Highways",
        "original_cost_cr": 1200.0,
        "planned_end_year": 2027,
        "planned_end_quarter": 2,
        "fast_track_clearance": True,
        "advance_land_row": True,
        "milestone_funding": False,
        "resolve_disputes": True,
        "dbt_compensation_release": True
    }
    headers = {"Authorization": f"Bearer {analyst_token}"}
    res = client.post("/api/v1/simulations", json=payload, headers=headers)
    assert res.status_code == 200
    sim = res.json()
    assert "baseline" in sim
    assert "simulated" in sim
    assert "impact" in sim
    assert "provenance_disclaimer" in sim
    assert len(sim["assumptions"]) == 5

def test_alert_lifecycle_assign_and_comment(officer_token):
    headers = {"Authorization": f"Bearer {officer_token}"}
    # Assign alert 1
    res_assign = client.post("/api/v1/alerts/1/assign", json={
        "assigned_authority": "Special Land Acquisition Officer (SLAO)",
        "assignment_notes": "Issue RFCTLARR Section 19 declaration within 14 days"
    }, headers=headers)
    assert res_assign.status_code == 200
    assert res_assign.json()["status"] == "ASSIGNED"

    # Add comment
    res_comment = client.post("/api/v1/alerts/1/comment", json={
        "comment_text": "Joint measurement survey completed with state revenue department."
    }, headers=headers)
    assert res_comment.status_code == 200
    assert res_comment.json()["status"] == "COMMENT_RECORDED"

    # Get history
    res_hist = client.get("/api/v1/alerts/1/history")
    assert res_hist.status_code == 200
    hist = res_hist.json()
    assert len(hist["comments"]) >= 1
    assert "officer" in hist["comments"][0]["user_name"].lower()

def test_model_monitoring_and_data_quality():
    res_mon = client.get("/api/v1/model/monitoring")
    assert res_mon.status_code == 200
    mon = res_mon.json()
    assert mon["active_model_version"] == "v2.1.0-land-intelligence"
    assert mon["drift_monitoring"]["population_stability_index_psi"] == 0.042
    assert "TRIGGER-BASED" in mon["retraining_architecture"]["status"]

    res_dq = client.get("/api/v1/data-quality")
    assert res_dq.status_code == 200
    dq = res_dq.json()
    assert dq["overall_quality_score_pct"] > 90.0
    assert "land_acquisition_integrity" in dq
    assert dq["duplicate_records_count"] >= 0
