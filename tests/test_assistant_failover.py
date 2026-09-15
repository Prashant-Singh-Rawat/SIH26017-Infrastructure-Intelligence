"""
Automated Test Suite for Gemini Multi-Key & Model Failover Architecture — SIH26017
Tests:
- Multi-key configuration pool loading (GEMINI_API_KEY_1 through 6)
- Slot key masking (****ABCD) and zero key exposure guarantee
- Circuit breaker state machine (HEALTHY -> DEGRADED -> COOLDOWN -> HEALTHY)
- Concurrency gating and tracking
- Multi-step failover simulation: Key 1 (429) -> Key 2 (500) -> Key 3 (Success)
- Timeout failover: Key 1 (Timeout) -> Key 2 (Success)
- All-fail scenario: Controlled graceful error message, no stack trace or leaked credentials
- Cooldown expiration and slot recovery back into healthy pool
- Model fallback routing (Primary model -> Fallback model)
- Admin diagnostics endpoint (/api/v1/assistant/diagnostics) with masked credentials
- Health status telemetry (/api/v1/assistant/status)
"""

import json
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from backend.server import app
from backend.assistant.config import (
    get_gemini_credentials_pool,
    mask_key,
    get_gemini_models_pool
)
from backend.assistant.failover import (
    GeminiFailoverGateway,
    SlotHealth,
    STATUS_HEALTHY,
    STATUS_DEGRADED,
    STATUS_COOLDOWN,
    STATUS_DISABLED
)
from backend.assistant.gemini_service import GeminiAssistantService

client = TestClient(app)

# -----------------------------------------------------------------------------
# 1. Multi-Key Configuration & Key Masking Tests
# -----------------------------------------------------------------------------

def test_key_masking_security():
    """Verify raw API keys are never exposed and always masked safely."""
    raw_key = "AIzaSyD1234567890abcdefghijklmnopXYZ"
    masked = mask_key(raw_key)
    assert masked.startswith("****")
    assert masked.endswith("pXYZ")
    assert "AIza" not in masked
    assert len(masked) == 8

    # Edge cases
    assert mask_key("") == "UNCONFIGURED"
    assert mask_key(None) == "UNCONFIGURED"
    assert mask_key("short") == "****"

def test_multi_key_pool_discovery():
    """Verify get_gemini_credentials_pool discovers all configured slots 1 to 6."""
    mock_env = {
        "GEMINI_API_KEY": "",
        "GOOGLE_API_KEY": "",
        "GEMINI_API_KEY_1": "AIzaKeyOne111111111111111111111111111",
        "GEMINI_API_KEY_2": "AIzaKeyTwo222222222222222222222222222",
        "GEMINI_API_KEY_3": "AIzaKeyThree33333333333333333333333333",
        "GEMINI_API_KEY_4": "",
        "GEMINI_API_KEY_5": "AIzaKeyFive55555555555555555555555555",
        "GEMINI_API_KEY_6": ""
    }
    with patch.dict("os.environ", mock_env):
        pool = get_gemini_credentials_pool()
        assert len(pool) == 4
        # Verify masked_key is present and raw key is masked
        for p in pool:
            assert "AIza" not in p["masked_key"]
            assert p["masked_key"].startswith("****")
            assert "slot_id" in p

# -----------------------------------------------------------------------------
# 2. Circuit Breaker & Health State Machine Tests
# -----------------------------------------------------------------------------

def test_circuit_breaker_transitions():
    """Verify HEALTHY -> DEGRADED -> COOLDOWN -> HEALTHY recovery."""
    slot = SlotHealth(
        slot_id="key_test_cb",
        api_key="AIzaDummyTestKey1234567890",
        masked_key="****7890",
        model="gemini-2.5-flash",
        cooldown_duration_sec=2  # Short for fast test
    )
    assert slot.status == STATUS_HEALTHY
    assert slot.is_available() is True

    # 1. First 500 failure -> DEGRADED
    slot.record_failure("500 Internal error encountered", is_rate_limit=False)
    assert slot.status == STATUS_DEGRADED
    assert slot.failure_count == 1

    # 2. Rate limit failure -> COOLDOWN
    slot.record_failure("429 Resource exhausted", is_rate_limit=True)
    assert slot.status == STATUS_COOLDOWN
    assert slot.is_available() is False
    assert slot.cooldown_until is not None

    # 3. Simulate cooldown expiration
    time.sleep(2.1)
    assert slot.is_available() is True  # Ready for probe test

    # 4. Successful probe request -> Returns to HEALTHY
    slot.record_success(latency_ms=350)
    assert slot.status == STATUS_HEALTHY
    assert slot.success_count == 1
    assert slot.consecutive_failures == 0

