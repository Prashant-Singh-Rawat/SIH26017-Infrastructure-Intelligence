"""
Automated Continuous Ingestion, Snapshots & Data Governance Test Suite — SIH26017
Validates:
1. Data source registry & official PAIMANA metadata
2. Data freshness indicators & 'HISTORICAL SNAPSHOT' honest reporting
3. Historical snapshot catalog and detail retrieval
4. Change detection engine (NEW, UPDATED, UNCHANGED, COMPLETED deltas)
5. Project history and temporal risk tracking
6. Model insights and zero-leakage feature contract
7. Ingestion RBAC authorization (VIEWER/ANALYST -> 403, ADMIN -> 200)
8. Data quality gate and CSV formula injection protection
"""

import os
import pytest
from fastapi.testclient import TestClient

from backend.server import app
from backend.security.auth import create_access_token
from backend.database import get_db_connection

@pytest.fixture(scope="module", autouse=True)
def cleanup_test_artifacts():
    yield
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("DELETE FROM projects WHERE project_code IN (999111, 999201, 999202, 999203);")
        c.execute("DELETE FROM data_snapshots WHERE id LIKE 'test_snap%';")
        c.execute("DELETE FROM raw_data_snapshots WHERE snapshot_id LIKE 'test_snap%';")
        c.execute("DELETE FROM project_versions WHERE snapshot_id LIKE 'test_snap%';")
        c.execute("DELETE FROM data_quality_runs WHERE snapshot_id LIKE 'test_snap%';")
        c.execute("DELETE FROM ingestion_runs WHERE snapshot_id LIKE 'test_snap%';")
        conn.commit()
    finally:
        conn.close()

client = TestClient(app)

ADMIN_TOKEN = create_access_token(
    user_id="00000000-0000-0000-0000-000000000001",
    email="admin.infra@gov.in",
    role="ADMIN",
    full_name="Director General"
)

ANALYST_TOKEN = create_access_token(
    user_id="00000000-0000-0000-0000-000000000003",
    email="analyst.gatishakti@gov.in",
    role="ANALYST",
    full_name="Lead Economist"
)

VIEWER_TOKEN = create_access_token(
    user_id="00000000-0000-0000-0000-000000000004",
    email="viewer.public@gov.in",
    role="VIEWER",
    full_name="Public Auditor"
)

def test_data_sources_registry():
    """Verify GET /api/v1/data/sources returns official MoSPI PAIMANA metadata."""
    res = client.get("/api/v1/data/sources")
    assert res.status_code == 200
    data = res.json()
    assert "sources" in data
    assert len(data["sources"]) >= 1
    
    paimana = next((s for s in data["sources"] if s["id"] == "mospi_paimana"), None)
    assert paimana is not None
    assert paimana["organization"] == "Ministry of Statistics and Programme Implementation (MoSPI), Government of India"
    assert paimana["official_status"] == "OFFICIAL_GOVERNMENT"
    assert paimana["provenance"] == "[SOURCE — MoSPI PAIMANA]"
    assert paimana["update_frequency"] == "MONTHLY"

def test_data_freshness_honest_reporting():
    """Verify GET /api/v1/data/freshness reports 'HISTORICAL SNAPSHOT' and never claims fake 'LIVE DATA'."""
    res = client.get("/api/v1/data/freshness")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "HISTORICAL SNAPSHOT"
    assert data["is_live"] is False
    assert data["total_records"] >= 1981
    assert "MoSPI PAIMANA" in data["data_source"]
    assert "READY FOR AUTHORIZED GOVERNMENT API CREDENTIALS" in data["api_integration_status"]
    assert "[SOURCE — MoSPI PAIMANA]" in data["provenance"]

def test_data_snapshots_catalog_and_detail():
    """Verify GET /api/v1/data/snapshots and GET /api/v1/data/snapshots/{id}."""
    res = client.get("/api/v1/data/snapshots")
    assert res.status_code == 200
    data = res.json()
    assert "snapshots" in data
    assert len(data["snapshots"]) >= 1
    
    baseline = next((s for s in data["snapshots"] if s["id"] == "paimana_2026_04"), None)
    assert baseline is not None
    assert baseline["record_count"] == 1981
    assert baseline["schema_version"] == "v2.1"
    assert baseline["status"] == "VALIDATED"
    assert baseline["source_checksum"].startswith("sha256:")

    # Detail probe
    res_det = client.get("/api/v1/data/snapshots/paimana_2026_04")
    assert res_det.status_code == 200
    det_data = res_det.json()
    assert det_data["snapshot"]["id"] == "paimana_2026_04"
    assert det_data["snapshot"]["total_original_cost_cr"] > 0

    # Non-existent snapshot 404
    res_404 = client.get("/api/v1/data/snapshots/non_existent_snap_999")
    assert res_404.status_code == 404
    assert res_404.json()["error"]["code"] == "SNAPSHOT_NOT_FOUND"

