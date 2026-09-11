"""
PM-OCMS Infrastructure Predictive Analytics & Early Warning Platform (SIH26017)
Production-Grade FastAPI Backend with RBAC, RLS-ready Data Access, Rate Limiting, and Security Headers.
"""

import os
import uuid
import json
import time
import joblib
import pandas as pd
import numpy as np
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, Query, HTTPException, Request, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError

from backend.database import (
    get_db_connection, DB_PATH, IS_POSTGRES, adapt_query, record_audit_log,
    get_data_sources, get_data_snapshots, get_data_snapshot,
    get_data_freshness, get_project_history, get_project_risk_history,
    get_snapshot_change_events, record_prediction_history
)
from backend.adapters.paimana_adapter import PaimanaAdapter
from backend.change_detection import ChangeDetectionEngine
from backend.risk_tracker import RiskTracker
from backend.ingestion_service import IngestionService
from backend.feature_engineering import assign_cost_bucket
from backend.model_engine import (
    explain_prediction_cached,
    simulate_interventions,
    get_action_recommendations,
    get_risk_tier,
    MODELS_DIR,
    PROCESSED_DIR
)
from backend.schemas import (
    PredictRequest,
    SimulateRequest,
    AlertAcknowledgeRequest,
    CreateAlertRequest,
    SnapshotIngestPayload,
    EGoSDispatchPayload,
    ErrorResponse
)
from backend.security.auth import (
    get_current_user,
    get_optional_user,
    require_role,
    create_access_token,
    UserClaims
)
from backend.security.headers import SecurityHeadersMiddleware
from backend.security.rate_limiter import rate_limit
from backend.security.audit import log_audit_event

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

# ---------------------------------------------------------------
# Application Initialization
# ---------------------------------------------------------------
app = FastAPI(
    title="PM-OCMS Infrastructure Predictive Analytics & Early Warning Platform",
    description="Secure Decision-Support System for Infrastructure Delays & Cost Overruns (SIH26017 Prototype)",
    version="2.1.0-production-spec",
    docs_url="/docs",
    redoc_url="/redoc"
)

# 1. Request ID Middleware
@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = req_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    return response

# 1b. Request Size Limit Middleware (Phase 4: Reject oversized payloads > 5MB, configurable)
MAX_REQUEST_SIZE = int(os.getenv("MAX_REQUEST_SIZE_MB", "5")) * 1024 * 1024

@app.middleware("http")
async def payload_size_limit_middleware(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl:
        try:
            if int(cl) > MAX_REQUEST_SIZE:
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={
                        "error": {
                            "code": "PAYLOAD_TOO_LARGE",
                            "message": f"Request body exceeds {MAX_REQUEST_SIZE // (1024*1024)}MB maximum permitted size.",
                            "request_id": getattr(request.state, "request_id", None)
                        }
                    }
                )
        except ValueError:
            pass
    return await call_next(request)

# 2. Security Headers Middleware
app.add_middleware(SecurityHeadersMiddleware)

# 3. Explicit CORS Allowlist (No wildcard, configurable via CORS_ORIGINS & FRONTEND_URL)
cors_env = os.getenv("CORS_ORIGINS", os.getenv("ALLOWED_ORIGINS", ""))
frontend_url = os.getenv("FRONTEND_URL", "").strip()

allowed_origins = [
    "http://127.0.0.1:8000",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://localhost:3000",
    "http://127.0.0.1:5500",
    "http://localhost:5500"
]

# Auto-detect Vercel environment URLs
vercel_url = os.getenv("VERCEL_URL", "").strip()
if vercel_url:
    allowed_origins.append(f"https://{vercel_url}")
vercel_prod_url = os.getenv("VERCEL_PROJECT_PRODUCTION_URL", "").strip()
if vercel_prod_url:
    allowed_origins.append(f"https://{vercel_prod_url}")

if cors_env:
    for o in cors_env.split(","):
        cleaned = o.strip()
        if cleaned and cleaned != "*" and cleaned not in allowed_origins:
            allowed_origins.append(cleaned)
if frontend_url and frontend_url != "*" and frontend_url not in allowed_origins:
    allowed_origins.append(frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "Retry-After"]
)

# 4. Global Sanitized Exception Handlers (Never leak stack traces)
@app.exception_handler(HTTPException)
async def custom_http_exception_handler(request: Request, exc: HTTPException):
    req_id = getattr(request.state, "request_id", None)
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        payload = exc.detail
        if "request_id" not in payload["error"]:
            payload["error"]["request_id"] = req_id
    else:
        payload = {
            "error": {
                "code": f"HTTP_{exc.status_code}",
                "message": str(exc.detail),
                "request_id": req_id
            }
        }
    return JSONResponse(status_code=exc.status_code, content=payload, headers=exc.headers)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    req_id = getattr(request.state, "request_id", None)
    errors_summary = []
    for err in exc.errors():
        loc = " -> ".join([str(l) for l in err.get("loc", [])])
        msg = err.get("msg", "Invalid value")
        errors_summary.append(f"{loc}: {msg}")
    
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request payload failed schema validation.",
                "details": errors_summary,
                "request_id": req_id
            }
        }
    )

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    req_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    # Log technical error securely server-side
    print(f"[UNHANDLED ERROR] [Request {req_id}] {type(exc).__name__}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred while processing the request. Please quote the request ID.",
                "request_id": req_id
            }
        }
    )

# ---------------------------------------------------------------
# In-Memory Cache: Machine Learning Pipelines & Metadata
# ---------------------------------------------------------------
classifier = None
regressor = None
shap_explainer = None
feature_names = []

try:
    classifier = joblib.load(os.path.join(MODELS_DIR, "delay_classifier.joblib"))
except Exception as e:
    print(f"[ML WARNING] Could not load classifier: {e}")

try:
    regressor = joblib.load(os.path.join(MODELS_DIR, "delay_regressor.joblib"))
except Exception as e:
    print(f"[ML WARNING] Could not load regressor: {e}")

try:
    shap_explainer = joblib.load(os.path.join(MODELS_DIR, "shap_explainer.joblib"))
