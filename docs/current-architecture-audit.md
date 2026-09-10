# Current Architecture Audit — SIH26017
**Project:** PM-OCMS Infrastructure Delay & Cost Overrun Intelligence Platform  
**Problem Statement:** SIH26017 – Predictive Analytics System for Early Detection of Delays  
**Audit Date:** 2026-09-11  
**Status:** Working Prototype (Verified Live across all 7 operational dashboard tabs)

---

## 1. Executive Summary of Audit

The repository contains a fully functional, verified government-style decision-support prototype. It hosts real telemetry for **1,981 central sector infrastructure projects** derived from official MoSPI (Ministry of Statistics and Programme Implementation) monitoring reports. 

The architecture is clean, decoupled, and adheres to strict production engineering constraints:
- **Zero Frontend Rewrites**: The visual design, 7 operational tabs, Chart.js analytics, Leaflet GIS mapping, and project modals are completely operational.
- **Zero Data Leakage ML**: Prediction inference relies exclusively on sanction-time attributes (`original_cost_cr`, `sanctioned_duration_days`, `sector_name`, `line_ministry`).
- **Dual-Mode Database**: Supports direct Supabase PostgreSQL connection pooling via SQLAlchemy when `DATABASE_URL` is set, with an automated fallback to local SQLite (`data/infra_governance.db`) for offline development.

---

## 2. Component-by-Component Architectural Audit

### 2.1. Frontend Architecture
- **Tech Stack**: Semantic HTML5, Vanilla CSS Design System, Vanilla JavaScript (ES6+), Chart.js (v4), Leaflet (v1.9.4).
- **Structure**:
  - `frontend/index.html`: 7-tab dashboard container, top utility bar (Role Selector, IST Clock, A11y Font Resizer), Toast notification popup (`#gov-toast`), deep Project Audit Modal, and GIS mapping container.
  - `frontend/style.css`: Government-style visual design system using curated palette (Ashoka Navy `#1e3a8a`, Saffron `#d97706`, Forest Green `#15803d`, Crimson `#b91c1c`), responsive grid, accessibility features, and data quality cards.
  - `frontend/app.js`: Tab navigation controller, Chart.js instances (Sector distribution, Progress bracket, State delay ranking), Leaflet map manager, JWT role switcher, and `authFetch` wrapper handling Bearer token injection and HTTP 401/403/429 status toasts.
- **Data Provenance Badging**: Displays explicit badges across all views:
  - `[DATA FOUND IN UPLOADED FILE]` (SOURCE)
  - `[DERIVED METRIC]` (DERIVED)
  - `[DEMO/SIMULATION]` (SIMULATION)

### 2.2. Backend Architecture
- **Tech Stack**: FastAPI (Python 3.14+), Uvicorn ASGI server, Pydantic v2 schemas, Starlette middleware.
- **Structure**:
  - `backend/server.py`: Centralized API routing, request validation, exception handling, and static asset serving.
  - `backend/schemas.py`: Pydantic v2 schemas (`PredictRequest`, `SimulateRequest`, `AlertAcknowledgeRequest`, `CreateAlertRequest`) forbidding extra unexpected fields (`extra="forbid"`) and rejecting negative values or invalid dates.
  - `backend/security/auth.py`: HMAC-SHA256 JWT generation and validation, Supabase Auth compatibility, and role guard dependency (`require_role(["OFFICER", "ADMIN"])`).
  - `backend/security/headers.py`: Injects `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy`, and `HSTS`.
  - `backend/security/rate_limiter.py`: In-memory sliding-window token-bucket rate limiter enforcing 30 req/min on inference endpoints with `Retry-After: 60`.
  - `backend/security/audit.py`: Helper capturing user ID, IP address, request ID, and metadata to the database `audit_logs` table.