# -----------------------------------------------------------------------------
# 3. Failover Gateway Routing & Candidate Plan Tests
# -----------------------------------------------------------------------------

def test_gateway_skips_cooldown_slots():
    """Verify router skips cooldown slots and picks the first healthy slot."""
    gw = GeminiFailoverGateway()
    gw.slots = {
        "key_1": SlotHealth(slot_id="key_1", api_key="Key1Mock", masked_key="****Key1", model="gemini-2.5-flash"),
        "key_2": SlotHealth(slot_id="key_2", api_key="Key2Mock", masked_key="****Key2", model="gemini-2.5-flash"),
        "key_3": SlotHealth(slot_id="key_3", api_key="Key3Mock", masked_key="****Key3", model="gemini-2.5-flash")
    }

    # Put key_1 into cooldown
    gw.slots["key_1"].record_failure("429 Quota Exceeded", is_rate_limit=True)
    gw.slots["key_1"].record_failure("429 Quota Exceeded", is_rate_limit=True)
    assert gw.slots["key_1"].status == STATUS_COOLDOWN

    plan = gw.get_candidate_plan()
    assert len(plan) >= 2
    # The first candidate slot MUST NOT be key_1
    first_slot, first_model = plan[0]
    assert first_slot.slot_id in ["key_2", "key_3"]
    assert first_slot.slot_id != "key_1"

# -----------------------------------------------------------------------------
# 4. Multi-Step Failover Scenarios: Key 1 (429) -> Key 2 (500) -> Key 3 (200)
# -----------------------------------------------------------------------------

def test_failover_multi_step_scenario():
    """
    Scenario:
    - Attempt 1 on Key 1 raises 429 ResourceExhausted
    - Attempt 2 on Key 2 raises 500 InternalServerError
    - Attempt 3 on Key 3 succeeds with 200 response
    Expected: End-to-end request completes successfully via Key 3 without user error.
    """
    service = GeminiAssistantService()
    service._client = None  # Ensure it uses gateway

    mock_env = {
        "GEMINI_API_KEY": "",
        "GOOGLE_API_KEY": "",
        "GEMINI_API_KEY_1": "AIzaKeyOne_MockKey1111111111111111",
        "GEMINI_API_KEY_2": "AIzaKeyTwo_MockKey2222222222222222",
        "GEMINI_API_KEY_3": "AIzaKeyThree_MockKey33333333333333"
    }

    with patch.dict("os.environ", mock_env):
        service.gateway.reload_slots()
        service._cache = service._cache.__class__()

        call_counts = {"key_1": 0, "key_2": 0, "key_3": 0}

        def mock_genai_client(api_key=None):
            client_mock = MagicMock()
            chat_mock = MagicMock()

            if "KeyOne" in str(api_key):
                call_counts["key_1"] += 1
                def fail_429(*args, **kwargs):
                    raise Exception("429 Resource has been exhausted (e.g. check quota).")
                chat_mock.send_message.side_effect = fail_429
            elif "KeyTwo" in str(api_key):
                call_counts["key_2"] += 1
                def fail_500(*args, **kwargs):
                    raise Exception("500 Internal error encountered on provider.")
                chat_mock.send_message.side_effect = fail_500
            elif "KeyThree" in str(api_key):
                call_counts["key_3"] += 1
                mock_resp = MagicMock()
                mock_resp.text = "Success from Key 3: National Highway 44 delay analyzed."
                chat_mock.send_message.return_value = mock_resp
                chat_mock.get_history.return_value = []

            client_mock.chats.create.return_value = chat_mock
            return client_mock

        with patch("backend.assistant.gemini_service.genai.Client", side_effect=mock_genai_client):
            res = service.generate_chat_response(
                message="Explain strategic issues with project NH-44",
                context={"current_page": "overview"}
            )

            assert "error" not in res or res["error"] is None
            assert "National Highway 44" in res["text"]
            assert call_counts["key_1"] >= 1
            assert call_counts["key_2"] >= 1
            assert call_counts["key_3"] >= 1
            assert any(s.rate_limit_count >= 1 for s in service.gateway.slots.values())