except Exception as e:
    print(f"[ML WARNING] Could not load shap_explainer: {e}")

try:
    feature_names = joblib.load(os.path.join(MODELS_DIR, "feature_names.joblib"))
except Exception as e:
    print(f"[ML WARNING] Could not load feature_names: {e}")

model_metadata = {}
try:
    with open(os.path.join(MODELS_DIR, "model_metadata.json"), "r", encoding="utf-8") as f:
        model_metadata = json.load(f)
except Exception as e:
    print(f"[ML WARNING] Could not load model_metadata: {e}")

cost_summary = {}
try:
    with open(os.path.join(PROCESSED_DIR, "cost_summary.json"), "r", encoding="utf-8") as f:
        cost_summary = json.load(f)
except Exception as e:
    print(f"[ML WARNING] Could not load cost_summary: {e}")

# ---------------------------------------------------------------
# 1. Observability Endpoints
# ---------------------------------------------------------------
@app.get("/health", tags=["Observability"])
@app.get("/api/health", tags=["Observability"])
@app.get("/api/v1/health", tags=["Observability"])
def health_check():
    """Liveness probe indicating the service process is up."""
    return {
        "status": "healthy",
        "service": "pm-ocms-intelligence-platform",
        "version": "2.1.0",
        "timestamp": datetime_iso()
    }

@app.get("/ready", tags=["Observability"])
@app.get("/api/ready", tags=["Observability"])
@app.get("/api/v1/ready", tags=["Observability"])
def readiness_check():
    """Readiness probe checking database connectivity and model availability."""
    db_status = "connected"
    try:
        conn = get_db_connection()
        conn.cursor().execute("SELECT 1;").fetchone()
        conn.close()
    except Exception as e:
        db_status = f"error: {str(e)}"
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": {"code": "DATABASE_UNAVAILABLE", "message": "Database readiness check failed."}}
        )

    ml_ready = (classifier is not None and regressor is not None and shap_explainer is not None)

    return {
        "status": "ready",
        "database": db_status,
        "database_engine": "PostgreSQL" if IS_POSTGRES else "SQLite",
        "ml_models_loaded": ml_ready,
        "timestamp": datetime_iso()
    }

def datetime_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

# ---------------------------------------------------------------
# 2. Authentication & RBAC Helper Endpoints
# ---------------------------------------------------------------
@app.post("/api/v1/auth/demo-token", tags=["Authentication"])
def get_demo_token(role: Optional[str] = Query("VIEWER")):
    """
    Generates a signed JWT token for SIH hackathon evaluation of RBAC roles.
    Supported roles: ADMIN, OFFICER, ANALYST, VIEWER (with aliases like Ministry, Admin, Viewer).
    """
    raw_role = (role or "VIEWER").strip().upper()
    role_alias_map = {
        "ADMIN": "ADMIN",
        "ADMINISTRATOR": "ADMIN",
        "AUDITOR": "ADMIN",
        "MINISTRY": "OFFICER",
        "LINE MINISTRY": "OFFICER",
        "OFFICER": "OFFICER",
        "NODAL": "OFFICER",
        "ANALYST": "ANALYST",
        "ECONOMIST": "ANALYST",
        "VIEWER": "VIEWER",
        "PUBLIC": "VIEWER",
        "CITIZEN": "VIEWER"
    }
    role_upper = role_alias_map.get(raw_role, "VIEWER")
    user_map = {
        "ADMIN": ("00000000-0000-0000-0000-000000000001", "admin.infra@gov.in", "Director General (Infrastructure Intelligence)"),
        "OFFICER": ("00000000-0000-0000-0000-000000000002", "officer.railways@gov.in", "Executive Director (Works)"),
        "ANALYST": ("00000000-0000-0000-0000-000000000003", "analyst.gatishakti@gov.in", "Lead Infrastructure Economist"),
        "VIEWER": ("00000000-0000-0000-0000-000000000004", "viewer.public@gov.in", "Public Governance Auditor")
    }
    uid, email, name = user_map[role_upper]
    token = create_access_token(uid, email, role_upper, full_name=name)
    return {
        "access_token": token,
        "token_type": "Bearer",
        "role": role_upper,
        "user": {"id": uid, "email": email, "full_name": name}
    }

@app.get("/api/v1/auth/me", tags=["Authentication"])
def get_current_user_profile(user: UserClaims = Depends(get_current_user)):
    """Returns the profile and role claims of the authenticated user."""
    return {"user": user}

# ---------------------------------------------------------------
# 3. Core API v1 Endpoints
# ---------------------------------------------------------------
@app.get("/api/v1/summary", tags=["Executive Telemetry"])
def get_summary_v1():
    """Returns macroeconomic KPIs, sector/state benchmarks, and alert counts."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT 
        COUNT(*) as total_projects,
        SUM(CASE WHEN is_delayed = 1 THEN 1 ELSE 0 END) as delayed_count,
        SUM(CASE WHEN has_cost_overrun = 1 THEN 1 ELSE 0 END) as overrun_count,
        SUM(CASE WHEN revised_cost_is_set = 0 THEN 1 ELSE 0 END) as unrevised_count,
        SUM(CASE WHEN revised_date_is_missing = 1 THEN 1 ELSE 0 END) as missing_rev_date_count,
        SUM(CASE WHEN expenditure_cr > original_cost_cr THEN 1 ELSE 0 END) as overspent_count,
        AVG(CASE WHEN is_delayed = 1 THEN schedule_delay_days ELSE NULL END) as avg_delay_days,
        SUM(original_cost_cr) as total_proj_orig_cost,
        SUM(expenditure_cr) as total_proj_expenditure
    FROM projects;
    """)
    kpi_row = dict(cursor.fetchone())
    
    sectors = [dict(r) for r in cursor.execute("SELECT * FROM sector_benchmarks ORDER BY original_cost_cr DESC;").fetchall()]
    states = [dict(r) for r in cursor.execute("SELECT * FROM state_benchmarks ORDER BY original_cost_cr DESC;").fetchall()]
    progress = [dict(r) for r in cursor.execute("SELECT * FROM progress_brackets ORDER BY sr_no ASC;").fetchall()]
    
    cursor.execute("SELECT alert_severity, COUNT(*) as cnt FROM project_alerts GROUP BY alert_severity;")
    alerts_summary = {r["alert_severity"]: r["cnt"] for r in cursor.fetchall()}
    conn.close()
    
    delay_rate_pct = round((kpi_row["delayed_count"] / kpi_row["total_projects"]) * 100, 1) if kpi_row["total_projects"] else 0.0
    
    return {
        "kpi": {
            "total_projects": kpi_row["total_projects"],
            "delayed_projects": kpi_row["delayed_count"],
            "delay_rate_pct": delay_rate_pct,
            "cost_overrun_projects_count": kpi_row["overrun_count"],
            "not_yet_revised_count": kpi_row["unrevised_count"],
            "missing_rev_date_count": kpi_row["missing_rev_date_count"],
            "overspent_count": kpi_row["overspent_count"],
            "avg_delay_days": round(kpi_row["avg_delay_days"] or 0, 1),
            "total_original_cost_cr": cost_summary["total_original_cost_cr"],
            "total_revised_cost_cr": cost_summary["total_revised_cost_cr"],
            "total_expenditure_cr": cost_summary["total_expenditure_cr"],
            "total_net_escalation_cr": round(cost_summary["total_revised_cost_cr"] - cost_summary["total_original_cost_cr"], 2),
            "alerts_summary": alerts_summary
        },
        "sectors": sectors,
        "states": states,
        "physical_progress": progress,
        "provenance_tag": "[DATA FOUND IN UPLOADED FILE]"
    }

