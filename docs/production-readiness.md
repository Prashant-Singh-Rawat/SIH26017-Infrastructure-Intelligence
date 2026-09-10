# SIH26017 Production Readiness

## Architecture
**PASS**
- Centralized FastAPI backend cleanly separated from client-side presentation.
- Dual-mode database layer supporting Supabase PostgreSQL and local SQLite offline fallback.
- In-memory caching for machine learning models and SHAP explainers to minimize inference overhead.

## Supabase
**PASS**
- Dual-mode connection manager in `backend/database.py` utilizes SQLAlchemy connection pooling (`pool_size=10`, `max_overflow=20`, `pool_pre_ping=True`) when `DATABASE_URL` is configured.
- Seamless fallback to local SQLite (`data/infra_governance.db`) with automatic column migrations and view creation when running without external cloud dependencies.

## PostgreSQL Schema
**PASS**
- Normalized 18-table schema defined in [`supabase/migrations/20260911000001_initial_schema.sql`](file:///c:/Users/prash/OneDrive/Documents/Desktop/SIH-Hackathon/supabase/migrations/20260911000001_initial_schema.sql).
- Unique constraints on `projects(project_code)`.
- Foreign key cascades on `project_snapshots`, `risk_factors`, `recommendations`, `data_import_errors`.
- B-Tree indexes on `project_code`, `sector`, `ministry`, `state`, `is_delayed`, `original_cost`, `completion_date`, `alert_severity`, and `audit_logs(action)`.
- Relational views matching Phase 2 specifications: `project_metrics`, `project_alerts`, `project_recommendations`, `project_audit_logs`, `model_predictions`.

## RLS
**PASS**
- Deny-by-default architecture configured in PostgreSQL migrations.
- Public read access permitted on non-sensitive dashboard aggregates and projects.
- Row-level update permissions on alerts restricted to `OFFICER` and `ADMIN`.
- System audit logs and data imports restricted exclusively to `ADMIN`.
- Documented in detail in [`docs/supabase-rls.md`](file:///c:/Users/prash/OneDrive/Documents/Desktop/SIH-Hackathon/docs/supabase-rls.md).

## Authentication
**PASS**
- HMAC-SHA256 signed JWT tokens compatible with Supabase Auth.
- Expiration verification (`exp`) and malformed signature rejection verified.
- Interactive token generator endpoint `/api/v1/auth/demo-token` provided for hackathon evaluators.

## Authorization
**PASS**
- Server-side Role-Based Access Control (RBAC) enforced via FastAPI `Depends(require_role([...]))`.
- Role hierarchy: `ADMIN` (4) > `OFFICER` (3) > `ANALYST` (2) > `PUBLIC_VIEWER` (1).
- Privilege escalation attempts return `HTTP 403 Forbidden` with descriptive structured error envelopes.

## API
**PASS**
- Fully standardized `/api/v1/` route hierarchy.
- Backward-compatible legacy aliases preserved (`/api/projects`, `/api/summary`, etc.).
- Complete OpenAPI v3 documentation available at `/docs` and `/redoc`.

## Security
**PASS**
- Explicit CORS allowlist avoiding wildcard origins in production.
- Mandatory HTTP security headers: `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy`, `Permissions-Policy`, and `HSTS`.
- Inbound payload size limiter enforcing a 5MB maximum (`HTTP 413 PAYLOAD_TOO_LARGE`).
- Sliding-window rate limiter enforcing 30 requests/minute per client IP on inference endpoints (`HTTP 429 Too Many Requests`).
- Sanitized exception handlers eliminating internal stack traces from responses.

## ML Zero-Leakage
**PASS**
- Pre-construction early-warning models strictly utilize sanction-time predictors (`original_cost_cr`, `sanctioned_duration_days`, `sector_name`, `line_ministry`).
- Downstream post-sanction features (`revised_cost_cr`, `expenditure_cr`, `physical_progress_pct`, `actual_completion_date`) are strictly quarantined.
- Documented in [`docs/ml-data-leakage-policy.md`](file:///c:/Users/prash/OneDrive/Documents/Desktop/SIH-Hackathon/docs/ml-data-leakage-policy.md).

## SHAP Explainability
**PASS**
- Pre-computed `shap.TreeExplainer` on Gradient Boosting trees returns genuine positive and negative risk feature attributions.
- Graceful fallback: If an unexpected input causes TreeSHAP computation to fail, the system catches the exception and returns a transparent notice instead of fabricating numbers.

## Data Provenance
**PASS**
- Explicit categorization across all dashboard views and responses:
  - `[DATA FOUND IN UPLOADED FILE]` (SOURCE)
  - `[DERIVED METRIC]` (DERIVED)
  - `[DEMO/SIMULATION]` (SIMULATION)
- Land acquisition fields (parcels, disputes, R&R compensation, GPS pins) are clearly disclosed as simulated demonstration data.
- Documented in [`docs/data-provenance.md`](file:///c:/Users/prash/OneDrive/Documents/Desktop/SIH-Hackathon/docs/data-provenance.md).

## Data Ingestion
**PASS**
- Idempotent upserting in [`scripts/import_data.py`](file:///c:/Users/prash/OneDrive/Documents/Desktop/SIH-Hackathon/scripts/import_data.py) using `ON CONFLICT(project_code) DO UPDATE`.
- Re-importing official MoSPI CSV files produces zero duplicate records.
- Ingestion metadata (`source_name`, `source_type`, `source_timestamp`, `ingestion_timestamp`, `data_status`) logged in `data_imports`.
- Validation errors quarantined in `data_import_errors`.

## Reliability
**PASS**
- Observability probes active: `/health`, `/ready`, `/api/health`, `/api/ready`, `/api/v1/health`, `/api/v1/ready`.
- Transactional context manager in `backend/database.py` ensures rollback on failure.
- Request ID correlation headers (`X-Request-ID`) attached to every response.

## Performance
**PASS**
- Server-side pagination (`?page=1&page_size=25`, max 100).
- Indexed database queries on project codes, sectors, states, and delay flags.
- In-memory caching for ML artifacts avoids per-request disk deserialization.

## Testing
**PASS**
- Automated test suite in `tests/` executes **23 tests with 100% PASS** via `python -m pytest tests/ -v`.
- Covers authentication, authorization, SQL injection, XSS handling, headers, rate limiting, payload limits, API contracts, and alert deduplication.

## Vercel
**BLOCKED — USER VERCEL/SUPABASE CONFIGURATION REQUIRED**
- **Explanation**: The Vercel deployment configuration ([`vercel.json`](file:///c:/Users/prash/OneDrive/Documents/Desktop/SIH-Hackathon/vercel.json)) and Python serverless dependency specification ([`requirements.txt`](file:///c:/Users/prash/OneDrive/Documents/Desktop/SIH-Hackathon/requirements.txt)) are created and verified. However, live deployment to Vercel requires authenticating with the user's external Vercel account (`vercel login` / `vercel --prod`) and configuring environment variables in the Vercel dashboard.

## 7-Tab Regression
**PASS**
- Automated browser acceptance test executed across all 7 tabs on `http://127.0.0.1:8000/`:
  - Tab 1 (Executive Overview): 1,981 projects, 1,267 delayed, cost KPIs, charts loaded.
  - Tab 2 (Master Projects Explorer): 1,981 records, search filter, deep audit modal with TreeSHAP waterfall.
  - Tab 3 (Early Warning & Risk Evaluator): Pre-construction inference, risk tier, expected delay, SHAP factors.
  - Tab 4 (What-If Policy Simulator): Fast-track toggle, baseline vs simulated scenario, days saved, assumptions.
  - Tab 5 (Critical Alerts Watchlist): Switched to `OFFICER`, executed alert acknowledgement live with toast.
  - Tab 6 (Land & GIS Demonstration): Leaflet map initialized, state markers, popup with `[DEMO/SIMULATION]` banner.
  - Tab 7 (Data Quality & Integrity Audit): 5 automated finding cards, affected row counters, severity badges.

## Secrets Audit
**PASS**
- `.gitignore` verified to exclude `.env`, `.env.*`, `*.key`, `*.pem`, `credentials.json`, `*.db`.
- `.env.example` sanitized to contain blank values only with zero hardcoded credentials.
- No privileged `SUPABASE_SERVICE_ROLE_KEY` or database passwords exposed in client code.

## Final Deployment Status
**BLOCKED — USER VERCEL/SUPABASE CONFIGURATION REQUIRED**
- **Explanation**: The local application is 100% functional, hardened, and verified. Full cloud production deployment to Supabase and Vercel is ready from a codebase perspective, but requires the user to supply their real cloud credentials (`DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`) and execute `supabase db push` and `vercel --prod`.
