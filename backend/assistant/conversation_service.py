"""
Assistant Conversation Management Service — SIH26017 Platform
Manages persistent conversations, three chat modes (Temporary, 30-Day, Permanent),
ownership verification (IDOR protection), message history, deterministic title generation,
and context summarization for long conversational threads.
"""

import re
import json
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple

from backend.database import get_db_connection, adapt_query

logger = logging.getLogger("assistant.conversations")

MODE_TEMPORARY = "temporary"
MODE_30_DAY = "30-day"
MODE_PERMANENT = "permanent"

def generate_deterministic_title(user_prompt: str, project_code: Optional[int] = None) -> str:
    """
    Generates a clear, professional conversation title deterministically from the first user prompt
    without burning expensive Gemini API quota.
    """
    clean = user_prompt.strip()
    # Check for project code mentions
    found_code = project_code
    if not found_code:
        code_match = re.search(r'\b(?:project\s*(?:#|no\.?|code)?\s*)?(\d{5,7})\b', clean, re.IGNORECASE)
        if code_match:
            found_code = int(code_match.group(1))

    lower = clean.lower()

    if "rfctlarr" in lower or "land acquisition" in lower:
        return f"RFCTLARR Land Analysis (Project #{found_code})" if found_code else "RFCTLARR Land Acquisition Discussion"
    elif "delay" in lower and found_code:
        return f"Project #{found_code} Delay Diagnostics"
    elif "cost overrun" in lower or "budget" in lower:
        return f"Cost Overrun Review (Project #{found_code})" if found_code else "Cost Overrun & Budget Review"
    elif "critical alert" in lower or "escalation" in lower:
        return "Critical Escalation Alerts Overview"
    elif "machine learning" in lower or "shap" in lower or "model" in lower:
        return "ML Predictive Model & Explainability"
    elif "data quality" in lower or "audit" in lower:
        return "Data Quality & Anomaly Audit"
    elif found_code:
        return f"Project #{found_code} Analysis"
    elif len(clean) <= 45:
        # Capitalize words for title
        return clean.capitalize()
    else:
        words = clean.split()
        return " ".join(words[:6]).capitalize() + "..."

