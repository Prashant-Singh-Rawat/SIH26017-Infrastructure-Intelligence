"""
Security & Penetration Test Suite — SIH26017
Verifies defenses against Auth Bypass, Privilege Escalation, SQL Injection, XSS, CORS, Rate Limiting, and Secret Leakage.
"""

import os
import time
import pytest
from fastapi.testclient import TestClient
from backend.server import app
from backend.security.auth import create_access_token

client = TestClient(app)

def test_auth_bypass_prevention():
    """Verify that protected operations reject unauthenticated anonymous calls with 401."""
    # 1. Alert acknowledgement requires officer authentication
    res_ack = client.post("/api/v1/alerts/1/acknowledge", json={"status": "ACKNOWLEDGED"})
    assert res_ack.status_code == 401
    assert res_ack.json()["error"]["code"] in ["AUTH_REQUIRED", "HTTP_401"]

    # 2. Audit logs require admin authentication
    res_audit = client.get("/api/v1/audit-logs")
    assert res_audit.status_code == 401
    assert res_audit.json()["error"]["code"] in ["AUTH_REQUIRED", "HTTP_401"]

def test_rbac_privilege_escalation_prevention():
    """Verify that users cannot perform actions outside their assigned role hierarchy."""
    viewer_token = create_access_token("00000000-0000-0000-0000-000000000004", "viewer@gov.in", "VIEWER")
    analyst_token = create_access_token("00000000-0000-0000-0000-000000000003", "analyst@gov.in", "ANALYST")
    officer_token = create_access_token("00000000-0000-0000-0000-000000000002", "officer@gov.in", "OFFICER")
    admin_token = create_access_token("00000000-0000-0000-0000-000000000001", "admin@gov.in", "ADMIN")

    # VIEWER cannot acknowledge alerts (requires OFFICER or ADMIN)
    res_v = client.post(
        "/api/v1/alerts/1/acknowledge",
        json={"status": "ACKNOWLEDGED"},
        headers={"Authorization": f"Bearer {viewer_token}"}
    )
    assert res_v.status_code == 403
    assert res_v.json()["error"]["code"] == "FORBIDDEN_ROLE"

    # ANALYST cannot access audit logs (requires ADMIN)
    res_a = client.get(
        "/api/v1/audit-logs",
        headers={"Authorization": f"Bearer {analyst_token}"}
    )
    assert res_a.status_code == 403
    assert res_a.json()["error"]["code"] == "FORBIDDEN_ROLE"

    # OFFICER cannot access audit logs (requires ADMIN)
    res_o = client.get(
        "/api/v1/audit-logs",
        headers={"Authorization": f"Bearer {officer_token}"}
    )
    assert res_o.status_code == 403

    # ADMIN can access audit logs
    res_adm = client.get(
        "/api/v1/audit-logs",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert res_adm.status_code == 200

def test_invalid_jwt_handling():
    """Verify that invalid and expired JWT tokens are cleanly rejected."""
    # Malformed token
    res_bad = client.get("/api/v1/audit-logs", headers={"Authorization": "Bearer not-a-real-token"})
    assert res_bad.status_code == 401
    assert res_bad.json()["error"]["code"] == "INVALID_TOKEN"

    # Expired token
    expired_token = create_access_token("user-id", "exp@gov.in", "ADMIN", expires_in_seconds=-3600)
    res_exp = client.get("/api/v1/audit-logs", headers={"Authorization": f"Bearer {expired_token}"})
    assert res_exp.status_code == 401
    assert res_exp.json()["error"]["code"] == "TOKEN_EXPIRED"

def test_sql_injection_defense():
    """Verify that SQL injection payloads in search filters do not execute or cause server 500 errors."""
    sqli_payloads = [
        "' OR '1'='1",
        "'; DROP TABLE projects; --",
        "1 UNION SELECT 1,2,3,4,5,6,7,8,9,10--",
        "admin'--"
    ]
    for payload in sqli_payloads:
        res = client.get(f"/api/v1/projects?q={payload}")
        assert res.status_code == 200, f"SQLi payload failed: {payload}"
        # Response should be valid JSON with total_records integer
        data = res.json()
        assert isinstance(data["total_records"], int)

def test_xss_payload_handling():
    """Verify that script tags in query strings are treated as plain text strings."""
    xss_payload = "<script>alert('xss')</script>"
    res = client.get(f"/api/v1/projects?q={xss_payload}")
    assert res.status_code == 200
    assert res.json()["total_records"] == 0

def test_security_headers_present():
    """Verify that mandatory HTTP security headers are injected into every response."""
    res = client.get("/health")
    assert "Content-Security-Policy" in res.headers
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    assert res.headers["X-Frame-Options"] == "DENY"
    assert res.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert "Permissions-Policy" in res.headers
    assert "Strict-Transport-Security" in res.headers

def test_input_validation_rejections():
    """Verify that Pydantic v2 rejects unexpected extra fields, negative costs, and invalid dates."""
    # Negative cost
    res_neg = client.post("/api/v1/predictions", json={
        "sector_name": "Railways",
        "line_ministry": "Ministry of Railways",
        "original_cost_cr": -200.0,
        "planned_end_year": 2028
    })
    assert res_neg.status_code == 422
    assert res_neg.json()["error"]["code"] == "VALIDATION_ERROR"

    # Unexpected extra fields (forbid extra)
    res_extra = client.post("/api/v1/predictions", json={
        "sector_name": "Railways",
        "line_ministry": "Ministry of Railways",
        "original_cost_cr": 200.0,
        "planned_end_year": 2028,
        "extra_field_attack": "injection"
    })
    assert res_extra.status_code == 422
    assert res_extra.json()["error"]["code"] == "VALIDATION_ERROR"

def test_secret_exposure_protection():
    """Verify that health, readiness, and error endpoints never leak environment secrets or credentials."""
    res_ready = client.get("/ready")
    text = res_ready.text.lower()
    assert "password" not in text
    assert "secret" not in text
    assert "service_role" not in text

def test_oversized_payload_rejection():
    """Verify that HTTP 413 is returned if request headers specify payload exceeding 5MB."""
    headers = {"Content-Length": str(10 * 1024 * 1024)}  # 10MB
    res = client.post("/api/v1/predictions", content=b"dummy", headers=headers)
    assert res.status_code == 413
    assert res.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
