# Security Policy & Governance Specification (SIH26017)
**Platform:** PM-OCMS Infrastructure Delay & Cost Overrun Intelligence Platform  
**Target:** Production-Grade Security Architecture  
**Document Classification:** Public Security Standard

---

## 1. Threat Model & STRIDE Analysis

| Threat Category | Primary Risk Vectors | Architectural Mitigation |
| :--- | :--- | :--- |
| **Spoofing** | Forged identities, forged client tokens | HMAC-SHA256 signed JWT tokens with expiry checks (`exp`) validated strictly on the server against `SUPABASE_JWT_SECRET`. |
| **Tampering** | Parameter tampering, SQL injection, malicious payloads | Pydantic v2 schemas reject forbidden fields (`extra="forbid"`), validate numeric bounds, and enforce parameterized SQL queries across all ORM and raw adapters. |
| **Repudiation** | Denying administrative actions or alert changes | Immutable append-only `audit_logs` records every high-impact mutation (`ALERT_ACKNOWLEDGED`, `ALERT_CREATED`, `PREDICTION_RUN`, `SIMULATION_RUN`, `DATA_IMPORTED`) with actor ID, IP address, and Request ID. |
| **Information Disclosure** | Secret leakage, stack trace leakage, internal paths | Sanitized global exception interceptor catches all errors, logs tracebacks server-side, and returns clean `{ "error": { "code": "...", "message": "...", "request_id": "..." } }`. Zero secrets in client-side code. |
| **Denial of Service** | Inference request storms, oversized payloads | Sliding-window token-bucket rate limiter enforces 30 req/min/IP on ML endpoints (`/predictions`, `/simulations`). Inbound payload size limiter rejects bodies > 5MB with `HTTP 413`. |
| **Elevation of Privilege**| Low-privileged users modifying alerts or reading logs | Server-side Role-Based Access Control (RBAC) enforces strict role guards: `PUBLIC_VIEWER` < `ANALYST` < `OFFICER` < `ADMIN`. Client-side claims are never trusted. Row-Level Security (RLS) restricts database access at the PostgreSQL engine level. |

---

## 2. Authentication & Authorization Architecture

- **Token Protocol**: HMAC-SHA256 signed JWT tokens.
- **Roles & Permissions**:
  - `PUBLIC_VIEWER`: Read-only access to executive dashboards, projects explorer, and alert watchlist.
  - `ANALYST`: Viewer access + permissions to execute early-warning predictions and What-If policy simulations.
  - `OFFICER`: Analyst access + permissions to create, acknowledge, escalate, and resolve project alerts.
  - `ADMIN`: Full governance authority including audit log inspection, data imports, and model rollouts.
- **Token Verification**: Tokens must be supplied in the `Authorization: Bearer <TOKEN>` HTTP header.

---

## 3. Database Security & Row-Level Security (RLS)

- **Principle**: Deny-by-default.
- **PostgreSQL RLS**: Activated on all exposed tables in [`supabase/migrations/20260911000001_initial_schema.sql`](file:///c:/Users/prash/OneDrive/Documents/Desktop/SIH-Hackathon/supabase/migrations/20260911000001_initial_schema.sql).
- **Service Role Isolation**: The `SUPABASE_SERVICE_ROLE_KEY` is strictly confined to server-side background pipelines and is **never** committed to version control or transmitted to the browser.

---

## 4. Network & Transport Security

- **CORS Allowlist**: Configured via `ALLOWED_ORIGINS` / `FRONTEND_URL`. Wildcards (`"*"`) with credentials are completely forbidden.
- **HTTP Security Headers**:
  - `Content-Security-Policy`: Permits only self, Chart.js/Leaflet CDNs, and OpenStreetMap tiles.
  - `X-Frame-Options: DENY`: Mitigates clickjacking.
  - `X-Content-Type-Options: nosniff`: Prevents MIME-confusion attacks.
  - `Referrer-Policy: strict-origin-when-cross-origin`: Minimizes referrer information leakage.
  - `Strict-Transport-Security`: Enforces HTTPS (`max-age=31536000; includeSubDomains`).
  - `Permissions-Policy`: Disables unnecessary browser capabilities (geolocation, camera, microphone, payment).

---

## 5. Input Validation & Defense-in-Depth

- **Strict Schemas**: Implemented in `backend/schemas.py` using Pydantic v2 `StrictBaseModel` (`extra="forbid"`, `str_strip_whitespace=True`).
- **Validation Rules**:
  - Negative costs are rejected (`gt=0.0`).
  - Implausible future dates beyond 2050 are rejected.
  - Out-of-bounds fiscal quarters (`1 - 4`) are rejected.
- **SQL Injection Defense**: Parameter substitution (`?` / `$1`) is mandatory across all queries.

---

## 6. Audit Logging & Non-Repudiation

- High-impact events are captured in `audit_logs`:
  - `action`: `PROJECT_VIEWED`, `PREDICTION_RUN`, `SIMULATION_RUN`, `ALERT_ACKNOWLEDGED`, `ALERT_CREATED`, `DATA_IMPORTED`
  - `actor_id`: User UUID or `anonymous`
  - `request_id`: Unique UUID generated per request
  - `ip_address`: Client IP (for forensic analysis)
  - `timestamp`: UTC ISO timestamp
- **Secret Filtering**: Passwords, tokens, API keys, and connection strings are strictly stripped prior to logging.

---

## 7. Incident Response & Reporting

To report a vulnerability or security defect in this decision-support platform, submit a security advisory with:
- Endpoint URL and HTTP method
- Proof-of-concept payload or step-by-step reproduction
- Observed response vs expected response

All reports are triaged within 24 hours.