class ConversationService:
    """
    Handles lifecycle, RBAC ownership validation, persistence, and queries
    for all AI assistant conversations and messages.
    """

    @staticmethod
    def create_conversation(
        user_id: str,
        title: Optional[str] = None,
        chat_mode: str = MODE_30_DAY,
        project_code: Optional[int] = None,
        project_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """Creates a new conversation record with appropriate expiration based on mode."""
        conv_id = f"conv_{uuid.uuid4().hex[:16]}"
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        # Determine retention mode & expiration
        is_permanent = 1 if chat_mode == MODE_PERMANENT else 0
        expires_at_iso = None

        if chat_mode == MODE_30_DAY:
            expires_at_iso = (now + timedelta(days=30)).isoformat()
        elif chat_mode == MODE_TEMPORARY:
            # Temporary sessions expire after 24 hours if abandoned
            expires_at_iso = (now + timedelta(hours=24)).isoformat()

        final_title = (title or "New Conversation").strip()

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(adapt_query("""
                INSERT INTO ai_conversations (
                    conversation_id, user_id, title, chat_mode, created_at, updated_at,
                    expires_at, is_permanent, is_deleted, message_count,
                    last_project_code, last_project_name
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?);
            """), (
                conv_id, user_id, final_title, chat_mode, now_iso, now_iso,
                expires_at_iso, is_permanent, project_code, project_name
            ))
            conn.commit()
        finally:
            conn.close()

        return {
            "conversation_id": conv_id,
            "user_id": user_id,
            "title": final_title,
            "chat_mode": chat_mode,
            "created_at": now_iso,
            "updated_at": now_iso,
            "expires_at": expires_at_iso,
            "is_permanent": bool(is_permanent),
            "message_count": 0,
            "last_project_code": project_code,
            "last_project_name": project_name
        }

    @staticmethod
    def get_conversation(conversation_id: str, user_id: str, is_admin: bool = False) -> Optional[Dict[str, Any]]:
        """Retrieves conversation metadata with strict ownership check to prevent IDOR."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            query = adapt_query("SELECT * FROM ai_conversations WHERE conversation_id = ? AND is_deleted = 0;")
            cursor.execute(query, (conversation_id,))
            row = cursor.fetchone()
        finally:
            conn.close()

        if not row:
            return None

        conv = dict(row)
        # Verify ownership unless admin
        if conv["user_id"] != user_id and not is_admin:
            logger.warning(f"Access denied: user {user_id} tried to read conversation {conversation_id} owned by {conv['user_id']}")
            return None

        conv["is_permanent"] = bool(conv["is_permanent"])
        return conv

    @staticmethod
    def list_conversations(
        user_id: str,
        limit: int = 20,
        offset: int = 0,
        include_temporary: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Lists recent conversations for user with recency group categorization
        (Today, Yesterday, Previous 7 Days, Older).
        """
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            mode_filter = "" if include_temporary else "AND chat_mode != 'temporary'"
            query = adapt_query(f"""
                SELECT * FROM ai_conversations
                WHERE user_id = ? AND is_deleted = 0 {mode_filter}
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?;
            """)
            cursor.execute(query, (user_id, limit, offset))
            rows = cursor.fetchall()
        finally:
            conn.close()

        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_start = today_start - timedelta(days=1)
        seven_days_start = today_start - timedelta(days=7)

        result = []
        for r in rows:
            item = dict(r)
            item["is_permanent"] = bool(item["is_permanent"])

            # Categorize recency
            try:
                upd = datetime.fromisoformat(item["updated_at"].replace("Z", "+00:00"))
                if upd >= today_start:
                    item["time_group"] = "Today"
                elif upd >= yesterday_start:
                    item["time_group"] = "Yesterday"
                elif upd >= seven_days_start:
                    item["time_group"] = "Previous 7 Days"
                else:
                    item["time_group"] = "Older"
            except Exception:
                item["time_group"] = "Recent"

            result.append(item)

        return result

    @staticmethod
    def update_conversation(
        conversation_id: str,
        user_id: str,
        title: Optional[str] = None,
        chat_mode: Optional[str] = None,
        is_permanent: Optional[bool] = None,
        is_admin: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Updates title, mode, or retention status."""
        conv = ConversationService.get_conversation(conversation_id, user_id, is_admin=is_admin)
        if not conv:
            return None

        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        new_title = title.strip() if title is not None else conv["title"]
        new_mode = chat_mode if chat_mode is not None else conv["chat_mode"]
        
        # Handle permanent toggle
        if is_permanent is not None:
            new_is_perm = 1 if is_permanent else 0
            if new_is_perm == 1:
                new_mode = MODE_PERMANENT
                expires_at_iso = None
            else:
                new_mode = MODE_30_DAY
                expires_at_iso = (now + timedelta(days=30)).isoformat()
        elif chat_mode == MODE_PERMANENT:
            new_is_perm = 1
            expires_at_iso = None
        elif chat_mode == MODE_30_DAY:
            new_is_perm = 0
            expires_at_iso = (now + timedelta(days=30)).isoformat()
        else:
            new_is_perm = 1 if conv["is_permanent"] else 0
            expires_at_iso = conv["expires_at"]

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(adapt_query("""
                UPDATE ai_conversations
                SET title = ?, chat_mode = ?, is_permanent = ?, expires_at = ?, updated_at = ?
                WHERE conversation_id = ?;
            """), (new_title, new_mode, new_is_perm, expires_at_iso, now_iso, conversation_id))
            conn.commit()
        finally:
            conn.close()

        return ConversationService.get_conversation(conversation_id, user_id, is_admin=is_admin)

    @staticmethod
    def delete_conversation(conversation_id: str, user_id: str, is_admin: bool = False) -> bool:
        """Permanently purges conversation and associated messages from the database."""
        conv = ConversationService.get_conversation(conversation_id, user_id, is_admin=is_admin)
        if not conv:
            return False

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            # Delete messages and conversation
            cursor.execute(adapt_query("DELETE FROM ai_messages WHERE conversation_id = ?;"), (conversation_id,))
            cursor.execute(adapt_query("DELETE FROM ai_conversations WHERE conversation_id = ?;"), (conversation_id,))
            conn.commit()
        finally:
            conn.close()
        logger.info(f"Conversation {conversation_id} deleted by user {user_id}.")
        return True

    @staticmethod
    def add_message(
        conversation_id: str,
        user_id: str,
        role: str,
        content: str,
        model_used: Optional[str] = None,
        provider_slot: Optional[str] = None,
        tools_called: Optional[List[Any]] = None,
        client_actions: Optional[List[Any]] = None,
        project_code: Optional[int] = None,
        request_id: Optional[str] = None,
        context_json: Optional[str] = None,
        token_usage: Optional[str] = None,
        error_information: Optional[str] = None,
        latency_ms: int = 0,
        is_admin: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Appends a message to conversation, autogenerates title if first turn, and updates context."""
        conv = ConversationService.get_conversation(conversation_id, user_id, is_admin=is_admin)
        if not conv:
            return None

        msg_id = f"msg_{uuid.uuid4().hex[:16]}"
        now_iso = datetime.now(timezone.utc).isoformat()
        tools_json = json.dumps(tools_called) if tools_called else None
        actions_json = json.dumps(client_actions) if client_actions else None

        conn = get_db_connection()
        try:
            cursor = conn.cursor()

            cursor.execute(adapt_query("""
                INSERT INTO ai_messages (
                    message_id, conversation_id, role, content, created_at,
                    model_used, provider_slot, request_id, token_usage, context_json,
                    response_status, latency_ms, tools_called, client_actions,
                    error_information, project_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'success', ?, ?, ?, ?, ?);
            """), (
                msg_id, conversation_id, role, content, now_iso,
                model_used, provider_slot, request_id, token_usage, context_json,
                latency_ms, tools_json, actions_json, error_information, project_code
            ))

            # Check if conversation needs title generation
            current_count = conv.get("message_count", 0)
            new_count = current_count + 1
            new_title = conv["title"]

            if role == "user" and (not conv["title"] or conv["title"] == "New Conversation"):
                new_title = generate_deterministic_title(content, project_code=project_code)

            cursor.execute(adapt_query("""
                UPDATE ai_conversations
                SET message_count = ?, updated_at = ?, last_message_at = ?, title = ?,
                    last_project_code = COALESCE(?, last_project_code)
                WHERE conversation_id = ?;
            """), (new_count, now_iso, now_iso, new_title, project_code, conversation_id))

            conn.commit()
        finally:
            conn.close()

        return {
            "message_id": msg_id,
            "conversation_id": conversation_id,
            "role": role,
            "content": content,
            "created_at": now_iso,
            "model_used": model_used,
            "provider_slot": provider_slot,
            "request_id": request_id,
            "tools_called": tools_called or [],
            "client_actions": client_actions or [],
            "project_code": project_code,
            "latency_ms": latency_ms
        }

    @staticmethod
    def export_conversation(conversation_id: str, user_id: str, export_format: str = "txt", is_admin: bool = False) -> Optional[Dict[str, Any]]:
        """
        Exports conversation in text or JSON format for download.
        Strictly excludes internal system prompts, raw credentials, or keys.
        """
        conv = ConversationService.get_conversation(conversation_id, user_id, is_admin=is_admin)
        if not conv:
            return None

        messages = ConversationService.get_messages(conversation_id, user_id, limit=200, is_admin=is_admin)
        title = conv.get("title", "Conversation")
        created_at = conv.get("created_at", "")

        if export_format.lower() == "json":
            export_data = {
                "title": title,
                "conversation_id": conversation_id,
                "created_at": created_at,
                "chat_mode": conv.get("chat_mode"),
                "is_permanent": conv.get("is_permanent"),
                "messages": [
                    {
                        "role": m.get("role"),
                        "content": m.get("content"),
                        "created_at": m.get("created_at")
                    }
                    for m in messages
                ]
            }
            return {
                "filename": f"chat_export_{conversation_id}.json",
                "media_type": "application/json",
                "content": json.dumps(export_data, indent=2)
            }
        else:
            lines = [
                "MoSPI Infrastructure Intelligence AI Assistant — Chat Transcript",
                f"Title: {title}",
                f"Date: {created_at}",
                f"Retention Mode: {conv.get('chat_mode', '30-day').capitalize()}",
                "=" * 60,
                ""
            ]
            for m in messages:
                speaker = "User" if m.get("role") == "user" else "AI Assistant (Gemini)"
                time_str = m.get("created_at", "")[:19]
                lines.append(f"[{time_str}] {speaker}:")
                lines.append(m.get("content", ""))
                lines.append("-" * 40)
            return {
                "filename": f"chat_export_{conversation_id}.txt",
                "media_type": "text/plain; charset=utf-8",
                "content": "\n".join(lines)
            }

    @staticmethod
    def get_messages(
        conversation_id: str,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        is_admin: bool = False
    ) -> List[Dict[str, Any]]:
        """Returns message turns for a conversation ordered chronologically."""
        conv = ConversationService.get_conversation(conversation_id, user_id, is_admin=is_admin)
        if not conv:
            return []

        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(adapt_query("""
                SELECT * FROM ai_messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC
                LIMIT ? OFFSET ?;
            """), (conversation_id, limit, offset))
            rows = cursor.fetchall()
        finally:
            conn.close()

        messages = []
        for r in rows:
            m = dict(r)
            m["tools_called"] = json.loads(m["tools_called"]) if m.get("tools_called") else []
            m["client_actions"] = json.loads(m["client_actions"]) if m.get("client_actions") else []
            messages.append(m)
        return messages

    @staticmethod
    def get_context_for_llm(
        conversation_id: str,
        user_id: str,
        recent_turns: int = 8
    ) -> Dict[str, Any]:
        """
        Retrieves controlled conversational history for the Gemini context window.
        Uses rolling summary if conversation exceeds 10 turns.
        """
        conv = ConversationService.get_conversation(conversation_id, user_id)
        if not conv:
            return {"history": [], "summary": None, "last_project_code": None}

        messages = ConversationService.get_messages(conversation_id, user_id, limit=50)
        summary = conv.get("conversation_summary")

        # If long thread and no summary yet, create a concise extractive summary
        if len(messages) > 10 and not summary:
            first_user_turns = [m["content"] for m in messages[:4] if m["role"] == "user"]
            summary = f"Earlier discussion covered: {'; '.join(first_user_turns[:3])}"

        recent_slice = messages[-recent_turns:] if len(messages) > recent_turns else messages
        history_formatted = [{"role": m["role"], "content": m["content"]} for m in recent_slice]

        return {
            "history": history_formatted,
            "summary": summary,
            "last_project_code": conv.get("last_project_code"),
            "last_project_name": conv.get("last_project_name"),
            "chat_mode": conv.get("chat_mode")
        }

    @staticmethod
    def search_conversations(user_id: str, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Database-backed search across conversation titles and message contents."""
        q = query.strip()
        if not q:
            return []

        search_pattern = f"%{q}%"
        conn = get_db_connection()
        try:
            cursor = conn.cursor()

            # Search matching titles and contents
            sql = adapt_query("""
                SELECT DISTINCT c.conversation_id, c.title, c.chat_mode, c.is_permanent,
                                c.updated_at, c.message_count,
                                (SELECT content FROM ai_messages m WHERE m.conversation_id = c.conversation_id ORDER BY m.created_at DESC LIMIT 1) as last_message
                FROM ai_conversations c
                LEFT JOIN ai_messages m ON c.conversation_id = m.conversation_id
                WHERE c.user_id = ?
                  AND c.is_deleted = 0
                  AND (c.title LIKE ? OR m.content LIKE ?)
                ORDER BY c.updated_at DESC
                LIMIT ?;
            """)
            cursor.execute(sql, (user_id, search_pattern, search_pattern, limit))
            rows = cursor.fetchall()
        finally:
            conn.close()

        result = []
        for r in rows:
            d = dict(r)
            d["is_permanent"] = bool(d["is_permanent"])
            result.append(d)
        return result

    @staticmethod
    def export_conversation(
        conversation_id: str,
        user_id: str,
        export_format: str = "txt",
        is_admin: bool = False
    ) -> Optional[Dict[str, str]]:
        """
        Exports conversation transcript in TXT or JSON format.
        Sanitized strictly: only title, timestamp, and user/assistant messages.
        Guarantees zero leakage of system prompts, API keys, credentials, or tool internals.
        """
        conv = ConversationService.get_conversation(conversation_id, user_id, is_admin=is_admin)
        if not conv:
            return None

        messages = ConversationService.get_messages(conversation_id, user_id, limit=500, is_admin=is_admin)
        now_iso = datetime.now(timezone.utc).isoformat()
        safe_title = re.sub(r'[^\w\-_\. ]', '_', conv.get("title", "conversation"))[:40].strip()
        base_name = f"chat_{safe_title}_{conversation_id[:8]}"

        if export_format.lower() == "json":
            export_data = {
                "conversation_id": conv.get("conversation_id"),
                "title": conv.get("title"),
                "chat_mode": conv.get("chat_mode"),
                "is_permanent": bool(conv.get("is_permanent")),
                "created_at": conv.get("created_at"),
                "exported_at": now_iso,
                "messages": [
                    {
                        "role": m.get("role"),
                        "content": m.get("content"),
                        "created_at": m.get("created_at")
                    }
                    for m in messages
                    if m.get("role") in ("user", "assistant")
                ]
            }
            return {
                "content": json.dumps(export_data, indent=2),
                "filename": f"{base_name}.json",
                "media_type": "application/json; charset=utf-8"
            }
        else:
            # Default TXT format
            lines = [
                "=" * 80,
                f"CONVERSATION EXPORT: {conv.get('title', 'Untitled')}",
                f"Exported At: {now_iso}",
                f"Chat Mode: {conv.get('chat_mode')} | Permanent: {bool(conv.get('is_permanent'))}",
                "=" * 80,
                ""
            ]
            for m in messages:
                role = (m.get("role") or "user").upper()
                if role not in ("USER", "ASSISTANT"):
                    continue
                ts = m.get("created_at", "")
                content = m.get("content", "").strip()
                lines.append(f"[{ts}] {role}:")
                lines.append(content)
                lines.append("-" * 40)
                lines.append("")

            return {
                "content": "\n".join(lines),
                "filename": f"{base_name}.txt",
                "media_type": "text/plain; charset=utf-8"
            }

# Global singleton
conversation_service = ConversationService()