@app.get("/api/v1/projects", tags=["Project Registry"])
def get_projects_v1(
    q: Optional[str] = Query(None, max_length=100),
    sector: Optional[str] = Query(None, max_length=120),
    ministry: Optional[str] = Query(None, max_length=255),
    state: Optional[str] = Query(None, max_length=120),
    status: Optional[str] = Query(None, max_length=50),
    quality: Optional[str] = Query(None, max_length=50),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    limit: Optional[int] = Query(None, ge=1, le=100)
):
    """
    Server-side paginated project explorer with multi-criteria filtering.
    Maximum page size constrained to 100 records.
    """
    if limit is not None:
        page_size = limit

    conn = get_db_connection()
    cursor = conn.cursor()
    
    conditions = ["1=1"]
    params = []
    
    if q:
        search = f"%{q.strip().lower()}%"
        if IS_POSTGRES:
            conditions.append("(LOWER(p.project_name) LIKE %s OR CAST(p.project_code AS TEXT) LIKE %s)")
        else:
            conditions.append("(LOWER(p.project_name) LIKE ? OR CAST(p.project_code AS TEXT) LIKE ?)")
        params.extend([search, search])
        
    if sector and sector != "all":
        conditions.append(adapt_query("p.sector_name = ?"))
        params.append(sector)
        
    if ministry and ministry != "all":
        conditions.append(adapt_query("p.line_ministry = ?"))
        params.append(ministry)
        
    if state and state != "all":
        conditions.append(adapt_query("s.inferred_state = ?"))
        params.append(state)
        
    if status and status != "all":
        st = status.strip().lower()
        if st in ("delayed", "is_delayed"):
            conditions.append("p.is_delayed = 1")
        elif st in ("on_schedule", "onschedule", "on-schedule"):
            conditions.append("p.is_delayed = 0 AND p.revised_date_is_missing = 0")
        elif st in ("not_revised", "unrevised", "pending"):
            conditions.append("(p.revised_cost_is_set = 0 OR p.revised_date_is_missing = 1)")
        elif st in ("overrun", "cost_overrun", "cost_overruns"):
            conditions.append("p.cost_overrun_pct > 20")
        
    if quality and quality != "all":
        q_clean = quality.strip().lower()
        if q_clean == "clean":
            conditions.append("p.data_quality_flags = 'CLEAN'")
        elif q_clean == "anomalies":
            conditions.append("p.data_quality_flags != 'CLEAN'")
        
    where_clause = " WHERE " + " AND ".join(conditions)
    
    count_query = f"""
    SELECT COUNT(*) as total
    FROM projects p
    LEFT JOIN simulated_land_gis s ON p.project_code = s.project_code
    {where_clause}
    """
    cursor.execute(count_query, params)
    total_records = cursor.fetchone()["total"]
    total_pages = (total_records + page_size - 1) // page_size if total_records else 1
    
    offset = (page - 1) * page_size
    data_query = f"""
    SELECT 
        p.*,
        s.inferred_state,
        s.land_required_acres,
        s.land_acquired_pct,
        s.land_clearance_status,
        s.active_legal_disputes,
        s.source_tag as sim_tag
    FROM projects p
    LEFT JOIN simulated_land_gis s ON p.project_code = s.project_code
    {where_clause}
    ORDER BY p.original_cost_cr DESC
    LIMIT ? OFFSET ?
    """
    cursor.execute(data_query, params + [page_size, offset])
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    
    return {
        "page": page,
        "page_size": page_size,
        "limit": page_size,
        "total_records": total_records,
        "total_pages": total_pages,
        "projects": rows
    }

