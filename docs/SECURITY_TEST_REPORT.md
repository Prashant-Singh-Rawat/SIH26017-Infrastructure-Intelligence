# Security & Penetration Test Report — SIH26017
**Project:** PM-OCMS Infrastructure Delay & Cost Overrun Intelligence Platform  
**Test Suite:** `tests/security/test_security.py`  
**Execution Environment:** Python 3.14.3, Pytest 9.1.1, Starlette/FastAPI TestClient  
**Test Execution Date:** 2026-09-11  
**Overall Security Verdict:** 100% PASS (9/9 Security Test Suites Passing)

---

## 1. Test Summary Matrix

| Test Identifier | Threat Vector Tested | Test Vector / Payload | Expected Defense | Observed Result | Status |
| :--- | :--- | :--- | :--- | :---: | :---: |
| `test_auth_bypass_prevention` | Anonymous Mutation & Audit Access | Unauthenticated `POST /api/v1/alerts/1/acknowledge`, `GET /api/v1/audit-logs` | Rejected with `HTTP 401 Unauthorized` | `401 Unauthorized` returned | **PASS** |
| `test_rbac_privilege_escalation_prevention` | Role Boundary Violation (Horizontal / Vertical) | `VIEWER` acknowledging alert; `OFFICER`/`ANALYST` reading audit logs | Rejected with `HTTP 403 Forbidden` (`FORBIDDEN_ROLE`) | `403 Forbidden` returned | **PASS** |
| `test_invalid_jwt_handling` | Signature Forgery & Token Expiry | Malformed token string; Token with negative timestamp (`exp = now - 3600`) | Rejected with `HTTP 401` (`INVALID_TOKEN` / `TOKEN_EXPIRED`) | `401 Unauthorized` returned | **PASS** |
| `test_sql_injection_defense` | SQL Injection via Search Parameters | `' OR '1'='1`, `'; DROP TABLE projects; --`, `UNION SELECT 1,2..` | Parameterized SQL treats input as literal string | Clean `200 OK` with 0 records or safe match; No 500 error | **PASS** |
| `test_xss_payload_handling` | Cross-Site Scripting Injection | `<script>alert('xss')</script>` in search query parameter | Sanitized string lookup; No execution or reflective payload | Clean `200 OK` with 0 matches | **PASS** |
| `test_security_headers_present` | MIME Confusion, Clickjacking, Protocol Downgrade | Response inspection on `/health` probe | Headers injected: `CSP`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `HSTS` | All headers present | **PASS** |
| `test_input_validation_rejections` | Malicious / Impossible Inputs & Mass Assignment | Negative outlay (`-200.0 Cr`); Extra field injection (`extra_field_attack`) | Pydantic v2 rejects payload with `HTTP 422 Unprocessable Content` | `422 Unprocessable Content` returned | **PASS** |
| `test_secret_exposure_protection` | Secret Credential Leakage in Probes | Inspection of `/ready` probe output for `password`, `secret`, `service_role` | Sanitized system readiness response without credential leak | Zero secrets exposed | **PASS** |
| `test_oversized_payload_rejection` | Denial of Service via Large Payloads | Request header `Content-Length: 10485760` (10 MB > 5 MB limit) | Rejected with `HTTP 413 Payload Too Large` | `413 Payload Too Large` returned | **PASS** |

---

## 2. Test Execution Log (Pytest Artifact)

```
============================= test session starts =============================
platform win32 -- Python 3.14.3, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\prash\OneDrive\Documents\Desktop\SIH-Hackathon

tests/security/test_security.py::test_auth_bypass_prevention PASSED      [ 11%]
tests/security/test_security.py::test_rbac_privilege_escalation_prevention PASSED [ 22%]
tests/security/test_security.py::test_invalid_jwt_handling PASSED        [ 33%]
tests/security/test_security.py::test_sql_injection_defense PASSED       [ 44%]
tests/security/test_security.py::test_xss_payload_handling PASSED        [ 55%]
tests/security/test_security.py::test_security_headers_present PASSED    [ 66%]
tests/security/test_security.py::test_input_validation_rejections PASSED [ 77%]
tests/security/test_security.py::test_secret_exposure_protection PASSED  [ 88%]
tests/security/test_security.py::test_oversized_payload_rejection PASSED [100%]

======================== 9 passed, 6 warnings in 4.05s ========================
```

---

## 3. Defense Implementation Details

1. **SQL Injection Defense**:
   All database queries in [`backend/database.py`](file:///c:/Users/prash/OneDrive/Documents/Desktop/SIH-Hackathon/backend/database.py) and [`backend/server.py`](file:///c:/Users/prash/OneDrive/Documents/Desktop/SIH-Hackathon/backend/server.py) use parameterized binding (`?` in SQLite and `$1` in PostgreSQL). No user inputs are concatenated into SQL queries.
2. **XSS Protection**:
   Dynamic HTML in [`frontend/app.js`](file:///c:/Users/prash/OneDrive/Documents/Desktop/SIH-Hackathon/frontend/app.js) sanitizes text interpolation using `.textContent` and escapes string attributes. The `Content-Security-Policy` header restricts script sources strictly to self and whitelisted CDNs (`jsdelivr`, `unpkg`).
3. **Payload Guard**:
   Inbound request bodies exceeding 5MB are intercepted before memory allocation by `payload_size_limit_middleware` in `backend/server.py`.
