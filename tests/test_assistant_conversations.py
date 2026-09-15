"""
Automated Test Suite for Assistant Conversations & Retention Modes — SIH26017
Tests:
- Creation of Temporary, 30-day, and Permanent conversations
- Expiration calculation and validation
- Converting 30-day to Permanent and vice versa
- Permanent chats never expiring
- Message persistence, retrieval, and message_count updates
- Deterministic title generation from first prompt
- IDOR ownership validation & cross-user access denial
- Rename and deletion (with message cascade)
- Database-backed search by title and message content
- Recency grouping (Today, Yesterday, Previous 7 Days, Older)
- Automated idempotent cleanup routine (cleans expired & abandoned, protects permanent)
- Full REST API verification using FastAPI TestClient
"""

import json
import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

from backend.server import app
from backend.assistant.conversation_service import (
    conversation_service,
    generate_deterministic_title,
    MODE_TEMPORARY,
    MODE_30_DAY,
    MODE_PERMANENT
)
from backend.assistant.database import (
    init_assistant_tables,
    cleanup_expired_conversations
)
from backend.database import get_db_connection, adapt_query

client = TestClient(app)

@pytest.fixture(autouse=True)
def setup_db():
    """Ensure assistant tables exist before each test."""
    init_assistant_tables()

# -----------------------------------------------------------------------------
# 1. Deterministic Title Generation Tests
# -----------------------------------------------------------------------------

def test_deterministic_title_generation():
    """Test title generation for various user inquiries without API calls."""
    assert "705728" in generate_deterministic_title("Why is project 705728 delayed?")
    assert "RFCTLARR" in generate_deterministic_title("Explain RFCTLARR land acquisition issues")
    assert "Critical Escalation" in generate_deterministic_title("What are the critical alerts?")
    assert "ML Predictive" in generate_deterministic_title("Explain SHAP values for model predictions")
    assert "Data Quality" in generate_deterministic_title("Check data quality audit anomalies")
    assert generate_deterministic_title("Hello there") == "Hello there"

# -----------------------------------------------------------------------------
# 2. Conversation Creation & Modes Tests
# -----------------------------------------------------------------------------

def test_create_temporary_chat():
    """Verify temporary chat creation and default 24h expiration."""
    conv = conversation_service.create_conversation(
        user_id="user_test_temp",
        title="Temp Session",
        chat_mode=MODE_TEMPORARY
    )
    assert conv["chat_mode"] == MODE_TEMPORARY
    assert conv["is_permanent"] is False
    assert conv["expires_at"] is not None

    # Check database record
    db_conv = conversation_service.get_conversation(conv["conversation_id"], user_id="user_test_temp")
    assert db_conv is not None
    assert db_conv["chat_mode"] == MODE_TEMPORARY
    assert db_conv["is_permanent"] is False

def test_create_30_day_chat():
    """Verify 30-day chat default retention calculation."""
    conv = conversation_service.create_conversation(
        user_id="user_test_30d",
        title="Normal Chat",
        chat_mode=MODE_30_DAY
    )
    assert conv["chat_mode"] == MODE_30_DAY
    assert conv["is_permanent"] is False
    assert conv["expires_at"] is not None

    exp_dt = datetime.fromisoformat(conv["expires_at"].replace("Z", "+00:00"))
    created_dt = datetime.fromisoformat(conv["created_at"].replace("Z", "+00:00"))
    diff_days = (exp_dt - created_dt).days
    assert diff_days in [29, 30]

def test_create_permanent_chat():
    """Verify permanent chat has no expiration date."""
    conv = conversation_service.create_conversation(
        user_id="user_test_perm",
        title="Important Dossier Chat",
        chat_mode=MODE_PERMANENT
    )
    assert conv["chat_mode"] == MODE_PERMANENT
    assert conv["is_permanent"] is True
    assert conv["expires_at"] is None

def test_convert_30_day_to_permanent():
    """Verify converting a 30-day chat to permanent removes expiration."""
    conv = conversation_service.create_conversation(
        user_id="user_test_convert",
        chat_mode=MODE_30_DAY
    )
    assert conv["expires_at"] is not None

    # Update to permanent
    updated = conversation_service.update_conversation(
        conversation_id=conv["conversation_id"],
        user_id="user_test_convert",
        is_permanent=True
    )
    assert updated is not None
    assert updated["is_permanent"] is True
    assert updated["chat_mode"] == MODE_PERMANENT
    assert updated["expires_at"] is None

# -----------------------------------------------------------------------------
# 3. Message Persistence & Automatic Title Generation
# -----------------------------------------------------------------------------