@app.get("/api/v1/projects/{code}", tags=["Project Registry"])
def get_project_detail_v1(code: int, request: Request, user: Optional[UserClaims] = Depends(get_optional_user)):
    """Fetches deep project telemetry, alerts, SHAP attributions, and mitigation protocols."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = adapt_query("""
    SELECT 
        p.*,
        s.inferred_state,
        s.latitude,
        s.longitude,
        s.land_required_acres,
        s.land_acquired_pct,
        s.land_clearance_status,
        s.active_legal_disputes,
        s.affected_families_count,
        s.rehabilitation_package_cr,
        s.source_tag as sim_tag
    FROM projects p
    LEFT JOIN simulated_land_gis s ON p.project_code = s.project_code
    WHERE p.project_code = ?
    """)
    cursor.execute(query, [code])
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "PROJECT_NOT_FOUND", "message": f"Project code #{code} not found in database."}}
        )
        
    project = dict(row)
    
    cursor.execute(adapt_query("""
    SELECT alert_id, alert_severity, alert_category, alert_title, alert_description, escalation_authority, status, acknowledged_at
    FROM project_alerts
    WHERE project_code = ?
    ORDER BY alert_id DESC;
    """), [code])
    alerts = [dict(r) for r in cursor.fetchall()]
    conn.close()
    
    # Compute live SHAP explainability
    input_row = pd.DataFrame([{
        "sector_name": project["sector_name"],
        "line_ministry": project["line_ministry"],
        "cost_scale_bucket": project["cost_scale_bucket"],
        "original_cost_cr": project["original_cost_cr"],
        "log_original_cost": project["log_original_cost"],
        "original_end_year": project["original_end_year"],
        "original_end_quarter": project["original_end_quarter"],
        "sector_delay_rate": project["sector_delay_rate"],
        "ministry_delay_rate": project["ministry_delay_rate"]
    }])
    
    prob = float(classifier.predict_proba(input_row)[0][1])
    est_delay = max(0, int(round(float(regressor.predict(input_row)[0]))))
    shap_factors = explain_prediction_cached(input_row, classifier, shap_explainer, feature_names)
    recommendations = get_action_recommendations(
        prob,
        int(project["schedule_delay_days"] or est_delay),
        project["sector_name"],
        project["line_ministry"],
        project["original_cost_cr"]
    )
    
    log_audit_event(request, action="PROJECT_VIEWED", resource_type="projects", resource_id=str(code), user=user)

    return {
        "project": project,
        "alerts": alerts,
        "ai_intelligence": {
            "delay_probability_pct": round(prob * 100, 1),
            "risk_tier": get_risk_tier(prob),
            "estimated_delay_days": est_delay,
            "estimated_delay_months": round(est_delay / 30.4, 1),
            "shap_factors": shap_factors,
            "action_recommendations": recommendations,
            "model_provenance": "Strict Pre-Construction Features (Zero Data Leakage)"
        },
        "provenance_labels": {
            "core_fields": "[DATA FOUND IN UPLOADED FILE]",
            "derived_metrics": "[DERIVED METRIC]",
            "land_gis_fields": "[DEMO/SIMULATION]"
        }
    }

@app.post(
    "/api/v1/predictions",
    tags=["Predictive Analytics"],
    dependencies=[Depends(rate_limit("inference"))]
)
def predict_project_v1(
    req: PredictRequest,
    request: Request,
    user: Optional[UserClaims] = Depends(get_optional_user)
):
    """
    Zero-leakage early-warning prediction using pre-construction features only.
    Generates genuine SHAP waterfall attribution and institutional mitigations.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(adapt_query("SELECT sector_delay_rate FROM projects WHERE sector_name = ? LIMIT 1;"), [req.sector_name])
    s_row = cursor.fetchone()
    sec_rate = float(s_row["sector_delay_rate"]) if s_row else float(model_metadata["base_delay_rate"])
    
    cursor.execute(adapt_query("SELECT ministry_delay_rate FROM projects WHERE line_ministry = ? LIMIT 1;"), [req.line_ministry])
    m_row = cursor.fetchone()
    min_rate = float(m_row["ministry_delay_rate"]) if m_row else float(model_metadata["base_delay_rate"])
    conn.close()
    
    cost = max(req.original_cost_cr, 1.0)
    log_cost = float(np.log1p(cost))
    bucket = assign_cost_bucket(cost)
    
    input_df = pd.DataFrame([{
        "sector_name": req.sector_name,
        "line_ministry": req.line_ministry,
        "cost_scale_bucket": bucket,
        "original_cost_cr": cost,
        "log_original_cost": log_cost,
        "original_end_year": req.planned_end_year,
        "original_end_quarter": req.planned_end_quarter,
        "sector_delay_rate": sec_rate,
        "ministry_delay_rate": min_rate
    }])
    
    prob = float(classifier.predict_proba(input_df)[0][1])
    delay_days = max(0, int(round(float(regressor.predict(input_df)[0]))))
    
    shap_factors = explain_prediction_cached(input_df, classifier, shap_explainer, feature_names)
    recommendations = get_action_recommendations(prob, delay_days, req.sector_name, req.line_ministry, cost)
    
    log_audit_event(
        request,
        action="PREDICTION_RUN",
        resource_type="ml_prediction",
        user=user,
        metadata={"sector": req.sector_name, "cost_cr": cost, "prob": prob}
    )

    return {
        "delay_probability_pct": round(prob * 100, 1),
        "risk_tier": get_risk_tier(prob),
        "estimated_delay_days": delay_days,
        "estimated_delay_months": round(delay_days / 30.4, 1),
        "shap_factors": shap_factors,
        "action_recommendations": recommendations,
        "model_provenance": "Strict Pre-Construction Features (Zero Data Leakage)"
    }

