# API Specification & Integration Reference
**Project:** PM-OCMS Infrastructure Delay & Cost Overrun Intelligence Platform (SIH26017)  
**API Version:** `v1`  
**Base URL:** `/api/v1`

---

## 1. Authentication Headers

All role-gated endpoints require an HTTP Bearer JWT token:
```http
Authorization: Bearer <JWT_ACCESS_TOKEN>
```
To obtain a signed test token for SIH review, call:
```http
POST /api/v1/auth/demo-token?role=ANALYST
```
Supported roles: `ADMIN`, `OFFICER`, `ANALYST`, `VIEWER`.

---

## 2. Observability & Health

### `GET /health`
Liveness probe.
- **Access**: Public
- **Response**:
  ```json
  {
    "status": "healthy",
    "service": "pm-ocms-intelligence-platform",
    "version": "2.1.0",
    "timestamp": "2026-09-11T00:00:00Z"
  }
  ```

### `GET /ready`
Readiness probe testing database connection and ML model status.
- **Access**: Public
- **Response**:
  ```json
  {
    "status": "ready",
    "database": "connected",
    "database_engine": "PostgreSQL",
    "ml_models_loaded": true,
    "timestamp": "2026-09-11T00:00:00Z"
  }
  ```

---

## 3. Project Telemetry & Explorer

### `GET /api/v1/summary`
Macro telemetry and portfolio KPIs across all 1,981 projects.
- **Access**: Public
- **Response**:
  ```json
  {
    "kpi": {
      "total_projects": 1981,
      "delayed_projects": 1267,
      "delay_rate_pct": 64.0,
      "total_original_cost_cr": 3712662.0,
      "total_revised_cost_cr": 4278402.0,
      "avg_delay_days": 931.7
    },
    "sectors": [...],
    "states": [...]
  }
  ```

### `GET /api/v1/projects`
Server-side paginated project table.
- **Query Parameters**:
  - `q` (string, optional): Search by project name or code.
  - `sector` (string, optional): Sector filter.
  - `ministry` (string, optional): Line ministry filter.
  - `status` (string, default `"all"`): `"delayed"`, `"on_schedule"`, `"not_revised"`.
  - `page` (int, default `1`): Page number.
  - `page_size` (int, default `25`, max `100`): Items per page.
- **Response**:
  ```json
  {
    "page": 1,
    "page_size": 25,
    "total_records": 1981,
    "total_pages": 80,
    "projects": [...]
  }
  ```

### `GET /api/v1/projects/{project_code}`
Deep project audit with SHAP attribution factors.
- **Access**: Public (Enriched with user audit if token provided).
- **Response**:
  ```json
  {
    "project": {...},
    "alerts": [...],
    "ai_intelligence": {
      "delay_probability_pct": 28.9,
      "risk_tier": "Low Risk (Green)",
      "estimated_delay_days": 154,
      "shap_factors": [
        {"feature": "original_end_year", "shap_value": 0.21, "direction": "RISK_INCREASE", "impact_pct": 42.1}
      ],
      "action_recommendations": [...]
    }
  }
  ```

---

## 4. Machine Learning & Decision Support

### `POST /api/v1/predictions`
Run live zero-leakage delay risk inference.
- **Rate Limit**: 30 requests / minute
- **Request Body**:
  ```json
  {
    "sector_name": "Railways",
    "line_ministry": "Ministry of Railways",
    "original_cost_cr": 2500.0,
    "planned_end_year": 2028,
    "planned_end_quarter": 2
  }
  ```
- **Response**:
  ```json
  {
    "delay_probability_pct": 14.8,
    "risk_tier": "Low Risk (Green)",
    "estimated_delay_days": 68,
    "estimated_delay_months": 2.2,
    "shap_factors": [...],
    "action_recommendations": [...]
  }
  ```

### `POST /api/v1/simulations`
What-If policy intervention simulator.
- **Rate Limit**: 30 requests / minute
- **Request Body**:
  ```json
  {
    "sector_name": "Roads & Highways",
    "line_ministry": "Ministry of Road Transport & Highways",
    "original_cost_cr": 1800.0,
    "planned_end_year": 2027,
    "planned_end_quarter": 2,
    "fast_track_clearance": true,
    "advance_land_row": true,
    "milestone_funding": false
  }
  ```
- **Response**:
  ```json
  {
    "baseline": {"delay_probability_pct": 29.4, "estimated_delay_days": 154},
    "simulated": {"delay_probability_pct": 11.2, "estimated_delay_days": 68},
    "impact": {"days_saved": 86, "risk_reduction_pct_pts": 18.2},
    "provenance_disclaimer": "MODEL SIMULATION — NOT AN OFFICIAL GOVERNMENT FORECAST"
  }
  ```

---

## 5. Escalation Alerts & Governance

### `GET /api/v1/alerts`
Priority alerts feed with dual field naming (`severity`/`alert_severity`, `reason`/`alert_description`, `assigned_authority`, `resolution_timestamp`).
- **Query Parameters**: `severity` (`CRITICAL`, `HIGH`, `MEDIUM`, `LOW`), `limit`.
- **Response**:
  ```json
  {
    "total": 40,
    "alerts": [
      {
        "alert_id": 1346,
        "project_code": 400277,
        "severity": "CRITICAL",
        "alert_severity": "CRITICAL",
        "reason": "Cost overrun exceeds +245% of sanctioned budget",
        "alert_description": "Cost overrun exceeds +245% of sanctioned budget",
        "assigned_authority": "Project Monitoring Group (PMG)",
        "status": "ACTIVE",
        "created_at": "2026-09-10T12:00:00Z",
        "resolution_timestamp": null
      }
    ]
  }
  ```

### `POST /api/v1/alerts`
Create an escalation alert with automatic duplicate prevention.
- **Required Role**: `OFFICER` or `ADMIN`
- **Request Body**:
  ```json
  {
    "project_code": 400277,
    "severity": "HIGH",
    "reason": "Critical path schedule milestone missed by > 180 days.",
    "category": "SCHEDULE_DELAY",
    "assigned_authority": "Project Monitoring Group (PMG)"
  }
  ```
- **Response (Success)**:
  ```json
  {
    "status": "CREATED",
    "alert_id": 1347,
    "project_code": 400277,
    "severity": "HIGH",
    "reason": "Critical path schedule milestone missed by > 180 days."
  }
  ```
- **Response (Duplicate Prevented)**:
  ```json
  {
    "status": "DUPLICATE_PREVENTED",
    "message": "Active HIGH alert already exists for project #400277.",
    "alert_id": 1347
  }
  ```

### `POST /api/v1/alerts/{alert_id}/acknowledge`
Acknowledge or update alert status, recording resolution timestamp and officer audit log.
- **Required Role**: `OFFICER` or `ADMIN`
- **Request Body**:
  ```json
  {
    "status": "ACKNOWLEDGED",
    "notes": "Joint inspection scheduled with PM GatiShakti taskforce."
  }
  ```

### `GET /api/v1/audit-logs`
Immutable audit log feed.
- **Required Role**: `ADMIN`
