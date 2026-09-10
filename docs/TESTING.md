# Automated Testing & Quality Assurance Suite
**Project:** PM-OCMS Infrastructure Delay & Cost Overrun Intelligence Platform (SIH26017)  
**Framework:** Pytest + FastAPI TestClient

---

## 1. Test Suite Organization

```
tests/
├── __init__.py
├── test_unit.py              # Unit tests for feature pipelines & algorithms
├── test_api.py               # API integration tests for /api/v1 endpoints
└── security/
    ├── __init__.py
    └── test_security.py      # Security, penetration, and RBAC authorization tests
```

---

## 2. Test Execution Instructions

Run the complete automated test suite from the repository root:

```bash
# Execute all tests with verbose output
python -m pytest tests/ -v

# Execute security tests only
python -m pytest tests/security/test_security.py -v

# Execute unit and API tests only
python -m pytest tests/test_unit.py tests/test_api.py -v
```

---

## 3. Test Coverage Inventory

### 3.1. Security Tests (`tests/security/test_security.py`)
- `test_auth_bypass_prevention`: Verifies unauthenticated calls to protected routes receive HTTP 401.
- `test_rbac_privilege_escalation_prevention`: Verifies VIEWER cannot acknowledge alerts, and ANALYST cannot access audit logs (HTTP 403).
- `test_invalid_jwt_handling`: Verifies malformed and expired JWT tokens are rejected with HTTP 401.
- `test_sql_injection_defense`: Tests SQL injection payloads (`' OR '1'='1`, `UNION SELECT`) in query search parameters.
- `test_xss_payload_handling`: Tests script injection attempts in search queries.
- `test_security_headers_present`: Verifies CSP, X-Frame-Options, X-Content-Type-Options, HSTS, and Referrer-Policy headers.
- `test_input_validation_rejections`: Verifies Pydantic rejects negative costs, out-of-bound years, and unexpected extra fields with HTTP 422.
- `test_secret_exposure_protection`: Verifies health and readiness responses do not leak secrets or credentials.

### 3.2. API Integration Tests (`tests/test_api.py`)
- `test_health_and_readiness_endpoints`: Validates `/health` and `/ready` response contracts.
- `test_summary_telemetry`: Verifies macro KPIs across 1,981 projects.
- `test_paginated_projects_explorer`: Tests server-side pagination, search queries, and total counts.
- `test_project_detail_with_shap`: Verifies deep project view, live SHAP attribution factors, and mitigations.
- `test_predictions_endpoint`: Validates ML early-warning prediction contracts.
- `test_simulations_endpoint`: Validates What-If policy intervention calculations and days saved.

### 3.3. Unit Tests (`tests/test_unit.py`)
- `test_cost_bucket_assignment`: Verifies capital outlay bucketing (Tier 1 to Tier 5).
- `test_risk_tier_classification`: Verifies probability mapping to risk tiers (Critical, High, Medium, Low).
- `test_zero_leakage_feature_specification`: Asserts no post-construction features exist in training matrices.
- `test_action_recommendations_generation`: Validates rule-based mitigation generation.
- `test_cached_shap_explainability`: Asserts high-performance SHAP attribution calculations.