@app.post(
    "/api/v1/simulations",
    tags=["Decision Support"],
    dependencies=[Depends(rate_limit("inference"))]
)
def simulate_policy_v1(
    req: SimulateRequest,
    request: Request,
    user: Optional[UserClaims] = Depends(get_optional_user)
):
    """
    What-If policy intervention simulator modeling risk reduction and schedule compression.
    Results are labeled: 'MODEL SIMULATION — NOT AN OFFICIAL GOVERNMENT FORECAST'.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(adapt_query("SELECT sector_delay_rate FROM projects WHERE sector_name = ? LIMIT 1;"), [req.sector_name])
    s_row = cursor.fetchone()
    sec_rate = float(s_row["sector_delay_rate"]) if s_row else float(model_metadata["base_delay_rate"])
    
    cursor.execute(adapt_query("SELECT ministry_delay_rate FROM projects WHERE line_ministry = ? LIMIT 1;"), [req.line_ministry])
    m_row = cursor.fetchone()
    min_rate = float(m_row["ministry_delay_rate"]) if m_row else float(model_metadata["base_delay_rate"])
    conn.close()
    
    cost = max(req.original_cost_cr, 1.0)
    bucket = assign_cost_bucket(cost)
    
    base_input = {
        "sector_name": req.sector_name,
        "line_ministry": req.line_ministry,
        "cost_scale_bucket": bucket,
        "original_cost_cr": cost,
        "log_original_cost": float(np.log1p(cost)),
        "original_end_year": req.planned_end_year,
        "original_end_quarter": req.planned_end_quarter,
        "sector_delay_rate": sec_rate,
        "ministry_delay_rate": min_rate
    }
    
    interventions = {
        "fast_track_clearance": req.fast_track_clearance,
        "advance_land_row": req.advance_land_row,
        "milestone_funding": req.milestone_funding
    }
    
    res = simulate_interventions(base_input, interventions)
    res["provenance_disclaimer"] = "MODEL SIMULATION — NOT AN OFFICIAL GOVERNMENT FORECAST"

    log_audit_event(
        request,
        action="SIMULATION_RUN",
        resource_type="policy_simulation",
        user=user,
        metadata={"sector": req.sector_name, "interventions": interventions}
    )

    return res

@app.get("/api/v1/alerts", tags=["Escalation Alerts"])
def get_alerts_v1(
    severity: Optional[str] = Query(None, pattern="^(all|CRITICAL|HIGH|MEDIUM|LOW)$"),
    limit: int = Query(50, ge=1, le=200)
):
    """Priority risk watchlist for nodal monitoring officers."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
    SELECT 
        a.*,
        p.project_name,
        p.sector_name,
        p.line_ministry,
        p.original_cost_cr,
        p.revised_cost_cr,
        p.cost_overrun_pct,
        p.schedule_delay_days
    FROM project_alerts a
    JOIN projects p ON a.project_code = p.project_code
    """
    params = []
    if severity and severity != "all":
        query += adapt_query(" WHERE a.alert_severity = ?")
        params.append(severity.upper())
        
    query += " ORDER BY a.alert_id DESC LIMIT ?;"
    params.append(limit)
    
    cursor.execute(query, params)
    raw_alerts = [dict(r) for r in cursor.fetchall()]
    conn.close()

    formatted_alerts = []
    for a in raw_alerts:
        item = dict(a)
        orig = item.get("original_cost_cr") or 0.0
        revised = item.get("revised_cost_cr") or orig
        item["cost_overrun_cr"] = round(max(0.0, revised - orig), 2)
        # Ensure Phase 9 explicit field aliases
        item["severity"] = item.get("alert_severity")
        item["reason"] = item.get("alert_description")
        item["assigned_authority"] = item.get("assigned_authority") or item.get("escalation_authority", "Project Monitoring Group (PMG)")
        item["resolution_timestamp"] = item.get("resolution_timestamp") or (
            item.get("acknowledged_at") if item.get("status") in ("ACKNOWLEDGED", "RESOLVED") else None
        )
        formatted_alerts.append(item)

    return {"alerts": formatted_alerts, "total": len(formatted_alerts)}

@app.post(
    "/api/v1/alerts",
    tags=["Escalation Alerts"]
)
def create_alert_v1(
    req: CreateAlertRequest,
    request: Request,
    officer: UserClaims = Depends(require_role(["OFFICER", "ADMIN"]))
):
    """
    Creates an escalation alert with duplicate prevention.
    Restricted to OFFICER and ADMIN roles via RBAC.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if an active alert for this project with the same severity already exists (Phase 9 duplicate prevention)
    cursor.execute(adapt_query("""
    SELECT alert_id, project_code, alert_severity, status 
    FROM project_alerts 
    WHERE project_code = ? AND alert_severity = ? AND status = 'ACTIVE';
    """), (req.project_code, req.severity.upper()))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        return {
            "status": "DUPLICATE_PREVENTED",
            "message": f"Active {req.severity.upper()} alert already exists for project #{req.project_code}.",
            "alert_id": dict(existing)["alert_id"]
        }
        
    title = req.title or f"Early Warning: {req.severity.upper()} risk detected on Project #{req.project_code}"
    assigned = req.assigned_authority or "Project Monitoring Group (PMG)"
    
    if IS_POSTGRES:
        # PostgreSQL: use RETURNING id to get new row ID
        cursor.execute(adapt_query("""
        INSERT INTO project_alerts (
            project_code, alert_severity, alert_category, alert_title, alert_description,
            escalation_authority, assigned_authority, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE') RETURNING alert_id;
        """), (
            req.project_code,
            req.severity.upper(),
            req.category or "SCHEDULE_DELAY",
            title,
            req.reason,
            assigned,
            assigned
        ))
        new_id = cursor.fetchone()["alert_id"]
    else:
        cursor.execute(adapt_query("""
        INSERT INTO project_alerts (
            project_code, alert_severity, alert_category, alert_title, alert_description,
            escalation_authority, assigned_authority, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE');
        """), (
            req.project_code,
            req.severity.upper(),
            req.category or "SCHEDULE_DELAY",
            title,
            req.reason,
            assigned,
            assigned
        ))
        new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    log_audit_event(
        request,
        action="ALERT_CREATED",
        resource_type="alerts",
        resource_id=str(new_id),
        user=officer,
        metadata={"project_code": req.project_code, "severity": req.severity.upper(), "reason": req.reason}
    )
    
    return {
        "status": "CREATED",
        "alert_id": new_id,
        "project_code": req.project_code,
        "severity": req.severity.upper(),
        "reason": req.reason,
        "assigned_authority": assigned
    }