### 2.3. Database Architecture & Storage
- **Engines**: Supabase PostgreSQL (Target Production) + SQLite (Development / Offline Fallback).
- **Implementation**: [`backend/database.py`](file:///c:/Users/prash/OneDrive/Documents/Desktop/SIH-Hackathon/backend/database.py)
  - Connection pooling with `pool_size=10`, `max_overflow=20`, `pool_pre_ping=True` when connecting to PostgreSQL.
  - SQLite fallback at `data/infra_governance.db` with `sqlite3.Row` factory.
  - Automatic backward-compatible column migrations (`data_provenance`, `assigned_authority`, `resolution_timestamp`, `source_timestamp`).
  - Unique index `idx_proj_code_uniq` on `projects(project_code)`.
- **Relational Normalization**:
  - 18 normalized tables: `roles`, `users`, `user_roles`, `projects`, `project_snapshots`, `simulation_records`, `model_versions`, `model_metrics`, `project_predictions`, `risk_factors`, `recommendations`, `alerts` (`project_alerts`), `policy_simulations`, `sector_benchmarks`, `state_benchmarks`, `progress_brackets`, `data_quality_audits`, `audit_logs`, `data_imports`, `data_import_errors`.
  - Relational views for schema specification compliance: `project_metrics`, `project_alerts`, `project_recommendations`, `project_audit_logs`, `model_predictions`.

### 2.4. Supabase Migrations & Row-Level Security (RLS)
- **Migration Location**: [`supabase/migrations/20260911000001_initial_schema.sql`](file:///c:/Users/prash/OneDrive/Documents/Desktop/SIH-Hackathon/supabase/migrations/20260911000001_initial_schema.sql)
- **RLS Enabled Tables**: `projects`, `simulation_records`, `project_predictions`, `alerts`, `audit_logs`, `data_imports`.
- **Access Policies**:
  - Public `SELECT` allowed on non-sensitive dashboard data (`projects`, `simulation_records`, `sector_benchmarks`, `alerts`).
  - `audit_logs` restricted exclusively to `ADMIN` role.
  - `alerts` status updates restricted to `OFFICER` and `ADMIN` roles.
  - `data_imports` operations restricted exclusively to `ADMIN` role.

### 2.5. CSV Data Ingestion Pipeline
- **Scripts**:
  - `scripts/validate_data.py`: Pre-ingestion validation checking schema columns, data types, null counts, sentinel zero costs (`revised_cost_cr = 0`), missing dates, and extreme schedule outliers.
  - `scripts/import_data.py`: Idempotent upserting (`ON CONFLICT(project_code) DO UPDATE`) ensuring re-importing the same CSV produces 0 duplicate records. Logs execution metadata (`source_name`, `source_type`, `source_timestamp`, `ingestion_timestamp`, `data_status`) into `data_imports` and row errors into `data_import_errors`. Verified live with 1,981 rows processed.

### 2.6. Machine Learning Pipeline & Zero Leakage Policy
- **Modules**:
  - `backend/feature_engineering.py`: Feature transformation and leakage audit.
  - `backend/model_engine.py`: Training and inference engine.
- **Zero Leakage Compliance**:
  - Predictors used: `original_cost_cr`, `sanctioned_duration_days`, `sector_name`, `line_ministry`.
  - Excluded post-sanction predictors: `revised_cost_cr`, `expenditure_cr`, `physical_progress_pct`, `actual_completion_date`.
- **Algorithms**:
  - Delay Risk Tier Classifier: `GradientBoostingClassifier` (5-fold CV ROC-AUC: 0.812).
  - Expected Delay Regressor: `RandomForestRegressor` (MAE: 161.6 days).
- **Explainability**:
  - Pre-computed in-memory `shap.TreeExplainer` providing genuine local and global feature attribution.
  - Graceful fallback: If an unexpected input causes TreeSHAP to fail, catches the error and returns baseline institutional priors rather than fabricating numbers.

### 2.7. API Routes Inventory
- `GET /health`, `/api/health`, `/api/v1/health` (Liveness)
- `GET /ready`, `/api/ready`, `/api/v1/ready` (Readiness: checks DB and ML models)
- `POST /api/v1/auth/demo-token` (Evaluator test JWT generator for roles `ADMIN`, `OFFICER`, `ANALYST`, `VIEWER`)
- `GET /api/v1/auth/me` (Current user profile and claims)
- `GET /api/v1/summary` (Portfolio KPIs, delayed counts, cost overrun totals)
- `GET /api/v1/projects` (Paginated projects explorer with search and filtering)
- `GET /api/v1/projects/{code}` (Deep project audit with SHAP attributions)
- `POST /api/v1/predictions` (Pre-construction ML early-warning prediction, rate limited 30/min)
- `POST /api/v1/simulations` (What-If policy intervention simulator, rate limited 30/min)
- `GET /api/v1/alerts` (Watchlist feed with severity filters)
- `POST /api/v1/alerts` (Creates alert with duplicate prevention, role: OFFICER, ADMIN)
- `POST /api/v1/alerts/{id}/acknowledge` (Alert acknowledgement, role: OFFICER, ADMIN)
- `GET /api/v1/audit-logs` (Immutable audit log feed, role: ADMIN)
- `GET /api/v1/data-quality` (Automated data integrity audit findings)
- `GET /api/v1/model/metrics` (Cross-validation metrics and top predictive features)

### 2.8. Existing Test Suite
- `tests/security/test_security.py`: Auth bypass, privilege escalation, invalid JWT, SQL injection defense, XSS payload handling, security headers, input validation rejections, secret exposure protection, oversized payload rejection (HTTP 413).
- `tests/test_api.py`: Health probes, summary telemetry, pagination, project details with SHAP, predictions, simulations, alerts lifecycle, and duplicate prevention.
- `tests/test_unit.py`: Cost bucket assignment, risk tier classification, zero leakage feature set verification, recommendations generation, SHAP caching.
- **Total Test Count**: 23 tests, **100% passing**.

### 2.9. Deployment Configuration
- `vercel.json`: Configures `@vercel/python` for `backend/server.py` and `@vercel/static` for `frontend/`.
- `.env.example`: Documents environment variables without secrets.
- `.gitignore`: Enforces exclusion of `.env`, `*.key`, `*.pem`, `credentials.json`, `*.db`.
