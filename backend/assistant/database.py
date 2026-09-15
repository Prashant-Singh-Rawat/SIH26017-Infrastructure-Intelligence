"""
Assistant Database Layer — SIH26017 Platform
Manages persistent conversation storage, message history, model health tracking,
usage events, and automated idempotent expiration cleanup.
Fully dual-compatible with SQLite and PostgreSQL.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional, Tuple
from backend.database import get_db_connection, adapt_query, IS_POSTGRES

logger = logging.getLogger("assistant.database")
_assistant_tables_initialized = False

def init_assistant_tables(force: bool = False):
    """
    Initializes assistant tables and indices idempotently.
    Safe to call repeatedly across app startup and tests.
    """
    global _assistant_tables_initialized
    if _assistant_tables_initialized and not force:
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    pk_auto = "SERIAL PRIMARY KEY" if IS_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

    # 1. AI Conversations
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_conversations (
        conversation_id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        title TEXT NOT NULL,
        chat_mode TEXT NOT NULL DEFAULT '30-day',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        expires_at TEXT,
        last_message_at TEXT,
        status TEXT NOT NULL DEFAULT 'active',
        is_permanent INTEGER NOT NULL DEFAULT 0,
        is_deleted INTEGER NOT NULL DEFAULT 0,
        message_count INTEGER NOT NULL DEFAULT 0,
        conversation_summary TEXT,
        last_project_code INTEGER,
        last_project_name TEXT
    );
    """)

    # 2. AI Messages
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_messages (
        message_id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        model_used TEXT,
        provider_slot TEXT,
        request_id TEXT,
        token_usage TEXT,
        context_json TEXT,
        response_status TEXT DEFAULT 'success',
        latency_ms INTEGER DEFAULT 0,
        tools_called TEXT,
        client_actions TEXT,
        error_information TEXT,
        project_code INTEGER,
        FOREIGN KEY (conversation_id) REFERENCES ai_conversations(conversation_id) ON DELETE CASCADE
    );
    """)

    # 3. User Chat Preferences
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ai_chat_preferences (
        user_id TEXT PRIMARY KEY,
        default_chat_mode TEXT NOT NULL DEFAULT '30-day',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 4. Model & Slot Health Tracking
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS ai_model_health (
        id {pk_auto},
        credential_slot TEXT NOT NULL,
        model_name TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'HEALTHY',
        last_success_at TEXT,
        last_failure_at TEXT,
        cooldown_until TEXT,
        request_count INTEGER NOT NULL DEFAULT 0,
        success_count INTEGER NOT NULL DEFAULT 0,
        failure_count INTEGER NOT NULL DEFAULT 0,
        rate_limit_count INTEGER NOT NULL DEFAULT 0,
        timeout_count INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (credential_slot, model_name)
    );
    """)

    # 5. Usage & Diagnostic Events
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS ai_usage_events (
        id {pk_auto},
        request_id TEXT,
        conversation_id TEXT,
        credential_slot TEXT,
        model_used TEXT,
        event_type TEXT NOT NULL,
        status TEXT NOT NULL,
        latency_ms INTEGER DEFAULT 0,
        error_type TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 6. Gemini API Usage Telemetry Table
    cursor.execute(f"""
    CREATE TABLE IF NOT EXISTS gemini_usage (
        id {pk_auto},
        request_id TEXT NOT NULL,
        conversation_id TEXT,
        provider TEXT NOT NULL DEFAULT 'Google Gemini',
        key_slot TEXT,
        model TEXT,
        started_at TEXT,
        completed_at TEXT,
        success INTEGER NOT NULL DEFAULT 1,
        error_type TEXT,
        http_status INTEGER,
        latency_ms INTEGER DEFAULT 0,
        input_tokens INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Safe column additions for existing installations
    existing_conv_cols = []
    try:
        cursor.execute("PRAGMA table_info(ai_conversations);")
        existing_conv_cols = [c[1] for c in cursor.fetchall()]
    except Exception:
        pass

    if existing_conv_cols:
        if "last_message_at" not in existing_conv_cols:
            try:
                cursor.execute("ALTER TABLE ai_conversations ADD COLUMN last_message_at TEXT;")
            except Exception:
                pass
        if "status" not in existing_conv_cols:
            try:
                cursor.execute("ALTER TABLE ai_conversations ADD COLUMN status TEXT DEFAULT 'active';")
            except Exception:
                pass

    existing_msg_cols = []
    try:
        cursor.execute("PRAGMA table_info(ai_messages);")
        existing_msg_cols = [c[1] for c in cursor.fetchall()]
    except Exception:
        pass

    if existing_msg_cols:
        for col_name, col_type in [
            ("request_id", "TEXT"),
            ("token_usage", "TEXT"),
            ("context_json", "TEXT"),
            ("error_information", "TEXT")
        ]:
            if col_name not in existing_msg_cols:
                try:
                    cursor.execute(f"ALTER TABLE ai_messages ADD COLUMN {col_name} {col_type};")
                except Exception:
                    pass

    # Indices
    indices = [
        "CREATE INDEX IF NOT EXISTS idx_ai_conv_user ON ai_conversations (user_id, is_deleted, created_at);",
        "CREATE INDEX IF NOT EXISTS idx_ai_conv_expires ON ai_conversations (expires_at, is_permanent, is_deleted);",
        "CREATE INDEX IF NOT EXISTS idx_ai_conv_mode ON ai_conversations (chat_mode, is_permanent);",
        "CREATE INDEX IF NOT EXISTS idx_ai_msg_conv ON ai_messages (conversation_id, created_at);",
        "CREATE INDEX IF NOT EXISTS idx_ai_msg_role ON ai_messages (conversation_id, role);",
        "CREATE INDEX IF NOT EXISTS idx_ai_health_slot ON ai_model_health (credential_slot, model_name);",
        "CREATE INDEX IF NOT EXISTS idx_ai_events_type ON ai_usage_events (event_type, created_at);",
        "CREATE INDEX IF NOT EXISTS idx_gemini_usage_req ON gemini_usage (request_id);",
        "CREATE INDEX IF NOT EXISTS idx_gemini_usage_conv ON gemini_usage (conversation_id);"
    ]
    for idx_sql in indices:
        try:
            cursor.execute(idx_sql)
        except Exception as e:
            logger.debug(f"Index creation note: {e}")

    conn.commit()
    conn.close()
    _assistant_tables_initialized = True
    logger.info("AI Assistant tables and indices successfully initialized.")

def cleanup_expired_conversations() -> Dict[str, Any]:
    """
    Idempotent background/on-demand cleanup routine:
    1. Removes 30-day conversations whose `expires_at` is in the past and `is_permanent = 0`.
    2. Removes temporary conversations older than 24 hours (if abandoned).
    3. Deletes associated messages and metadata.
    4. Records a cleanup event in `ai_usage_events`.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    now_iso = datetime.now(timezone.utc).isoformat()
    yesterday_iso = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    try:
        # Find expired conversations to delete
        # Condition A: Expired 30-day chats
        # Condition B: Abandoned temporary chats > 24 hours old
        find_query = adapt_query("""
            SELECT conversation_id FROM ai_conversations 
            WHERE is_permanent = 0 
              AND (
                (expires_at IS NOT NULL AND expires_at <= ?)
                OR 
                (chat_mode = 'temporary' AND created_at <= ?)
              );
        """)
        cursor.execute(find_query, (now_iso, yesterday_iso))
        rows = cursor.fetchall()
        conv_ids = [r[0] if isinstance(r, (tuple, list)) else r["conversation_id"] for r in rows]

        deleted_conv_count = 0
        deleted_msg_count = 0

        if conv_ids:
            # Delete messages first (or via CASCADE)
            placeholders = ",".join(["?"] * len(conv_ids))
            del_msg_sql = adapt_query(f"DELETE FROM ai_messages WHERE conversation_id IN ({placeholders});")
            cursor.execute(del_msg_sql, tuple(conv_ids))
            deleted_msg_count = cursor.rowcount if cursor.rowcount >= 0 else len(conv_ids)

            # Delete conversations
            del_conv_sql = adapt_query(f"DELETE FROM ai_conversations WHERE conversation_id IN ({placeholders});")
            cursor.execute(del_conv_sql, tuple(conv_ids))
            deleted_conv_count = len(conv_ids)

        # Log cleanup event
        cursor.execute(adapt_query("""
            INSERT INTO ai_usage_events (event_type, status, error_type, created_at)
            VALUES ('cleanup', 'success', ?, ?);
        """), (f"deleted_convs={deleted_conv_count},deleted_msgs={deleted_msg_count}", now_iso))

        conn.commit()
        return {
            "status": "success",
            "deleted_conversations": deleted_conv_count,
            "deleted_messages": deleted_msg_count,
            "cleaned_at": now_iso
        }
    except Exception as e:
        conn.rollback()
        logger.error(f"Cleanup error: {e}")
        return {
            "status": "error",
            "error": str(e),
            "deleted_conversations": 0,
            "deleted_messages": 0
        }
    finally:
        conn.close()

# Auto-initialize tables on module import
try:
    init_assistant_tables()
except Exception as _e:
    logger.warning(f"Could not auto-initialize assistant tables on import: {_e}")
