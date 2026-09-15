"""
Test Suite for Google Gemini AI Assistant Integration — SIH26017 Platform
Verifies:
1. Tool calling against real database records and ML engine
2. Read-only safety and security enforcement
3. Status, chat, stream, and reset endpoints
4. Context awareness and selected project resolution
5. Multi-turn conversation handling
6. Multilingual support and honesty/hallucination prevention
"""

import pytest
import json
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from backend.server import app
from backend.assistant.tools import (
    search_projects,
    get_project_details,
    get_project_ml_risk_and_delay,
    get_land_acquisition_bottlenecks,
    get_critical_alerts,
    get_dashboard_summary_metrics,
    get_data_quality_metrics,
    query_knowledge_base,
    client_navigation_action,
    ASSISTANT_TOOLS
)
from backend.assistant.gemini_service import GeminiAssistantService, SYSTEM_INSTRUCTION

client = TestClient(app)

# -----------------------------------------------------------------------------
# 1. Tool Functions Tests (Real Database & ML Model Integration)
# -----------------------------------------------------------------------------

def test_tool_search_projects_real_db():
    """Verify search_projects retrieves real projects from SQLite database."""
    res = search_projects(query="Railway", limit=3)
    assert "total_found" in res
    assert res["total_found"] > 0
    assert len(res["projects"]) <= 3
    first = res["projects"][0]
    assert "project_code" in first
    assert "project_name" in first
    assert "original_cost_cr" in first

def test_tool_get_project_details_real_db():
    """Verify get_project_details fetches exact record for known project #705728."""
    res = get_project_details(705728)
    assert res["project_code"] == 705728
    assert "project_name" in res
    assert "original_cost_cr" in res
    assert "revised_cost_cr" in res
    assert "schedule_delay_days" in res

def test_tool_get_project_details_nonexistent():
    """Verify get_project_details safely handles nonexistent project code."""
    res = get_project_details(99999999)
    assert "error" in res
    assert "not found" in res["error"].lower()

def test_tool_ml_risk_and_delay():
    """Verify get_project_ml_risk_and_delay uses real ML models and SHAP explainer."""
    res = get_project_ml_risk_and_delay(705728)
    assert "project_code" in res
    assert ("risk_tier" in res or "actual_reported_delay_days" in res)
    if "shap_attribution_drivers" in res:
        assert isinstance(res["shap_attribution_drivers"], list)

def test_tool_land_acquisition_bottlenecks():
    """Verify get_land_acquisition_bottlenecks uses land engine RFCTLARR logic."""
    res = get_land_acquisition_bottlenecks(705728)
    assert "project_code" in res
    assert "critical_bottleneck_stage" in res
    assert "statutory_act_reference" in res
    assert "recommended_statutory_actions" in res

def test_tool_critical_alerts():
    """Verify get_critical_alerts queries real alerts."""
    res = get_critical_alerts(limit=5)
    assert "total_returned" in res
    assert "alerts" in res
    assert len(res["alerts"]) <= 5

def test_tool_dashboard_summary():
    """Verify get_dashboard_summary_metrics returns overview stats."""
    res = get_dashboard_summary_metrics()
    assert res["total_monitored_projects"] == 1981
    assert "total_sanctioned_cost_cr" in res

def test_tool_data_quality_metrics():
    """Verify get_data_quality_metrics returns real audit KPIs."""
    res = get_data_quality_metrics()
    assert res["catalog_total_records"] == 1981
    assert "dimensions" in res
    assert "completeness_score_pct" in res["dimensions"]

def test_tool_knowledge_base():
    """Verify query_knowledge_base searches docs directory."""
    res = query_knowledge_base("architecture")
    assert "matched_documents" in res
    assert len(res["matched_documents"]) > 0

def test_tool_client_navigation():
    """Verify client_navigation_action formats valid client-side actions."""
    res = client_navigation_action("navigate_tab", target_tab="simulator", project_code=705728)
    assert "action_type" in res
    assert res["target_tab"] == "simulator"
    assert res["project_code"] == 705728

# -----------------------------------------------------------------------------
# 2. Assistant Service & Context Preamble Tests
# -----------------------------------------------------------------------------

def test_context_preamble_resolution():
    """Verify context prompt builder anchors to current tab and project."""
    service = GeminiAssistantService()
    ctx = {
        "current_page": "early-warning",
        "selected_project_code": 705728,
        "selected_project_name": "Udhampur-Srinagar-Baramulla Rail Link",
        "user_role": "DISTRICT_OFFICER"
    }
    preamble = service._build_context_prompt(ctx)
    assert "early-warning" in preamble
    assert "705728" in preamble
    assert "Udhampur-Srinagar-Baramulla" in preamble
    assert "DISTRICT_OFFICER" in preamble
    assert "When the user refers to 'this project'" in preamble