@app.post(
    "/api/v1/alerts/{alert_id}/acknowledge",
    tags=["Escalation Alerts"]
)
def acknowledge_alert_v1(
    alert_id: int,
    req: AlertAcknowledgeRequest,
    request: Request,
    officer: UserClaims = Depends(require_role(["OFFICER", "ADMIN"]))
):
    """
    Acknowledge or resolve an active project alert.
    Restricted to OFFICER and ADMIN roles via RBAC.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(adapt_query("SELECT alert_id, project_code FROM project_alerts WHERE alert_id = ?;"), [alert_id])
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "ALERT_NOT_FOUND", "message": f"Alert ID #{alert_id} not found."}}
        )

    now_str = datetime_iso()
    res_ts = now_str if req.status in ("ACKNOWLEDGED", "RESOLVED") else None
    cursor.execute(adapt_query("""
    UPDATE project_alerts
    SET status = ?, acknowledged_at = ?, acknowledged_by = ?, acknowledgement_notes = ?, resolution_timestamp = ?
    WHERE alert_id = ?;
    """), (req.status, now_str, officer.email, req.notes, res_ts, alert_id))
    conn.commit()
    conn.close()

    log_audit_event(
        request,
        action="ALERT_ACKNOWLEDGED",
        resource_type="alerts",
        resource_id=str(alert_id),
        user=officer,
        metadata={"status": req.status, "notes": req.notes}
    )

    return {
        "status": "SUCCESS",
        "alert_id": alert_id,
        "updated_status": req.status,
        "acknowledged_by": officer.email,
        "acknowledged_at": now_str,
        "resolution_timestamp": res_ts
    }

@app.post(
    "/api/v1/alerts/batch-dispatch",
    tags=["Escalation Alerts"]
)
def batch_dispatch_alerts_v1(
    request: Request,
    officer: UserClaims = Depends(require_role(["OFFICER", "ADMIN"]))
):
    """
    Batch dispatches active critical alerts to the Empowered Group of Secretaries (EGoS).
    Persists status update and registers immutable audit log event.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(adapt_query("""
    SELECT alert_id, project_code, alert_severity 
    FROM project_alerts 
    WHERE status = 'ACTIVE' AND alert_severity IN ('CRITICAL', 'HIGH')
    ORDER BY alert_id DESC
    LIMIT 25;
    """))
    rows = cursor.fetchall()
    if not rows:
        conn.close()
        return {"status": "NOOP", "dispatched_count": 0, "message": "No active critical alerts pending dispatch."}

    alert_ids = [dict(r)["alert_id"] for r in rows]
    now_str = datetime_iso()
    
    for aid in alert_ids:
        cursor.execute(adapt_query("""
        UPDATE project_alerts 
        SET status = 'ACKNOWLEDGED', 
            acknowledged_at = ?, 
            acknowledged_by = ?, 
            acknowledgement_notes = ? 
        WHERE alert_id = ?;
        """), (now_str, officer.email, "Batch dispatched to Empowered Group of Secretaries (EGoS) Agenda", aid))
    conn.commit()
    conn.close()

    log_audit_event(
        request,
        action="EGOS_BATCH_DISPATCH",
        resource_type="alerts",
        user=officer,
        metadata={"dispatched_alert_ids": alert_ids, "count": len(alert_ids)}
    )

    return {
        "status": "DISPATCHED",
        "dispatched_count": len(alert_ids),
        "dispatched_alert_ids": alert_ids,
        "message": f"Successfully dispatched {len(alert_ids)} critical exceptions to EGoS Agenda."
    }

@app.post(
    "/api/v1/simulations/dispatch-egos",
    tags=["Decision Support"]
)
def dispatch_simulation_egos_v1(
    payload: EGoSDispatchPayload,
    request: Request,
    officer: UserClaims = Depends(require_role(["OFFICER", "ADMIN"]))
):
    """
    Submits a simulated policy intervention package to Empowered Group of Secretaries (EGoS).
    Persists an escalation alert record and immutable audit log.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    p_code = payload.project_code or 1001
    p_name = payload.project_name or "National Infrastructure Corridor"
    knobs_desc = ", ".join(payload.selected_knobs) if payload.selected_knobs else "Section 3E/3F Possession, Mobilization Liquidity"
    title = f"EGoS Policy Intervention: #{p_code} ({payload.days_saved}d recovery)"
    desc = f"Intervention package for {p_name} ({payload.sector_name or 'Infrastructure'}). Mitigations: {knobs_desc}. Projected recovery: {payload.days_saved} days, Cost escalation averted: ₹{payload.cost_averted_cr} Cr."
    
    if IS_POSTGRES:
        cursor.execute(adapt_query("""
        INSERT INTO project_alerts (
            project_code, alert_severity, alert_category, alert_title, alert_description,
            escalation_authority, assigned_authority, status
        ) VALUES (?, 'HIGH', 'POLICY_INTERVENTION', ?, ?, 'Empowered Group of Secretaries (EGoS)', 'Cabinet Secretariat', 'ACTIVE')
        RETURNING alert_id;
        """), (p_code, title, desc))
        new_id = cursor.fetchone()["alert_id"]
    else:
        cursor.execute(adapt_query("""
        INSERT INTO project_alerts (
            project_code, alert_severity, alert_category, alert_title, alert_description,
            escalation_authority, assigned_authority, status
        ) VALUES (?, 'HIGH', 'POLICY_INTERVENTION', ?, ?, 'Empowered Group of Secretaries (EGoS)', 'Cabinet Secretariat', 'ACTIVE');
        """), (p_code, title, desc))
        new_id = cursor.lastrowid
        
    conn.commit()
    conn.close()
    
    log_audit_event(
        request,
        action="EGOS_POLICY_SUBMITTED",
        resource_type="policy_intervention",
        resource_id=str(new_id),
        user=officer,
        metadata={"project_code": p_code, "days_saved": payload.days_saved, "cost_averted_cr": payload.cost_averted_cr}
    )
    
    return {
        "status": "SUBMITTED",
        "tracking_id": f"EGOS-2026-{new_id:04d}",
        "alert_id": new_id,
        "message": f"Intervention Package submitted to EGoS Portal (Tracking #EGOS-2026-{new_id:04d})."
    }

@app.get("/api/v1/data-quality", tags=["Data Governance"])
def get_data_quality_v1():
    """Returns programmatic data quality findings and anomaly statistics."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT 
        COUNT(*) as total_records,
        SUM(CASE WHEN revised_cost_is_set = 0 THEN 1 ELSE 0 END) as unrevised_cost,
        SUM(CASE WHEN revised_date_is_missing = 1 THEN 1 ELSE 0 END) as missing_rev_date,
        SUM(CASE WHEN expenditure_cr > original_cost_cr THEN 1 ELSE 0 END) as overspent,
        SUM(CASE WHEN data_quality_flags LIKE '%IMPLAUSIBLE_FUTURE_DATE%' THEN 1 ELSE 0 END) as extreme_dates,
        SUM(CASE WHEN data_quality_flags LIKE '%EXTREME_SCHEDULE_OUTLIER%' THEN 1 ELSE 0 END) as schedule_outliers,
        SUM(CASE WHEN data_quality_flags LIKE '%EXTREME_COST_OVERRUN%' THEN 1 ELSE 0 END) as cost_outliers
    FROM projects;
    """)
    audit_stats = dict(cursor.fetchone())
    conn.close()
    
    return {
        "data_quality_audit": audit_stats,
        "provenance_note": "[DATA FOUND IN UPLOADED FILE] — Rigorous sentinel checks applied."
    }

@app.get("/api/v1/model/metrics", tags=["Predictive Analytics"])
def get_model_metrics_v1():
    """Returns genuine cross-validated champion ML metrics (Zero Fabrication)."""
    return {
        "champion_model": "v1.0.0-champion",
        "metadata": model_metadata,
        "provenance_note": "Metrics computed via Stratified 5-Fold Cross Validation on 80/20 train/test split."
    }

@app.get(
    "/api/v1/audit-logs",
    tags=["Governance & Compliance"]
)
def get_audit_logs_v1(
    limit: int = Query(50, ge=1, le=200),
    admin: UserClaims = Depends(require_role(["ADMIN"]))
):
    """
    Returns immutable system audit logs.
    Restricted to ADMIN role only.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(adapt_query("""
    SELECT * FROM audit_logs
    ORDER BY id DESC
    LIMIT ?;
    """), [limit])
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return {"audit_logs": rows, "total": len(rows)}