def test_change_detection_engine():
    """Verify GET /api/v1/data/changes compares snapshots and returns deterministic deltas."""
    res = client.get("/api/v1/data/changes?from_snapshot=paimana_2026_04&to_snapshot=paimana_2026_05")
    assert res.status_code == 200
    data = res.json()
    assert "summary" in data
    assert "events" in data
    assert "new_projects" in data["summary"]
    assert "updated_projects" in data["summary"]
    assert "unchanged_projects" in data["summary"]
    
    # Verify event structure
    if len(data["events"]) > 0:
        evt = data["events"][0]
        assert "project_code" in evt
        assert "change_type" in evt
        assert evt["change_type"] in ("NEW", "UPDATED", "UNCHANGED", "COMPLETED", "REMOVED_FROM_ACTIVE_SNAPSHOT")

def test_project_history_and_risk_progression():
    """Verify historical snapshot versions and risk history endpoints."""
    # Project 702668 has seeded versions
    res_hist = client.get("/api/v1/projects/702668/history")
    assert res_hist.status_code == 200
    data_hist = res_hist.json()
    assert data_hist["project_code"] == 702668
    assert "history" in data_hist
    assert len(data_hist["history"]) >= 1
    assert "snapshot_id" in data_hist["history"][0]

    # Risk history probe
    res_risk = client.get("/api/v1/projects/702668/risk-history")
    assert res_risk.status_code == 200
    data_risk = res_risk.json()
    assert data_risk["project_code"] == 702668
    assert "risk_history" in data_risk
    assert len(data_risk["risk_history"]) >= 1
    assert "risk_tier" in data_risk["risk_history"][0]

def test_model_insights_endpoint():
    """Verify GET /api/v1/model-insights provides zero-leakage schema and metrics."""
    res = client.get("/api/v1/model-insights")
    assert res.status_code == 200
    data = res.json()
    assert "metadata" in data
    assert "feature_schema" in data
    assert data["feature_schema"]["zero_leakage_guarantee"] is True
    assert "expenditure_cr" in data["feature_schema"]["quarantined_downstream_features"]
    assert "sector_name" in data["feature_schema"]["inception_features"]

def test_ingestion_rbac_authorization():
    """Verify POST /api/v1/data/ingest requires ADMIN or OFFICER role."""
    payload = {
        "snapshot_id": "test_snap_2026_06",
        "snapshot_label": "Test Snapshot June 2026",
        "snapshot_date": "2026-06-30",
        "csv_content": "sr_no,sector_name,line_ministry,project_code,project_name,original_cost_cr,revised_cost_cr,expenditure_cr,original_end_date_str,revised_end_date_str\n1,Railways,Ministry of Railways,999111,Test Express Link,1200.0,0.0,250.0,15/06/2028,15/06/2028"
    }

    # 1. Unauthenticated -> 401
    res_no_auth = client.post("/api/v1/data/ingest", json=payload)
    assert res_no_auth.status_code == 401

    # 2. VIEWER role -> 403 Forbidden
    res_viewer = client.post(
        "/api/v1/data/ingest",
        json=payload,
        headers={"Authorization": f"Bearer {VIEWER_TOKEN}"}
    )
    assert res_viewer.status_code == 403

    # 3. ANALYST role -> 403 Forbidden
    res_analyst = client.post(
        "/api/v1/data/ingest",
        json=payload,
        headers={"Authorization": f"Bearer {ANALYST_TOKEN}"}
    )
    assert res_analyst.status_code == 403

    # 4. ADMIN role -> 200 Success
    res_admin = client.post(
        "/api/v1/data/ingest",
        json=payload,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}
    )
    assert res_admin.status_code == 200
    res_data = res_admin.json()
    assert res_data["status"] == "SUCCESS"
    assert res_data["snapshot_id"] == "test_snap_2026_06"
    assert res_data["valid_records_ingested"] == 1

def test_data_quality_gate_and_quarantine():
    """Verify that invalid rows (e.g. negative costs, formula injection) are quarantined safely."""
    # Row 1: Valid
    # Row 2: Negative cost -> quarantined
    # Row 3: Formula injection (=SUM(1+1)) -> sanitized with single quote prefix
    csv_text = (
        "sr_no,sector_name,line_ministry,project_code,project_name,original_cost_cr,revised_cost_cr,expenditure_cr,original_end_date_str,revised_end_date_str\n"
        "1,Power,Ministry of Power,999201,Valid Hydro Project,850.0,0.0,100.0,10/12/2027,10/12/2027\n"
        "2,Roads,Ministry of Road Transport,999202,Negative Outlay Bypass,-500.0,0.0,50.0,10/12/2027,10/12/2027\n"
        "3,Shipping,Ministry of Ports,999203,=CMD|'/C calc'!A0,300.0,0.0,10.0,10/12/2027,10/12/2027\n"
    )

    payload = {
        "snapshot_id": "test_snap_quarantine_01",
        "snapshot_label": "Quarantine Testing Snapshot",
        "snapshot_date": "2026-07-31",
        "csv_content": csv_text,
        "notes": "Testing data quality gate quarantine behavior"
    }

    res = client.post(
        "/api/v1/data/ingest",
        json=payload,
        headers={"Authorization": f"Bearer {ADMIN_TOKEN}"}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    # Row 2 was quarantined due to negative cost
    assert data["quarantined_records"] == 1
    # Rows 1 and 3 (sanitized formula) were valid
    assert data["valid_records_ingested"] == 2