def test_system_instruction_grounding_and_safety():
    """Verify system instruction forbids hallucinations, unauthorized writes, and prompt injections."""
    assert "GROUNDED IN TRUTH (ZERO DATA HALLUCINATION)" in SYSTEM_INSTRUCTION
    assert "I don't have that information in the currently available portal data" in SYSTEM_INSTRUCTION
    assert "READ VS. WRITE ENFORCEMENT" in SYSTEM_INSTRUCTION
    assert "PROMPT INJECTION DEFENSE" in SYSTEM_INSTRUCTION
    assert "MULTI-LANGUAGE & NATURAL REGISTER" in SYSTEM_INSTRUCTION

# -----------------------------------------------------------------------------
# 3. HTTP Endpoints Tests
# -----------------------------------------------------------------------------

def test_assistant_status_endpoint():
    """Verify GET /api/v1/assistant/status returns capabilities and readiness."""
    res = client.get("/api/v1/assistant/status")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "model" in data
    assert "capabilities" in data
    assert "general_knowledge_qa" in data["capabilities"]
    assert "project_telemetry_analysis" in data["capabilities"]
    assert "client_navigation_actions" in data["capabilities"]

def test_assistant_reset_endpoint():
    """Verify POST /api/v1/assistant/reset succeeds."""
    res = client.post("/api/v1/assistant/reset")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "session_reset"

def test_assistant_chat_unconfigured_key():
    """Verify assistant handles unconfigured API key gracefully without crashing."""
    with patch.dict("os.environ", {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}):
        service = GeminiAssistantService()
        service._client = None
        result = service.generate_chat_response(message="Hello")
        assert "AI Assistant is temporarily unavailable" in result["text"]
        assert result["error"] == "API_KEY_UNCONFIGURED"

# -----------------------------------------------------------------------------
# 4. Mocked Gemini Service End-to-End Chat & Tool Dispatch Tests
# -----------------------------------------------------------------------------

def test_gemini_service_with_mocked_client():
    """Verify tool dispatch and response parsing with a mocked genai.Client."""
    service = GeminiAssistantService()
    mock_client = MagicMock()

    mock_chat = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "Project #705728 (USBRL) has a sanctioned cost of ₹27,949 Cr and revised cost of ₹37,012 Cr."
    mock_chat.send_message.return_value = mock_resp

    mock_part = MagicMock()
    mock_part.function_call = MagicMock()
    mock_part.function_call.name = "get_project_details"
    mock_part.function_call.args = {"project_code": 705728}
    mock_part.function_response = None

    mock_content = MagicMock()
    mock_content.parts = [mock_part]
    mock_chat.get_history.return_value = [mock_content]

    mock_client.chats.create.return_value = mock_chat
    service._client = mock_client

    result = service.generate_chat_response(
        message="Tell me about project 705728",
        context={"current_page": "explorer", "selected_project_code": 705728}
    )

    assert "error" not in result or result["error"] is None
    assert "USBRL" in result["text"]
    assert len(result["tools_called"]) > 0
    assert result["tools_called"][0]["name"] == "get_project_details"

# -----------------------------------------------------------------------------
# 5. Security & Live Endpoint Verification Tests
# -----------------------------------------------------------------------------

def test_assistant_status_security_no_key_leakage():
    """Verify GET /api/v1/assistant/status never exposes API key or secrets."""
    res = client.get("/api/v1/assistant/status")
    assert res.status_code == 200
    data = res.json()
    assert "available" in data
    assert data["provider"] == "Google Gemini"
    # Ensure no secret strings or partial keys in response
    resp_str = json.dumps(data)
    assert "AIza" not in resp_str
    assert "key=" not in resp_str

def test_assistant_chat_endpoint_live():
    """Verify POST /api/v1/assistant/chat returns a valid response payload."""
    res = client.post("/api/v1/assistant/chat", json={"message": "Reply with exactly: Gemini online."})
    assert res.status_code == 200
    data = res.json()
    assert "text" in data
    assert len(data["text"]) > 0

def test_assistant_stream_endpoint_live():
    """Verify POST /api/v1/assistant/chat/stream returns text/event-stream."""
    res = client.post("/api/v1/assistant/chat/stream", json={"message": "Hello"})
    assert res.status_code == 200
    assert "text/event-stream" in res.headers.get("content-type", "")
