# PM-OCMS Infrastructure Delay & Cost Overrun Intelligence Platform
**Smart India Hackathon 2026 | Problem Statement: SIH26017**  
*Secure Decision-Support System for Infrastructure Early-Warning & Land Acquisition Delays*

---

> [!NOTE]
> **Prototype & Non-Government Disclaimer**:
> This platform is an engineering prototype designed for the **Smart India Hackathon (SIH26017)**. It models decision-support processes for infrastructure governance. It does not claim official certification or represent an operational Government of India production portal.
> 
> **Data Provenance**:
> - **Source Telemetry** (`[DATA FOUND IN UPLOADED FILE]`): 1,981 central sector projects, administrative ministries, and financial outlays are directly ingested from official MoSPI CSV reports.
> - **Predictive Analytics** (`[DERIVED METRIC]`): Risk probabilities, delay durations, and SHAP drivers are computed via strict zero-leakage pre-construction ML models.
> - **Land Acquisition Layer** (`[DEMO/SIMULATION]`): Land acres, title dispute counts, R&R compensation, and GPS coordinates are synthetic demonstration attributes clearly segregated from official audit records.

---

## 1. Architectural Highlights

- **Full-Stack Target**: Single-Page HTML/CSS/JS Frontend on **Vercel** + High-Performance **FastAPI** Backend + **Supabase PostgreSQL** Database.
- **Enterprise Security**:
  - Signed JWT Authentication with Role-Based Access Control (**ADMIN**, **OFFICER**, **ANALYST**, **VIEWER**).
  - PostgreSQL **Row-Level Security (RLS)** policies with least-privilege access.
  - Defense-in-depth **Security Headers** (`Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `HSTS`).
  - Sliding-window thread-safe **Rate Limiting** protecting ML inference endpoints (HTTP 429 with `Retry-After`).
  - Strict **Pydantic v2 Request Validation** rejecting unexpected fields, negative costs, and invalid dates.
  - Immutable **Audit Logging** (`audit_logs` table) capturing actor user ID, client IP, request ID, and timestamp.
- **Machine Learning Governance**:
  - Strict zero-leakage pre-construction features only.
  - Champion Gradient Boosting Classifier (**ROC-AUC: 0.9189**, 5-Fold CV: **0.9235**).
  - Random Forest Regressor (**MAE: 161.6 Days**, R²: **0.8848**).
  - Sub-millisecond genuine **TreeSHAP** feature attributions.

---

## 2. Directory Structure

```
.
├── backend/
│   ├── models/                   # Serialized ML pipelines & metadata
│   ├── security/                 # Auth, RBAC, Rate Limiting, Security Headers, Audit
│   │   ├── auth.py
│   │   ├── headers.py
│   │   ├── rate_limiter.py
│   │   └── audit.py
│   ├── database.py               # Dual-mode connector (Supabase Postgres + SQLite fallback)
│   ├── feature_engineering.py    # Zero-leakage feature pipeline
│   ├── ingestion.py              # Raw CSV batch parser
│   ├── model_engine.py           # Champion model trainers & SHAP caching
│   ├── schemas.py                # Pydantic v2 schemas
│   └── server.py                 # FastAPI application gateway & API v1 routes
├── data/
│   ├── raw/                      # 5 Official CSV source files
│   └── processed/                # Processed datasets & cost summary
├── docs/                         # Comprehensive Engineering Documentation
│   ├── ARCHITECTURE_AUDIT.md
│   ├── ARCHITECTURE.md
│   ├── SECURITY.md
│   ├── DATABASE.md
│   ├── API.md
│   ├── ML_PIPELINE.md
│   ├── DATA_DICTIONARY.md
│   ├── DATA_PIPELINE.md
│   ├── DATA_SOURCES.md
│   ├── SNAPSHOT_ARCHITECTURE.md
│   ├── DATA_VERSIONING.md
│   ├── MODEL_RETRAINING_POLICY.md
│   ├── DATA_FRESHNESS.md
│   ├── DEPLOYMENT.md
│   ├── DISASTER_RECOVERY.md
│   ├── THREAT_MODEL.md
│   └── TESTING.md
├── frontend/                     # Interactive Single-Page Application (7 Tabs + Data Update Center)
│   ├── index.html
│   ├── style.css
│   └── app.js
├── scripts/                      # Automated ingestion & validation CLI tools
│   ├── validate_data.py
│   └── import_data.py
├── supabase/
│   └── migrations/               # PostgreSQL DDL migrations & Continuous Ingestion Tables
│       ├── 20260911000001_initial_schema.sql
│       └── 20260911000002_continuous_ingestion_snapshots.sql
├── tests/                        # Automated Pytest Suite (31 Tests Passing)
│   ├── test_unit.py
│   ├── test_api.py
│   ├── test_continuous_ingestion.py
│   └── security/
│       └── test_security.py
├── .env.example                  # Environment configuration reference
├── vercel.json                   # Vercel deployment configuration
└── README.md
```

---

## 3. Quick Start (Local Development)

### 3.1. Install Dependencies
```powershell
pip install fastapi uvicorn pandas numpy scikit-learn shap joblib pydantic pyjwt starlette pytest
```

### 3.2. Validate CSV Data & Ingest
```powershell
# Validate all source CSVs
python scripts/validate_data.py

# Idempotently ingest projects into database
python scripts/import_data.py
```

### 3.3. Run Automated Tests
```powershell
# Run the complete test suite (31/31 Passing - 100% Pass Rate)
python -m pytest tests/ -v
```
*(31 automated tests passing covering Auth bypass, RBAC, SQL injection, XSS, headers, rate limiting, data freshness, snapshot catalog, change detection engine, project history, and CSV formula injection defense).*

### 3.4. Start the Application
```powershell
python -m uvicorn backend.server:app --host 127.0.0.1 --port 8000 --reload
```
Navigate to: **`http://127.0.0.1:8000/`**

---

## 4. API Endpoints Reference (`/api/v1/`)

### Data Governance & Ingestion (`/api/v1/data/*`):
- `GET /api/v1/data/sources`: Official source registry (MoSPI PAIMANA).
- `GET /api/v1/data/snapshots`: Historical snapshot catalog with SHA-256 checksums.
- `GET /api/v1/data/snapshots/{id}`: Snapshot detail and project breakdown.
- `GET /api/v1/data/changes`: Deterministic change detection deltas (NEW, UPDATED, UNCHANGED, COMPLETED).
- `GET /api/v1/data/freshness`: Public data freshness telemetry ("HISTORICAL SNAPSHOT", never fake "LIVE").
- `POST /api/v1/data/ingest`: Protected ingestion gate (Requires ADMIN/OFFICER role + Data Quality Gate).

### Projects & Historical Trajectory:
- `GET /api/v1/projects`: Paginated explorer (1,981 baseline projects).
- `GET /api/v1/projects/{code}`: Project detail with real-time TreeSHAP explainability.
- `GET /api/v1/projects/{code}/history`: Multi-snapshot historical telemetry for a project.
- `GET /api/v1/projects/{code}/risk-history`: Temporal risk tier escalation trajectory.


| Method | Route | Description | Access Control |
|---|---|---|---|
| `GET` | `/health` | Application liveness probe | Public |
| `GET` | `/ready` | Database & ML readiness check | Public |
| `POST`| `/api/v1/auth/demo-token` | Generate signed JWT for role testing | Public |
| `GET` | `/api/v1/summary` | Macro KPIs across 1,981 projects | Public |
| `GET` | `/api/v1/projects` | Server-side paginated project explorer | Public |
| `GET` | `/api/v1/projects/{code}` | Project detail with SHAP attributions | Public / Authenticated |
| `POST`| `/api/v1/predictions` | Zero-leakage early-warning prediction | Authenticated (Rate Limited: 30/min) |
| `POST`| `/api/v1/simulations` | What-If policy intervention simulator | Authenticated (Rate Limited: 30/min) |
| `GET` | `/api/v1/alerts` | Prioritized risk escalation feed | Public |
| `POST`| `/api/v1/alerts/{id}/acknowledge` | Acknowledge/resolve active alert | **OFFICER**, **ADMIN** |
| `GET` | `/api/v1/data-quality` | Data quality audit findings | Public |
| `GET` | `/api/v1/model/metrics` | Cross-validated champion model metrics | Public |
| `GET` | `/api/v1/audit-logs` | Immutable audit log records | **ADMIN** only |
| `GET` | `/api/v1/metadata` | Real sectors, line ministries, states | Public |
| `GET` | `/api/v1/dashboard/map` | State benchmarks and GIS point samples | Public |

---

## 5. Security & RBAC Interactive Testing

In the top government utility bar of the dashboard, you can interactively switch the active role using the **Role** dropdown:
1. **VIEWER**: Can explore projects, overview metrics, and audits; cannot execute predictions or acknowledge alerts.
2. **ANALYST**: Can execute live delay predictions and What-If policy simulations.
3. **OFFICER**: Can acknowledge project escalation alerts and audit telemetry.
4. **ADMIN**: Full authority, access to immutable audit logs and system administration.

For complete documentation, refer to the [docs/](file:///c:/Users/prash/OneDrive/Documents/Desktop/SIH-Hackathon/docs/) directory.
