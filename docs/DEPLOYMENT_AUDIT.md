# Deployment Audit — SIH26017
**Project:** Infrastructure Delay & Cost Overrun Intelligence Platform  
**Target:** Supabase PostgreSQL + Vercel + FastAPI  
**Audit Date:** 2026-09-11  
**Audit Status:** Pre-Deployment Verification Complete

---

## 1. Executive Summary

This audit assesses the current readiness of the PM-OCMS Infrastructure Delay & Cost Overrun Intelligence Platform for deployment to **Vercel** (Frontend & Backend API) and **Supabase** (PostgreSQL Database & Auth).

The application is fully functional locally at `http://127.0.0.1:8000/` with:
- **1,981 projects** derived from official MoSPI CSV telemetry.
- **7 operational dashboard tabs** passing all interactive browser verification.
- **23/23 automated tests passing** (`python -m pytest tests/ -v`).
- **Zero Data Leakage ML**: Pre-construction early-warning engine with TreeSHAP explainability.
- **Defensive Security Controls**: Inbound request size limiter (5MB), sliding-window rate limiting (30 req/min/IP), security headers (CSP, HSTS, X-Frame), and server-side RBAC.

---

## 2. Component-by-Component Audit

### 2.1. Frontend Architecture
- **Framework**: Semantic HTML5, Vanilla CSS Design System, Vanilla JavaScript (ES6+), Chart.js (v4.4.1), Leaflet (v1.9.4).
- **Deployment Model**: Static assets served via Vercel CDN (`@vercel/static`) or FastAPI `StaticFiles`.
- **API Base URL**: Dynamically configured via `window.API_BASE_URL` in `frontend/app.js` with fallback to relative paths (`/api/v1/...`). This allows the frontend to operate seamlessly when deployed alongside FastAPI on Vercel or when hosted on a distinct frontend domain.
- **State & Role Management**: Interactive role selector in top bar generating signed JWT tokens via `/api/v1/auth/demo-token`.

### 2.2. Backend Framework & Architecture
- **Framework**: FastAPI (Python 3.14+) with ASGI server (Uvicorn).
- **Architecture**: Modular layout (`backend/server.py`, `backend/schemas.py`, `backend/database.py`, `backend/model_engine.py`, `backend/security/`).
- **Input Validation**: Pydantic v2 schemas (`StrictBaseModel`) rejecting unexpected extra fields (`extra="forbid"`), negative costs, and invalid dates.
- **Request Limits**: Enforces a strict 5MB maximum body size via middleware (`HTTP 413 PAYLOAD_TOO_LARGE`).
- **Rate Limiting**: Thread-safe sliding-window token-bucket limiter in `backend/security/rate_limiter.py` capping inference at 30 requests/minute per client IP (`HTTP 429 Too Many Requests`).

### 2.3. Database Access Layer
- **Implementation**: [`backend/database.py`](file:///c:/Users/prash/OneDrive/Documents/Desktop/SIH-Hackathon/backend/database.py)
- **Production Mode (PostgreSQL)**: Utilizes SQLAlchemy connection pooling (`pool_size=10`, `max_overflow=20`, `pool_pre_ping=True`) when `DATABASE_URL` is set to a PostgreSQL connection string.
- **Development Mode (SQLite Fallback)**: Automatically falls back to `data/infra_governance.db` when `DATABASE_URL` is absent, running automated column migrations and creating relational views.
- **Query Safety**: All SQL queries use parameter substitution (`?` / `$1`); zero user-controlled string concatenation.

### 2.4. Supabase Database & Migrations
- **Authoritative Schema**: [`supabase/migrations/20260911000001_initial_schema.sql`](file:///c:/Users/prash/OneDrive/Documents/Desktop/SIH-Hackathon/supabase/migrations/20260911000001_initial_schema.sql)
- **Tables (18)**: `roles`, `users`, `user_roles`, `projects`, `project_snapshots`, `simulation_records`, `model_versions`, `model_metrics`, `project_predictions`, `risk_factors`, `recommendations`, `alerts` (`project_alerts`), `policy_simulations`, `sector_benchmarks`, `state_benchmarks`, `progress_brackets`, `data_quality_audits`, `audit_logs`, `data_imports`, `data_import_errors`.
- **Relational Views**: `project_metrics`, `project_alerts`, `project_recommendations`, `project_audit_logs`, `model_predictions`.
- **Row-Level Security (RLS)**: Deny-by-default policies defined for `projects`, `simulation_records`, `alerts`, `audit_logs`, `data_imports`.

### 2.5. Machine Learning Model Loading
- **Pipelines**: `delay_classifier.joblib` (`GradientBoostingClassifier`) and `delay_regressor.joblib` (`RandomForestRegressor`).
- **Explainability**: `shap_explainer.joblib` (`shap.TreeExplainer`).
- **Loading Mechanism**: Serialized models are loaded into memory once on application startup (`backend/server.py`), eliminating per-request disk I/O.
- **Zero Leakage**: Strict feature contract excludes all post-sanction variables (`revised_cost_cr`, `expenditure_cr`, `actual_completion_date`, `physical_progress_pct`).

### 2.6. CORS & Security Headers
- **CORS Allowlist**: Configured in `backend/server.py` using `ALLOWED_ORIGINS` / `FRONTEND_URL`. Wildcards (`"*"`) with credentials are fully prohibited.
- **Security Headers**: `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`, `Strict-Transport-Security`, and `Permissions-Policy`.

### 2.7. Vercel Configuration & Packaging
- **Routing**: [`vercel.json`](file:///c:/Users/prash/OneDrive/Documents/Desktop/SIH-Hackathon/vercel.json) routes `/api/(.*)`, `/health`, `/ready`, `/docs` to `backend/server.py` and static assets to `frontend/`.
- **Dependencies**: [`requirements.txt`](file:///c:/Users/prash/OneDrive/Documents/Desktop/SIH-Hackathon/requirements.txt) pins required serverless packages.
- **CLI Status**: Vercel CLI v56.2.0 is installed locally; cloud push requires user authentication (`vercel login`).

---

## 3. What Must Be Configured for Live Cloud Deployment

1. **Supabase Cloud Project**:
   - Run migration script `supabase/migrations/20260911000001_initial_schema.sql` in the Supabase SQL Editor.
   - Run `python scripts/import_data.py --version v2026.09`.
2. **Environment Variables on Vercel**:
   - `DATABASE_URL=postgresql://postgres:[PASSWORD]@db.[PROJECT-REF].supabase.co:5432/postgres`
   - `SUPABASE_URL=https://[PROJECT-REF].supabase.co`
   - `SUPABASE_ANON_KEY=[ANON-KEY]`
   - `SUPABASE_SERVICE_ROLE_KEY=[SERVICE-ROLE-KEY]`
   - `FRONTEND_URL=https://[YOUR-VERCEL-DEPLOYMENT].vercel.app`
   - `ENVIRONMENT=production`