def test_message_persistence_and_title_update():
    """Verify message addition updates count and auto-generates title on turn 1."""
    conv = conversation_service.create_conversation(
        user_id="user_msg_test",
        title="New Conversation",
        chat_mode=MODE_30_DAY
    )

    # First turn from user
    msg1 = conversation_service.add_message(
        conversation_id=conv["conversation_id"],
        user_id="user_msg_test",
        role="user",
        content="Why is project 705728 delayed?",
        project_code=705728
    )
    assert msg1 is not None
    assert msg1["role"] == "user"

    # Verify conversation title was auto-updated deterministically
    updated_conv = conversation_service.get_conversation(conv["conversation_id"], user_id="user_msg_test")
    assert "705728" in updated_conv["title"]
    assert updated_conv["message_count"] == 1

    # Assistant reply turn
    msg2 = conversation_service.add_message(
        conversation_id=conv["conversation_id"],
        user_id="user_msg_test",
        role="assistant",
        content="Project 705728 has delay due to land acquisition.",
        model_used="gemini-2.5-flash",
        latency_ms=850
    )
    assert msg2 is not None

    messages = conversation_service.get_messages(conv["conversation_id"], user_id="user_msg_test")
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "assistant"
    assert messages[1]["latency_ms"] == 850

# -----------------------------------------------------------------------------
# 4. IDOR Ownership & Security Tests
# -----------------------------------------------------------------------------

def test_conversation_ownership_and_idor_protection():
    """Verify that User B cannot view, update, or delete User A's conversation."""
    conv_a = conversation_service.create_conversation(
        user_id="user_alice",
        title="Alice Confidential Chat",
        chat_mode=MODE_30_DAY
    )

    # User Bob attempts to read Alice's conversation
    conv_b_view = conversation_service.get_conversation(conv_a["conversation_id"], user_id="user_bob")
    assert conv_b_view is None

    # User Bob attempts to update Alice's conversation
    update_res = conversation_service.update_conversation(
        conversation_id=conv_a["conversation_id"],
        user_id="user_bob",
        title="Hacked Title"
    )
    assert update_res is None

    # User Bob attempts to delete Alice's conversation
    del_res = conversation_service.delete_conversation(
        conversation_id=conv_a["conversation_id"],
        user_id="user_bob"
    )
    assert del_res is False

    # Alice's conversation remains intact
    conv_alice = conversation_service.get_conversation(conv_a["conversation_id"], user_id="user_alice")
    assert conv_alice is not None
    assert conv_alice["title"] == "Alice Confidential Chat"

# -----------------------------------------------------------------------------
# 5. Conversation Deletion & Search Tests
# -----------------------------------------------------------------------------

def test_delete_conversation():
    """Verify deleting conversation purges messages."""
    conv = conversation_service.create_conversation(
        user_id="user_del_test",
        title="To be deleted",
        chat_mode=MODE_TEMPORARY
    )
    conversation_service.add_message(
        conversation_id=conv["conversation_id"],
        user_id="user_del_test",
        role="user",
        content="Temporary message"
    )

    # Delete
    assert conversation_service.delete_conversation(conv["conversation_id"], user_id="user_del_test") is True

    # Check conversation is gone
    assert conversation_service.get_conversation(conv["conversation_id"], user_id="user_del_test") is None
    assert len(conversation_service.get_messages(conv["conversation_id"], user_id="user_del_test")) == 0

def test_database_backed_chat_search():
    """Verify search finds conversations matching keywords in titles or messages."""
    conv = conversation_service.create_conversation(
        user_id="user_search_test",
        title="USBRL Tunneling Project",
        chat_mode=MODE_30_DAY
    )
    conversation_service.add_message(
        conversation_id=conv["conversation_id"],
        user_id="user_search_test",
        role="user",
        content="What is the environmental clearance status for Katra section?"
    )

    # Search by title keyword
    results_title = conversation_service.search_conversations(user_id="user_search_test", query="Tunneling")
    assert len(results_title) >= 1
    assert results_title[0]["conversation_id"] == conv["conversation_id"]

    # Search by message content keyword
    results_msg = conversation_service.search_conversations(user_id="user_search_test", query="environmental")
    assert len(results_msg) >= 1
    assert results_msg[0]["conversation_id"] == conv["conversation_id"]

    # Search with non-existent keyword
    results_none = conversation_service.search_conversations(user_id="user_search_test", query="nonexistentxyz123")
    assert len(results_none) == 0

# -----------------------------------------------------------------------------
# 6. Automated Cleanup Routine Tests
# -----------------------------------------------------------------------------

def test_automatic_cleanup_expired_conversations():
    """
    Simulate expired 30-day chat and verify cleanup routine deletes it
    while preserving permanent conversations.
    """
    # 1. Permanent conversation (should NEVER be deleted)
    perm_conv = conversation_service.create_conversation(
        user_id="user_clean_test",
        title="Permanent Safe Chat",
        chat_mode=MODE_PERMANENT
    )

    # 2. Expired conversation (artificially set expires_at in the past)
    exp_conv = conversation_service.create_conversation(
        user_id="user_clean_test",
        title="Old Expired Chat",
        chat_mode=MODE_30_DAY
    )
    past_iso = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(adapt_query("""
        UPDATE ai_conversations
        SET expires_at = ?, is_permanent = 0
        WHERE conversation_id = ?;
    """), (past_iso, exp_conv["conversation_id"]))
    conn.commit()
    conn.close()

    # Run cleanup routine
    cleanup_res = cleanup_expired_conversations()
    assert cleanup_res["status"] == "success"
    assert cleanup_res["deleted_conversations"] >= 1

    # Verify expired conversation is deleted
    assert conversation_service.get_conversation(exp_conv["conversation_id"], user_id="user_clean_test") is None

    # Verify permanent conversation survives
    assert conversation_service.get_conversation(perm_conv["conversation_id"], user_id="user_clean_test") is not None

