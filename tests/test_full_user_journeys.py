import pytest
from fastapi.testclient import TestClient
from backend.server import app

client = TestClient(app)

def get_token(role="NATIONAL_ADMIN"):
    res = client.post(f"/api/v1/auth/demo-token?role={role}")
    assert res.status_code == 200
    return res.json()["access_token"]

# JOURNEY 1: Login / Role Selection -> Executive Overview -> Project Dossier -> Risk Check
def test_journey_1_overview_and_project_dossier():
    token = get_token("NATIONAL_ADMIN")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Fetch Executive Summary KPIs & Sector telemetry
    res_summary = client.get("/api/v1/summary", headers=headers)
    assert res_summary.status_code == 200
    summary = res_summary.json()
    assert "kpi" in summary
    assert summary["kpi"]["total_projects"] > 0
    assert "sectors" in summary
    assert len(summary["sectors"]) > 0

    # 2. Pick first project from catalog
    res_proj = client.get("/api/v1/projects?page=1&limit=5", headers=headers)
    assert res_proj.status_code == 200
    catalog = res_proj.json()
    assert len(catalog["projects"]) > 0
    sample_code = catalog["projects"][0]["project_code"]

    # 3. Open full project dossier with Explainable AI & SHAP decomposition
    res_dossier = client.get(f"/api/v1/projects/{sample_code}", headers=headers)
    assert res_dossier.status_code == 200
    dossier = res_dossier.json()
    assert "project" in dossier
    assert "ai_intelligence" in dossier
    assert "shap_factors" in dossier["ai_intelligence"]
    assert "action_recommendations" in dossier["ai_intelligence"]

# JOURNEY 2: Projects Explorer -> Search -> Sector Filter -> Pagination -> Detail
def test_journey_2_explorer_search_filter_pagination():
    token = get_token("STATE_NODAL_OFFICER")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Search by keyword
    res_search = client.get("/api/v1/projects?q=Airport&page=1&limit=10", headers=headers)
    assert res_search.status_code == 200
    data_search = res_search.json()
    assert data_search["total_records"] > 0
    for p in data_search["projects"]:
        assert "airport" in p["project_name"].lower() or "civil aviation" in (p["sector_name"] or "").lower()

    # 2. Filter by sector
    res_sector = client.get("/api/v1/projects?sector=Railways&page=1&limit=10", headers=headers)
    assert res_sector.status_code == 200
    data_sector = res_sector.json()
    for p in data_sector["projects"]:
        assert "railway" in p["sector_name"].lower()

    # 3. Pagination navigation (Page 2)
    res_p2 = client.get("/api/v1/projects?page=2&limit=10", headers=headers)
    assert res_p2.status_code == 200
    data_p2 = res_p2.json()
    assert data_p2["page"] == 2
    assert len(data_p2["projects"]) > 0

# JOURNEY 3: Early Warning Evaluator -> Predict -> Change Inputs -> Recalculate
def test_journey_3_evaluator_lifecycle_and_recalculation():
    token = get_token("PROJECT_MONITORING_OFFICER")
    headers = {"Authorization": f"Bearer {token}"}

    # Step 1: Initial evaluation with 30% land acquired
    eval_payload_1 = {
        "sector_name": "Roads & Highways",
        "line_ministry": "Ministry of Road Transport & Highways",
        "original_cost_cr": 2800.0,
        "planned_end_year": 2028,
        "current_land_stage": "STAGE_VALUATION",
        "land_required_acres": 150.0,
        "land_acquired_pct": 30.0,
        "compensation_disbursed_pct": 20.0,
        "active_legal_disputes": 3,
        "affected_families_count": 250,
        "rehabilitation_package_cr": 12.0
    }
    res_1 = client.post("/api/v1/predictions", json=eval_payload_1, headers=headers)
    assert res_1.status_code == 200
    pred_1 = res_1.json()
    assert pred_1["delay_probability_pct"] > 0
    assert pred_1["estimated_delay_days"] > 0

    # Step 2: User changes parameters (land acquired improved to 85%, disputes resolved to 0)
    eval_payload_2 = {
        **eval_payload_1,
        "current_land_stage": "STAGE_POSSESSION",
        "land_acquired_pct": 85.0,
        "compensation_disbursed_pct": 80.0,
        "active_legal_disputes": 0
    }
    res_2 = client.post("/api/v1/predictions", json=eval_payload_2, headers=headers)
    assert res_2.status_code == 200
    pred_2 = res_2.json()

    # Improved land possession must result in lower delay probability
    assert pred_2["delay_probability_pct"] <= pred_1["delay_probability_pct"]

