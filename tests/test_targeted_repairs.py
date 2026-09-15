"""
Targeted Functionality Repair Verification Test Suite
Verifies:
1. Early Warning Module
2. Policy Simulator Module
3. Data Quality Audit Module
4. Direct SPA Route Resolution & History State
5. Role-Based Access Control (RBAC) Integrity
"""
import pytest
from fastapi.testclient import TestClient
from backend.server import app
from backend.security.auth import create_access_token

client = TestClient(app)

def test_direct_spa_routes_resolution():
    """Verify direct URL access for repaired and frozen navigation modules."""
    routes = [
        "/early-warning",
        "/policy-simulator",
        "/data-quality-audit",
        "/executive-overview",
        "/master-explorer",
        "/critical-alerts",
        "/land-and-gis-demo"
    ]
    for r in routes:
        res = client.get(r)
        assert res.status_code == 200, f"Failed for route {r}: {res.status_code}"
        assert "<!DOCTYPE html>" in res.text or "<html" in res.text

def test_data_quality_kpis_and_dimensions():
    """Verify Data Quality Audit returns real dataset metrics & 5-dimension breakdown."""
    res = client.get("/api/v1/data-quality")
    assert res.status_code == 200
    data = res.json()
    
    assert "data_quality_audit" in data
    audit = data["data_quality_audit"]
    assert audit["total_records"] == 1981
    assert audit["valid_records"] == 857
    assert audit["invalid_records"] == 1124
    assert audit["valid_records"] + audit["invalid_records"] == 1981
    assert audit["duplicate_records"] == 0
    
    # 5 Dimensions
    assert "quality_breakdown" in data
    dims = data["quality_breakdown"]
    for dim_name in ["completeness", "consistency", "validity", "uniqueness", "accuracy"]:
        assert dim_name in dims
        assert "score_pct" in dims[dim_name]
        assert "issues_count" in dims[dim_name]
        assert "title" in dims[dim_name]
        assert "description" in dims[dim_name]
        assert 0.0 <= dims[dim_name]["score_pct"] <= 100.0

def test_data_quality_issues_pagination_and_filtering():
    """Verify Data Quality issues querying, pagination, and filter parameters."""
    # 1. Default first page
    res = client.get("/api/v1/data-quality/issues?page=1&limit=10")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] > 1000
    assert len(data["issues"]) == 10
    assert data["page"] == 1
    
    first_issue = data["issues"][0]
    for k in ["project_code", "field", "issue_type", "issue", "severity", "current_value", "expected_format", "status"]:
        assert k in first_issue
        
    # 2. Filter by Severity
    res_crit = client.get("/api/v1/data-quality/issues?severity=CRITICAL&limit=5")
    assert res_crit.status_code == 200
    crit_data = res_crit.json()
    for item in crit_data["issues"]:
        assert item["severity"] == "CRITICAL"
        
    # 3. Filter by Search Query
    res_search = client.get("/api/v1/data-quality/issues?q=400010")
    assert res_search.status_code == 200
    search_data = res_search.json()
    assert search_data["total"] >= 1
    assert any(i["project_code"] == 400010 for i in search_data["issues"])

def test_data_quality_remediation_rbac():
    """Verify read-only VIEWER is denied 403, and authorized roles can remediate."""
    # Read-only token
    viewer_token = create_access_token("viewer-001", "viewer@gov.in", "VIEWER")
    res_forbidden = client.post(
        "/api/v1/data-quality/issues/400010/status",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"status": "UNDER_REVIEW", "notes": "Auditor review"}
    )
    assert res_forbidden.status_code == 403

    # Officer token
    officer_token = create_access_token("officer-001", "officer@gov.in", "STATE_OFFICER")
    res_ok = client.post(
        "/api/v1/data-quality/issues/400010/status",
        headers={"Authorization": f"Bearer {officer_token}"},
        json={"status": "UNDER_REVIEW", "notes": "Reviewed and acknowledged by Nodal Officer"}
    )
    assert res_ok.status_code == 200
    assert res_ok.json()["status"] == "SUCCESS"
    assert res_ok.json()["new_status"] in ["Under Review", "UNDER_REVIEW"]