@app.get("/api/v1/metadata", tags=["Project Registry"])
def get_metadata_v1():
    """Returns real sector, ministry, and inferred state registries."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if IS_POSTGRES:
        sectors = [r["sector_name"] for r in cursor.execute("SELECT DISTINCT sector_name FROM projects ORDER BY sector_name;").fetchall()]
        ministries = [r["line_ministry"] for r in cursor.execute("SELECT DISTINCT line_ministry FROM projects ORDER BY line_ministry;").fetchall()]
        states = [r["inferred_state"] for r in cursor.execute("SELECT DISTINCT inferred_state FROM simulated_land_gis ORDER BY inferred_state;").fetchall()]
    else:
        sectors = [r[0] for r in cursor.execute("SELECT DISTINCT sector_name FROM projects ORDER BY sector_name;").fetchall()]
        ministries = [r[0] for r in cursor.execute("SELECT DISTINCT line_ministry FROM projects ORDER BY line_ministry;").fetchall()]
        states = [r[0] for r in cursor.execute("SELECT DISTINCT inferred_state FROM simulated_land_gis ORDER BY inferred_state;").fetchall()]
    conn.close()
    return {
        "sectors": sectors,
        "ministries": ministries,
        "states": states,
        "provenance_note": "Sectors and ministries from real Projects_Report.csv. States are [DEMO/SIMULATION] inferred labels."
    }

@app.get("/api/v1/dashboard/map", tags=["Spatial Analytics"])
def get_dashboard_map_v1():
    """Returns state aggregates and GIS simulation sample coordinates."""
    conn = get_db_connection()
    cursor = conn.cursor()
    states = [dict(r) for r in cursor.execute("SELECT * FROM state_benchmarks ORDER BY original_cost_cr DESC;").fetchall()]
    geo_projects = [dict(r) for r in cursor.execute("""
        SELECT 
            p.project_code,
            p.project_name,
            p.sector_name,
            p.line_ministry,
            p.original_cost_cr,
            p.is_delayed,
            p.schedule_delay_days,
            s.inferred_state,
            s.latitude,
            s.longitude,
            s.land_required_acres,
            s.land_acquired_pct,
            s.land_clearance_status,
            s.source_tag as sim_tag
        FROM projects p
        JOIN simulated_land_gis s ON p.project_code = s.project_code
        WHERE s.latitude IS NOT NULL AND s.longitude IS NOT NULL
        LIMIT 200;
    """).fetchall()]
    conn.close()
    return {
        "states": states,
        "geo_projects": geo_projects,
        "provenance_note": "State-level summaries are from [DATA FOUND IN UPLOADED FILE]. Geo coordinates and land parameters are [DEMO/SIMULATION]."
    }

# ---------------------------------------------------------------
# 3b. Continuous Ingestion & Data Governance Endpoints (Phases 1, 3, 5, 9, 20)
# ---------------------------------------------------------------
@app.get("/api/v1/data/sources", tags=["Data Governance"])
def list_data_sources_v1():
    """Returns registered official data sources (MoSPI PAIMANA, status, access methods)."""
    sources = get_data_sources()
    return {"sources": sources, "total": len(sources)}

@app.get("/api/v1/data/snapshots", tags=["Data Governance"])
def list_data_snapshots_v1():
    """Returns all registered data snapshots with metadata and record counts."""
    snapshots = get_data_snapshots()
    return {"snapshots": snapshots, "total": len(snapshots)}

@app.get("/api/v1/data/snapshots/{snapshot_id}", tags=["Data Governance"])
def get_snapshot_detail_v1(snapshot_id: str):
    """Returns deep snapshot metrics, checksums, and validation status."""
    snap = get_data_snapshot(snapshot_id)
    if not snap:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "SNAPSHOT_NOT_FOUND", "message": f"Snapshot '{snapshot_id}' not found."}}
        )
    return {"snapshot": snap}

@app.get("/api/v1/data/changes", tags=["Data Governance"])
def get_snapshot_changes_v1(
    from_snapshot: Optional[str] = Query(None, description="Starting snapshot ID"),
    to_snapshot: Optional[str] = Query(None, description="Ending snapshot ID")
):
    """
    Returns deterministic project-level deltas and macro change statistics between two snapshots.
    Identifies NEW, UPDATED, UNCHANGED, COMPLETED, and REMOVED projects without fabricating data.
    """
    changes = get_snapshot_change_events(from_snapshot, to_snapshot)
    return changes

@app.get("/api/v1/data/freshness", tags=["Data Governance"])
def get_data_freshness_v1():
    """
    Returns verified data freshness telemetry for the dashboard header.
    Phase 9: Explicitly identifies 'HISTORICAL SNAPSHOT', never claims fake 'LIVE DATA'.
    """
    return get_data_freshness()

@app.get("/api/v1/projects/{code}/history", tags=["Project Registry"])
def get_project_history_v1(code: int):
    """Returns historical versions of a project across snapshots."""
    history = get_project_history(code)
    return {"project_code": code, "history": history, "snapshots_recorded": len(history)}

@app.get("/api/v1/projects/{code}/risk-history", tags=["Predictive Analytics"])
def get_project_risk_history_v1(code: int):
    """Returns temporal risk progression and early-warning escalation history."""
    risk_history = get_project_risk_history(code)
    return {"project_code": code, "risk_history": risk_history, "predictions_recorded": len(risk_history)}

@app.get("/api/v1/model-insights", tags=["Predictive Analytics"])
def get_model_insights_v1():
    """Returns zero-leakage model architecture, cross-validation metrics, and drift monitoring summary."""
    dq = get_data_quality_v1()
    return {
        "metadata": model_metadata,
        "feature_schema": {
            "inception_features": [
                "sector_name", "line_ministry", "original_cost_cr", "log_original_cost",
                "cost_scale_bucket", "original_end_year", "original_end_quarter",
                "sector_delay_rate", "ministry_delay_rate"
            ],
            "quarantined_downstream_features": [
                "expenditure_cr", "expenditure_ratio", "revised_cost_cr",
                "revised_end_date", "schedule_delay_days", "has_cost_overrun"
            ],
            "zero_leakage_guarantee": True
        },
        "data_quality_audit": dq["data_quality_audit"]
    }

@app.post(
    "/api/v1/data/ingest",
    tags=["Data Governance"],
    dependencies=[Depends(rate_limit("admin"))]
)
def ingest_new_snapshot_v1(
    payload: SnapshotIngestPayload,
    request: Request,
    user: UserClaims = Depends(require_role(["ADMIN", "OFFICER"]))
):
    """
    Protected administrative ingestion endpoint (Requires ADMIN or OFFICER role).
    Accepts snapshot metadata and CSV payload, executes data quality gate,
    and updates project versions and change events.
    """
    if not payload.csv_content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "MISSING_CSV_CONTENT", "message": "csv_content is required for snapshot ingestion."}}
        )
    
    file_bytes = payload.csv_content.encode("utf-8")
    if len(file_bytes) > MAX_REQUEST_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"error": {"code": "PAYLOAD_TOO_LARGE", "message": f"Snapshot payload exceeds maximum permitted size ({MAX_REQUEST_SIZE // (1024*1024)}MB)."}}
        )

    service = IngestionService()
    result = service.ingest_snapshot(
        file_content=file_bytes,
        filename=f"{payload.snapshot_id}.csv",
        snapshot_id=payload.snapshot_id,
        snapshot_label=payload.snapshot_label,
        snapshot_date=payload.snapshot_date,
        executed_by=user.email,
        notes=payload.notes or "Ingested via API"
    )

    log_audit_event(
        request,
        action="SNAPSHOT_INGESTED",
        resource_type="data_snapshots",
        resource_id=payload.snapshot_id,
        user=user,
        metadata={"valid_rows": result.get("valid_records_ingested", 0)}
    )

    return result

# ---------------------------------------------------------------
# 4. Backward Compatibility Aliases (/api/* -> /api/v1/*)
# ---------------------------------------------------------------
@app.get("/api/summary", include_in_schema=False)
def legacy_summary():
    return get_summary_v1()

@app.get("/api/projects", include_in_schema=False)
def legacy_projects(q: Optional[str] = None, sector: Optional[str] = None, ministry: Optional[str] = None, state: Optional[str] = None, status: Optional[str] = "all", quality: Optional[str] = "all", page: int = 1, limit: int = 25):
    return get_projects_v1(q=q, sector=sector, ministry=ministry, state=state, status=status, quality=quality, page=page, page_size=limit)

@app.get("/api/project/{code}", include_in_schema=False)
def legacy_project_detail(code: int, request: Request):
    return get_project_detail_v1(code=code, request=request, user=None)

@app.post("/api/predict", include_in_schema=False)
def legacy_predict(req: PredictRequest, request: Request):
    return predict_project_v1(req=req, request=request, user=None)

@app.post("/api/simulate", include_in_schema=False)
def legacy_simulate(req: SimulateRequest, request: Request):
    return simulate_policy_v1(req=req, request=request, user=None)

@app.get("/api/alerts", include_in_schema=False)
def legacy_alerts(severity: Optional[str] = None, limit: int = 50):
    return get_alerts_v1(severity=severity, limit=limit)

@app.get("/api/metadata", include_in_schema=False)
def legacy_metadata():
    return get_metadata_v1()

@app.get("/api/dashboard/map", include_in_schema=False)
def legacy_dashboard_map():
    return get_dashboard_map_v1()

@app.get("/api/model-insights", include_in_schema=False)
def legacy_model_insights():
    dq = get_data_quality_v1()
    return {
        "metadata": model_metadata,
        "data_quality_audit": dq["data_quality_audit"]
    }

# ---------------------------------------------------------------
# 5. Static Files & Root Single-Page Application
# ---------------------------------------------------------------
if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/", include_in_schema=False)
def serve_index():
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "PM-OCMS Infrastructure Intelligence Platform Backend Online."}

@app.get("/app.js", include_in_schema=False)
def serve_app_js():
    js_file = os.path.join(FRONTEND_DIR, "app.js")
    if os.path.exists(js_file):
        return FileResponse(js_file, media_type="application/javascript")
    return Response(status_code=404)

@app.get("/style.css", include_in_schema=False)
def serve_style_css():
    css_file = os.path.join(FRONTEND_DIR, "style.css")
    if os.path.exists(css_file):
        return FileResponse(css_file, media_type="text/css")
    return Response(status_code=404)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.server:app", host="127.0.0.1", port=8000, reload=True)