# JOURNEY 4: Policy Simulator -> Levers -> Impact -> Reset -> EGoS Submission
def test_journey_4_policy_simulation_and_egos_dispatch():
    token = get_token("NATIONAL_ADMIN")
    headers = {"Authorization": f"Bearer {token}"}

    # Baseline (no interventions)
    sim_base = {
        "sector_name": "Railways",
        "line_ministry": "Ministry of Railways",
        "original_cost_cr": 3200.0,
        "planned_end_year": 2028,
        "fast_track_clearance": False,
        "advance_land_row": False,
        "milestone_funding": False,
        "resolve_disputes": False,
        "dbt_compensation_release": False
    }
    res_base = client.post("/api/v1/simulations", json=sim_base, headers=headers)
    assert res_base.status_code == 200
    data_base = res_base.json()
    assert data_base["impact"]["days_saved"] == 0

    # Apply policy levers (Section 64 Lok Adalat + 100% Advance RoW)
    sim_applied = {
        **sim_base,
        "advance_land_row": True,
        "resolve_disputes": True,
        "dbt_compensation_release": True
    }
    res_applied = client.post("/api/v1/simulations", json=sim_applied, headers=headers)
    assert res_applied.status_code == 200
    data_applied = res_applied.json()
    assert data_applied["impact"]["days_saved"] > 0
    assert data_applied["impact"]["cost_averted_cr"] > 0

    # Dispatch intervention package to Empowered Group of Secretaries (EGoS)
    egos_payload = {
        "project_code": 400277,
        "project_name": "Dum Dum Airport-New Garia via Rajarhat",
        "sector_name": "Railways",
        "line_ministry": "Ministry of Railways",
        "selected_knobs": ["Advance 100% RoW", "Section 64 Fast-Track Tribunal"],
        "days_saved": data_applied["impact"]["days_saved"],
        "cost_averted_cr": data_applied["impact"]["cost_averted_cr"]
    }
    res_egos = client.post("/api/v1/simulations/dispatch-egos", json=egos_payload, headers=headers)
    assert res_egos.status_code == 200
    assert res_egos.json()["status"] == "SUBMITTED"

# JOURNEY 5: Critical Alerts -> Filter -> Acknowledge -> Assign -> Comment
def test_journey_5_alerts_management_lifecycle():
    token = get_token("DISTRICT_OFFICER")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Fetch alerts
    res_alerts = client.get("/api/v1/alerts?limit=10", headers=headers)
    assert res_alerts.status_code == 200
    alerts = res_alerts.json()["alerts"]
    assert len(alerts) > 0
    sample_alert_id = alerts[0]["alert_id"]

    # 2. Acknowledge alert
    ack_payload = {"status": "ACKNOWLEDGED", "notes": "District Land Collector reviewed court stay"}
    res_ack = client.post(f"/api/v1/alerts/{sample_alert_id}/acknowledge", json=ack_payload, headers=headers)
    assert res_ack.status_code == 200
    assert res_ack.json()["status"] == "SUCCESS"

    # 3. Add administrative comment to alert
    comment_payload = {"comment_text": "Special Land Acquisition Officer deployed for Section 19 declaration."}
    res_comment = client.post(f"/api/v1/alerts/{sample_alert_id}/comment", json=comment_payload, headers=headers)
    assert res_comment.status_code == 200
    assert res_comment.json()["status"] == "COMMENT_RECORDED"

# JOURNEY 6: GIS & Land Demo -> National Overview -> State Drilldown -> District Projects
def test_journey_6_gis_spatial_drilldown():
    # 1. National Level GeoJSON States
    res_geo = client.get("/india_states.geojson")
    assert res_geo.status_code == 200
    geojson = res_geo.json()
    assert geojson["type"] == "FeatureCollection"
    assert len(geojson["features"]) > 0

    # 2. State Drilldown
    res_states = client.get("/api/v1/gis/drilldown")
    assert res_states.status_code == 200
    states_data = res_states.json()
    assert states_data["level"] == "NATIONAL"
    first_state = states_data["states"][0]["state_name"]

    # 3. District Drilldown within state
    res_state = client.get(f"/api/v1/gis/drilldown?state={first_state}")
    assert res_state.status_code == 200
    state_detail = res_state.json()
    assert state_detail["level"] == "STATE"
    assert len(state_detail["districts"]) > 0

# JOURNEY 7: Data Center -> Ingestion Audit -> Freshness -> Snapshots -> Sources
def test_journey_7_data_center_and_audit():
    token = get_token("NATIONAL_ADMIN")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Ingestion Sources
    res_sources = client.get("/api/v1/data/sources", headers=headers)
    assert res_sources.status_code == 200
    assert len(res_sources.json()["sources"]) > 0

    # 2. Snapshots Catalog
    res_snaps = client.get("/api/v1/data/snapshots", headers=headers)
    assert res_snaps.status_code == 200
    assert len(res_snaps.json()["snapshots"]) > 0

    # 3. Data Freshness
    res_fresh = client.get("/api/v1/data/freshness", headers=headers)
    assert res_fresh.status_code == 200
    fresh = res_fresh.json()
    assert "total_records" in fresh
    assert fresh["total_records"] > 0

    # 4. Data Quality Audit
    res_dq = client.get("/api/v1/data-quality", headers=headers)
    assert res_dq.status_code == 200
    dq = res_dq.json()
    assert "data_quality_audit" in dq
    assert dq["data_quality_audit"]["total_records"] > 0