def test_data_quality_export_csv():
    """Verify Data Quality Audit CSV export produces valid CSV data."""
    res = client.get("/api/v1/data-quality/export")
    assert res.status_code == 200
    assert "text/csv" in res.headers.get("content-type", "")
    content = res.text
    assert "Project Code,Project Name,Sector,Ministry,State,Field,Issue Description,Issue Type,Severity,Current Value,Expected Format,Remediation Status,Reviewed By" in content
    assert "400005" in content

def test_early_warning_prediction_engine():
    """Verify Early Warning prediction endpoint with real project payload."""
    officer_token = create_access_token("officer-001", "officer@gov.in", "STATE_OFFICER")
    payload = {
        "project_code": 705728,
        "sector_name": "Railways",
        "line_ministry": "Ministry of Railways",
        "original_cost_cr": 108000.0,
        "planned_end_year": 2029,
        "planned_end_quarter": 4,
        "current_land_stage": "STAGE_COMPENSATION",
        "land_required_acres": 1394.0,
        "land_acquired_pct": 74.2,
        "compensation_disbursed_pct": 68.0,
        "active_legal_disputes": 2,
        "affected_families_count": 140,
        "rehabilitation_package_cr": 25.0
    }
    res = client.post(
        "/api/v1/predictions",
        headers={"Authorization": f"Bearer {officer_token}"},
        json=payload
    )
    assert res.status_code == 200
    data = res.json()
    assert "delay_probability_pct" in data
    assert "estimated_delay_days" in data
    assert "risk_tier" in data
    assert "most_likely_bottleneck_stage" in data
    assert data["delay_probability_pct"] >= 0

def test_policy_simulator_engine():
    """Verify Policy Simulator executes scenarios with baseline vs simulated comparison."""
    officer_token = create_access_token("officer-001", "officer@gov.in", "STATE_OFFICER")
    payload = {
        "project_code": 705728,
        "sector_name": "Railways",
        "line_ministry": "Ministry of Railways",
        "original_cost_cr": 108000.0,
        "planned_end_year": 2029,
        "planned_end_quarter": 4,
        "fast_track_clearance": True,
        "advance_land_row": True,
        "milestone_funding": True,
        "resolve_disputes": True,
        "dbt_compensation_release": True,
        "drone_possession_handover": True
    }
    res = client.post(
        "/api/v1/simulations",
        headers={"Authorization": f"Bearer {officer_token}"},
        json=payload
    )
    assert res.status_code == 200
    data = res.json()
    assert "baseline" in data
    assert "simulated" in data
    assert "impact" in data
    assert data["impact"]["days_saved"] >= 0
    assert data["impact"]["cost_averted_cr"] >= 0

def test_dom_elements_presence():
    """Verify all required DOM element IDs exist in frontend/index.html."""
    with open("frontend/index.html", "r", encoding="utf-8") as f:
        html = f.read()

    required_ids = [
        # Early Warning
        "eval-project-selector",
        "eval-project-search",
        "eval-cost-overrun-val",
        "eval-risk-factors-breakdown",
        "eval-btn-open-project",
        # Policy Simulator
        "sim-project-selector",
        "sim-project-search",
        "sim-base-cost",
        "sim-error-box",
        # Data Quality Audit
        "audit-total-records",
        "audit-valid-records",
        "audit-invalid-records",
        "audit-missing-fields",
        "audit-duplicate-records",
        "audit-quality-score",
        "audit-health-badge",
        "audit-last-update",
        "audit-status-badge",
        "audit-issues-tbody",
        "audit-filter-search",
        "audit-filter-severity",
        "audit-filter-type",
        "audit-filter-status"
    ]
    for el_id in required_ids:
        assert f'id="{el_id}"' in html, f"Missing DOM id: {el_id}"
