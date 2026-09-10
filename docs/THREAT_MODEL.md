# STRIDE Threat Model & Risk Assessment
**Project:** PM-OCMS Infrastructure Delay & Cost Overrun Intelligence Platform (SIH26017)  
**Methodology:** Microsoft STRIDE (Spoofing, Tampering, Repudiation, Information Disclosure, Denial of Service, Elevation of Privilege)

---

## 1. Asset Inventory

1. **National Project Telemetry**: Official sanction costs, revised budgets, commissioning milestones, line ministries (1,981 projects).
2. **User Accounts & Roles**: Officer, Analyst, and Administrator credentials.
3. **Machine Learning Model Artifacts**: Trained weights (`delay_classifier.joblib`, `delay_regressor.joblib`, `shap_explainer.joblib`).
4. **Predictive Risk Inferences**: Generated delay probabilities, slippage estimates, and SHAP feature drivers.
5. **System Audit Logs**: Immutable history of governance and prediction actions.
6. **Platform Secrets**: JWT secrets, database connection strings, Supabase keys.

---

## 2. STRIDE Threat Analysis Matrix

| STRIDE Category | Threat Description | Attack Vector | Mitigation Control Implemented | Residual Risk |
|---|---|---|---|---|
| **Spoofing** | Attacker impersonates an infrastructure officer or administrator | Forged or stolen JWT token | HMAC-SHA256 signature verification, strict token expiration, Supabase Auth | Low |
| **Tampering** | Unauthorized alteration of project budgets or alert statuses | Parameter tampering / direct API modification | Server-side Pydantic validation, RBAC checks on `/alerts/{id}/acknowledge`, RLS policies | Low |
| **Repudiation** | An officer denies having acknowledged a critical delay escalation alert | Disputed administrative action | Immutable `audit_logs` table storing actor user ID, client IP, timestamp, and request ID | Very Low |
| **Information Disclosure** | Leakage of internal database schema or unhandled server traces | Malformed payloads triggering unhandled exceptions | Global sanitized error handlers; strict exclusion of credentials via `.gitignore` | Very Low |
| **Denial of Service** | Resource exhaustion via continuous heavy ML inference calls | High-frequency bot requests to `/predictions` or `/simulations` | Sliding-window in-memory rate limiting (30 req/min for inference, 429 status) | Low |
| **Elevation of Privilege** | A VIEWER user executes administrative data imports or audits | Manipulating role claim in client payload | Server-side role guard `require_role(...)` that ignores client-claimed roles and relies only on verified JWT | Very Low |

---

## 3. Defense-in-Depth Summary

```
Browser Client
   |
   |-- 1. Security Headers (CSP, HSTS, X-Frame-Options, X-Content-Type-Options)
   |-- 2. Explicit CORS Origin Allowlist
   v
Application Gateway
   |
   |-- 3. Rate Limiter (Sliding Window per IP)
   |-- 4. JWT Authentication Guard (HMAC-SHA256 / Supabase Auth)
   |-- 5. Role-Based Access Control Dependency (ADMIN / OFFICER / ANALYST / VIEWER)
   v
Business Logic & ML Engine
   |
   |-- 6. Pydantic v2 Schema Enforcement (Range bounds, forbid extra fields)
   |-- 7. Zero-Leakage Pre-Construction Feature Isolation
   v
Database Persistence
   |
   |-- 8. PostgreSQL Row Level Security (RLS) Policies
   |-- 9. Immutable Audit Event Logging
```