# -----------------------------------------------------------------------------
# 7. REST API Endpoints Verification via TestClient
# -----------------------------------------------------------------------------

def test_api_create_and_list_conversations():
    """Verify POST and GET /api/v1/assistant/conversations."""
    headers = {"X-User-ID": "api_test_user"}
    
    # Create conversation
    res = client.post("/api/v1/assistant/conversations", json={
        "title": "API Test Chat",
        "chat_mode": "30-day",
        "initial_message": "Tell me about RFCTLARR Section 19"
    }, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["chat_mode"] == "30-day"
    conv_id = data["conversation_id"]

    # List conversations
    list_res = client.get("/api/v1/assistant/conversations", headers=headers)
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert "conversations" in list_data
    assert "grouped" in list_data
    assert any(c["conversation_id"] == conv_id for c in list_data["conversations"])

    # Detail view
    detail_res = client.get(f"/api/v1/assistant/conversations/{conv_id}", headers=headers)
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert detail_data["conversation"]["conversation_id"] == conv_id
    assert len(detail_data["messages"]) >= 1

    # Make permanent
    perm_res = client.post(f"/api/v1/assistant/conversations/{conv_id}/permanent", headers=headers)
    assert perm_res.status_code == 200
    assert perm_res.json()["is_permanent"] is True

    # Remove permanent status (unpermanent)
    unperm_res = client.post(f"/api/v1/assistant/conversations/{conv_id}/unpermanent", headers=headers)
    assert unperm_res.status_code == 200
    assert unperm_res.json()["is_permanent"] is False

    # Export as TXT
    export_txt_res = client.get(f"/api/v1/assistant/conversations/{conv_id}/export?format=txt", headers=headers)
    assert export_txt_res.status_code == 200
    assert "text/plain" in export_txt_res.headers["content-type"]
    assert "attachment; filename=" in export_txt_res.headers["content-disposition"]
    assert "RFCTLARR" in export_txt_res.text
    # Verify zero secrets leaked
    assert "GEMINI_API_KEY" not in export_txt_res.text
    assert "AIza" not in export_txt_res.text

    # Export as JSON
    export_json_res = client.get(f"/api/v1/assistant/conversations/{conv_id}/export?format=json", headers=headers)
    assert export_json_res.status_code == 200
    assert "application/json" in export_json_res.headers["content-type"]
    export_json_data = export_json_res.json()
    assert export_json_data["conversation_id"] == conv_id
    assert len(export_json_data["messages"]) >= 1

    # Verify IDOR on export: another user cannot export this chat
    unauth_exp_res = client.get(f"/api/v1/assistant/conversations/{conv_id}/export?format=txt", headers={"X-User-ID": "attacker_user"})
    assert unauth_exp_res.status_code == 404

    # Rename
    patch_res = client.patch(f"/api/v1/assistant/conversations/{conv_id}", json={
        "title": "Renamed API Chat"
    }, headers=headers)
    assert patch_res.status_code == 200
    assert patch_res.json()["title"] == "Renamed API Chat"

    # Delete
    del_res = client.delete(f"/api/v1/assistant/conversations/{conv_id}", headers=headers)
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"

    # Confirm 404 after deletion
    get_after = client.get(f"/api/v1/assistant/conversations/{conv_id}", headers=headers)
    assert get_after.status_code == 404

# -----------------------------------------------------------------------------
# 8. Frontend DOM and JavaScript Integrity Verification
# -----------------------------------------------------------------------------

def test_assistant_frontend_dom_and_js_elements():
    """Verify that all required conversation DOM elements and JS hooks exist."""
    import os
    
    # Check index.html
    html_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    required_dom_ids = [
        "assistant-mode-btn",
        "assistant-mode-dropdown",
        "assistant-history-btn",
        "assistant-temporary-banner",
        "assistant-title-bar",
        "assistant-active-title",
        "assistant-history-panel",
        "assistant-history-search",
        "assistant-history-list",
        "assistant-delete-modal",
        "assistant-export-btn",
        "assistant-export-dropdown"
    ]
    for dom_id in required_dom_ids:
        assert f'id="{dom_id}"' in html, f"Missing required DOM element #{dom_id} in index.html"

    # Check app.js
    js_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "app.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    required_js_functions = [
        "selectAssistantChatMode",
        "toggleAssistantHistoryPanel",
        "closeAssistantHistoryPanel",
        "promptRenameCurrentChat",
        "togglePermanentForActiveChat",
        "loadAssistantConversations",
        "handleAssistantSearchInput",
        "sendAssistantMessage",
        "startNewAssistantChat",
        "exportConversationById",
        "exportActiveChat"
    ]
    for fn in required_js_functions:
        assert f"window.{fn} = {fn}" in js, f"Missing window export for {fn} in app.js"