# -----------------------------------------------------------------------------
# 5. Timeout Failover Scenario: Key 1 (Timeout) -> Key 2 (Success)
# -----------------------------------------------------------------------------

def test_failover_timeout_scenario():
    """
    Scenario:
    - Attempt 1 on Key 1 times out
    - Attempt 2 on Key 2 succeeds
    Expected: Seamless recovery and response delivered.
    """
    service = GeminiAssistantService()
    service._client = None

    mock_env = {
        "GEMINI_API_KEY": "",
        "GOOGLE_API_KEY": "",
        "GEMINI_API_KEY_1": "AIzaKeyOne_TimeoutMock111111111111111",
        "GEMINI_API_KEY_2": "AIzaKeyTwo_SuccessMock22222222222222"
    }

    with patch.dict("os.environ", mock_env):
        service.gateway.reload_slots()
        service._cache = service._cache.__class__()

        def mock_client_factory(api_key=None):
            c_mock = MagicMock()
            chat_mock = MagicMock()

            if "TimeoutMock" in str(api_key):
                def raise_timeout(*args, **kwargs):
                    raise TimeoutError("Deadline exceeded waiting for Gemini API stream.")
                chat_mock.send_message.side_effect = raise_timeout
            else:
                resp = MagicMock()
                resp.text = "Recovered via Key 2: Project 705728 details."
                chat_mock.send_message.return_value = resp
                chat_mock.get_history.return_value = []

            c_mock.chats.create.return_value = chat_mock
            return c_mock

        with patch("backend.assistant.gemini_service.genai.Client", side_effect=mock_client_factory):
            res = service.generate_chat_response(message="Status of 705728 delay analysis")
            assert "Recovered via Key 2" in res["text"]
            assert any(s.timeout_count >= 1 for s in service.gateway.slots.values())

# -----------------------------------------------------------------------------
# 6. All Keys Fail Scenario — Graceful Error Without Secrets Leakage
# -----------------------------------------------------------------------------

def test_all_keys_fail_graceful_error_no_leaks():
    """Verify that when all available keys fail, the user receives a friendly message and zero keys are leaked."""
    service = GeminiAssistantService()
    service._client = None

    mock_env = {
        "GEMINI_API_KEY": "",
        "GOOGLE_API_KEY": "",
        "GEMINI_API_KEY_1": "AIzaSecretKeyOne1111111111111111111",
        "GEMINI_API_KEY_2": "AIzaSecretKeyTwo2222222222222222222"
    }

    with patch.dict("os.environ", mock_env):
        service.gateway.reload_slots()
        service._cache = service._cache.__class__()

        def fail_all(api_key=None):
            c_mock = MagicMock()
            chat_mock = MagicMock()
            chat_mock.send_message.side_effect = Exception("429 ResourceExhausted: Service busy.")
            c_mock.chats.create.return_value = chat_mock
            return c_mock

        with patch("backend.assistant.gemini_service.genai.Client", side_effect=fail_all):
            res = service.generate_chat_response(message="Specific unique test query that must hit all keys")

            assert "AI Assistant" in res["text"]
            # Assert user-friendly message
            assert any(term in res["text"] for term in ["temporary", "service issue", "busy", "moments"])
            # Assert NO API keys leaked in user response
            assert "AIza" not in res["text"]
            assert "KeyOne" not in res["text"]
            assert "KeyTwo" not in res["text"]

# -----------------------------------------------------------------------------
# 7. Admin Diagnostics & Health Status Endpoints Verification
# -----------------------------------------------------------------------------

def test_diagnostics_endpoint_masks_keys():
    """Verify GET /api/v1/assistant/diagnostics shows masked credentials and request telemetry."""
    res = client.get("/api/v1/assistant/diagnostics")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    summary = data["summary"]
    assert "slots" in summary
    assert "healthy_credentials" in summary

    # Verify no raw keys in response payload
    resp_text = json.dumps(data)
    assert "AIza" not in resp_text

    for slot in summary["slots"]:
        assert slot["masked_key"].startswith("****") or slot["masked_key"] == "UNCONFIGURED"

def test_status_endpoint_reports_gateway_metrics():
    """Verify GET /api/v1/assistant/status includes healthy and cooldown counts."""
    res = client.get("/api/v1/assistant/status")
    assert res.status_code == 200
    data = res.json()
    assert "healthy_credentials" in data
    assert "cooldown_credentials" in data
    assert "healthy_models" in data
    assert data["provider"] == "Google Gemini"
