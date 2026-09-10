# Security Architecture & Controls
**Project:** PM-OCMS Infrastructure Delay & Cost Overrun Intelligence Platform (SIH26017)  
**Version:** 2.1.0-production-spec

---

## 1. Threat Defense Matrix

| Vulnerability Vector | Risk Level | Defense Mechanism Implemented | Enforcement Layer |
|---|---|---|---|
| **Broken Authentication** | Critical | Signed JWTs (HMAC-SHA256) with expiry validation and Supabase Auth integration | `backend/security/auth.py` |
| **Privilege Escalation** | High | Server-side role guard `require_role(...)` with roles: `ADMIN`, `OFFICER`, `ANALYST`, `VIEWER` | FastAPI Dependencies |
| **SQL Injection** | Critical | Parameterized queries (`?` in SQLite, `%s` / ORM in Postgres); dynamic clauses strictly sanitized | `backend/server.py`, `database.py` |
| **Cross-Site Scripting (XSS)** | High | Strict `Content-Security-Policy`, `X-XSS-Protection`, and DOM innerText sanitization | `backend/security/headers.py` |
| **Clickjacking** | Medium | `X-Frame-Options: DENY` and `frame-ancestors 'none'` in CSP | HTTP Response Headers |
| **Denial of Service (DoS)** | High | Sliding-window in-memory rate limiting (IP-based, 429 status with `Retry-After`) | `backend/security/rate_limiter.py` |
| **Overly Permissive CORS** | Medium | Explicit allowlist (development and production domains; no `*` with credentials) | `CORSMiddleware` |
| **Information Leakage** | Medium | Global exception handler catches all unhandled errors; returns opaque request IDs without stack traces | `backend/server.py` |
| **Secret Exposure** | Critical | Zero credentials in source code; `.env` excluded via `.gitignore`; secrets loaded via environment variables | System Environment |

---

## 2. Role-Based Access Control (RBAC) Specification

| Role Name | Hierarchy Level | Allowed Capabilities | Restricted Capabilities |
|---|---|---|---|
| **VIEWER** | Level 1 | Read-only dashboards, search project explorer, view data quality audits | Cannot trigger ML predictions, run policy simulations, acknowledge alerts, or view audit logs |
| **ANALYST** | Level 2 | All VIEWER rights + run live ML delay predictions + execute What-If policy simulations | Cannot acknowledge alerts, manage data imports, or view system audit logs |
| **OFFICER** | Level 3 | All ANALYST rights + audit project details + acknowledge/resolve critical escalation alerts | Cannot manage data imports or view global audit logs |
| **ADMIN** | Level 4 | Full governance access: execute data imports, view immutable audit logs, update model rollouts | None (Full System Authority) |

---

## 3. Row-Level Security (RLS) on Supabase PostgreSQL

All core tables in `supabase/migrations/20260911000001_initial_schema.sql` enforce PostgreSQL Row Level Security:

```sql
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE alerts ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE data_imports ENABLE ROW LEVEL SECURITY;

-- Public can read projects and alerts
CREATE POLICY "Public read on projects" ON projects FOR SELECT USING (true);
CREATE POLICY "Public read on alerts" ON alerts FOR SELECT USING (true);

-- Only Officer and Admin can acknowledge alerts
CREATE POLICY "Officers acknowledge alerts" ON alerts FOR UPDATE
USING (
    EXISTS (
        SELECT 1 FROM user_roles ur
        JOIN roles r ON ur.role_id = r.id
        WHERE ur.user_id = auth.uid() AND r.name IN ('OFFICER', 'ADMIN')
    )
);

-- Only Admin can view audit logs
CREATE POLICY "Admins read audit logs" ON audit_logs FOR SELECT
USING (
    EXISTS (
        SELECT 1 FROM user_roles ur
        JOIN roles r ON ur.role_id = r.id
        WHERE ur.user_id = auth.uid() AND r.name = 'ADMIN'
    )
);
```

---

## 4. Content-Security-Policy (CSP) Details

The following CSP header is enforced by `SecurityHeadersMiddleware`:
```
default-src 'self';
script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com;
style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net https://unpkg.com;
font-src 'self' https://fonts.gstatic.com data:;
img-src 'self' data: https://*.tile.openstreetmap.org;
connect-src 'self' http://127.0.0.1:* http://localhost:*;
frame-ancestors 'none';
base-uri 'self';
```
*(OpenStreetMap tile servers and CDN scripts are explicitly permitted; external frame embeddings are strictly forbidden).*
