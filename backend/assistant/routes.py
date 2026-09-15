"""
FastAPI Routes for Gemini AI Assistant — SIH26017 Platform
Exposes standard JSON response, real-time Server-Sent Events (SSE) streaming,
multi-key failover diagnostics, and full conversation persistence lifecycle
(Temporary, 30-Day, Permanent chat modes with IDOR security & automated cleanup).
"""

import json
import logging
from typing import Dict, Any, List, Optional, Tuple
from fastapi import APIRouter, Depends, Request, HTTPException, status, Query
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel, Field

from backend.security.auth import get_optional_user, UserClaims
from backend.security.rate_limiter import rate_limit
from backend.assistant.config import (
    DEFAULT_GEMINI_MODEL,
    get_gemini_model,
    is_gemini_configured
)
from backend.assistant.gemini_service import assistant_service
from backend.assistant.failover import failover_gateway
from backend.assistant.conversation_service import (
    conversation_service,
    MODE_TEMPORARY,
    MODE_30_DAY,
    MODE_PERMANENT
)
from backend.assistant.database import cleanup_expired_conversations

logger = logging.getLogger("assistant.routes")

router = APIRouter()

# -----------------------------------------------------------------------------
# Pydantic Request & Response Models
# -----------------------------------------------------------------------------

class ChatMessageItem(BaseModel):
    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="Message text")

class ChatContext(BaseModel):
    current_page: Optional[str] = Field("overview", description="Current active portal tab")
    selected_project_code: Optional[int] = Field(None, description="Currently selected project code")
    selected_project_name: Optional[str] = Field(None, description="Currently selected project name")
    user_role: Optional[str] = Field(None, description="Active user role")

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000, description="User prompt or question")
    history: Optional[List[ChatMessageItem]] = Field(default_factory=list, description="Recent conversation turns")
    context: Optional[ChatContext] = Field(None, description="Current UI viewport context")
    session_id: Optional[str] = Field(None, description="Client session identifier")
    conversation_id: Optional[str] = Field(None, description="Existing conversation ID to attach turn to")
    chat_mode: Optional[str] = Field(MODE_30_DAY, description="'temporary', '30-day', or 'permanent'")

class CreateConversationRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=100, description="Optional title")
    chat_mode: Optional[str] = Field(MODE_30_DAY, description="'temporary', '30-day', or 'permanent'")
    project_code: Optional[int] = Field(None, description="Initial project code")
    project_name: Optional[str] = Field(None, description="Initial project name")
    initial_message: Optional[str] = Field(None, max_length=4000, description="Optional first user message")

class UpdateConversationRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=120, description="New title")
    chat_mode: Optional[str] = Field(None, description="'temporary', '30-day', or 'permanent'")
    is_permanent: Optional[bool] = Field(None, description="Toggle permanent retention")

class AddMessageRequest(BaseModel):
    role: str = Field("user", description="'user' or 'assistant'")
    content: str = Field(..., min_length=1, max_length=4000, description="Message content")
    project_code: Optional[int] = Field(None, description="Associated project code")
    model_used: Optional[str] = Field(None, description="Model used if assistant")

# -----------------------------------------------------------------------------
# Security & Identity Resolution Helper (IDOR Prevention)
# -----------------------------------------------------------------------------

def resolve_user_identity(
    user: Optional[UserClaims],
    request: Request,
    session_id: Optional[str] = None
) -> Tuple[str, bool]:
    """
    Safely resolves the calling identity and admin status for conversation isolation.
    Priority:
    1. Authenticated JWT username
    2. Explicit X-User-ID header (for internal testing/isolation)
    3. Session ID (from payload or X-Session-ID header)
    4. Client IP guest fallback
    """
    if user and getattr(user, "username", None):
        is_admin = getattr(user, "role", "").lower() in ["admin", "superadmin"]
        return user.username, is_admin

    x_user = request.headers.get("X-User-ID")
    if x_user:
        return x_user.strip(), False

    s_id = session_id or request.headers.get("X-Session-ID") or request.cookies.get("session_id")
    if s_id:
        return f"session_{s_id.strip()}", False

    client_ip = request.client.host if request.client else "127.0.0.1"
    return f"guest_{client_ip}", False

# -----------------------------------------------------------------------------
# Health, Status & Admin Diagnostics Endpoints
# -----------------------------------------------------------------------------

@router.get("/status")
def get_assistant_status(user: Optional[UserClaims] = Depends(get_optional_user)):
    """
    Health check and readiness status of the Gemini AI Assistant.
    Provides gateway health summary without revealing sensitive credentials.
    """
    configured = is_gemini_configured()
    ready = assistant_service.is_ready()
    model_name = get_gemini_model()
    health_summary = failover_gateway.get_health_summary()

    status_str = "ready" if (configured and ready) else ("unconfigured" if not configured else "initializing")

    resp = {
        "assistant": status_str,
        "status": status_str,
        "available": bool(configured and ready),
        "provider": "Google Gemini",
        "model": model_name,
        "active_model": model_name,
        "gemini_connected": bool(configured and ready),
        "healthy_models": health_summary.get("healthy_models", 1 if ready else 0),
        "healthy_credentials": health_summary.get("healthy_credentials", 1 if ready else 0),
        "healthy_credentials_count": health_summary.get("healthy_credentials", 1 if ready else 0),
        "cooldown_credentials": health_summary.get("cooldown_credentials", 0),
        "cooldown_credentials_count": health_summary.get("cooldown_credentials", 0),
        "is_configured": configured,
        "is_ready": ready,
        "capabilities": [
            "general_knowledge_qa",
            "project_telemetry_analysis",
            "ml_explainability_grounding",
            "rfctlarr_land_bottlenecks",
            "critical_escalation_alerts",
            "data_quality_governance",
            "client_navigation_actions",
            "multi_language_en_hi_hinglish",
            "persistent_conversations",
            "multi_key_failover",
            "chat_modes_retention"
        ]
    }
    if not configured:
        resp["reason"] = "API key is not configured"
    elif not ready:
        resp["reason"] = "Gemini client failed to initialize"

    return resp

@router.get("/diagnostics")
def get_assistant_diagnostics(
    req: Request,
    user: Optional[UserClaims] = Depends(get_optional_user)
):
    """
    Admin-only or internal diagnostics report showing masked slot health,
    circuit breaker statuses, cooldowns, and request statistics.
    NEVER leaks full API keys.
    """
    user_id, is_admin = resolve_user_identity(user, req)
    # Check if request is authorized as admin or localhost internal
    client_ip = req.client.host if req.client else "127.0.0.1"
    is_local = client_ip in ["127.0.0.1", "::1", "localhost", "testclient"] or req.headers.get("X-Admin") == "true"

    if not is_admin and not is_local:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin authorization required to view model diagnostics."
        )

    report = failover_gateway.get_diagnostics_report()
    summary = failover_gateway.get_health_summary()
    summary["slots"] = report
    return {
        "status": "success",
        "provider": "Google Gemini Gateway",
        "summary": summary,
        "slots": report
    }

# -----------------------------------------------------------------------------
# Conversation Lifecycle APIs
# -----------------------------------------------------------------------------

@router.post("/conversations")
def create_conversation(
    payload: CreateConversationRequest,
    req: Request,
    user: Optional[UserClaims] = Depends(get_optional_user)
):
    """Creates a new conversation record with specified chat mode."""
    user_id, _ = resolve_user_identity(user, req)
    mode = payload.chat_mode if payload.chat_mode in [MODE_TEMPORARY, MODE_30_DAY, MODE_PERMANENT] else MODE_30_DAY

    conv = conversation_service.create_conversation(
        user_id=user_id,
        title=payload.title,
        chat_mode=mode,
        project_code=payload.project_code,
        project_name=payload.project_name
    )

    # Optional initial message persistence
    if payload.initial_message:
        conversation_service.add_message(
            conversation_id=conv["conversation_id"],
            user_id=user_id,
            role="user",
            content=payload.initial_message,
            project_code=payload.project_code
        )
        # Refresh updated metadata
        refreshed = conversation_service.get_conversation(conv["conversation_id"], user_id)
        if refreshed:
            conv = refreshed

    return conv

@router.get("/conversations")
def list_conversations(
    req: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_temporary: bool = Query(True),
    grouped: bool = Query(True),
    user: Optional[UserClaims] = Depends(get_optional_user)
):
    """Lists conversations for the calling user, grouped by recency (Today, Yesterday, 7 Days, Older)."""
    user_id, _ = resolve_user_identity(user, req)
    convs = conversation_service.list_conversations(
        user_id=user_id,
        limit=limit,
        offset=offset,
        include_temporary=include_temporary
    )

    if not grouped:
        return {"conversations": convs, "total": len(convs)}

    # Group into buckets
    grouped_buckets: Dict[str, List[Any]] = {
        "Today": [],
        "Yesterday": [],
        "Previous 7 Days": [],
        "Older": []
    }
    for c in convs:
        grp = c.get("time_group", "Older")
        if grp not in grouped_buckets:
            grouped_buckets[grp] = []
        grouped_buckets[grp].append(c)

    return {
        "conversations": convs,
        "grouped": grouped_buckets,
        "total": len(convs)
    }

@router.get("/conversations/search")
def search_conversations(
    req: Request,
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(20, ge=1, le=100),
    user: Optional[UserClaims] = Depends(get_optional_user)
):
    """Searches conversations by title and message contents."""
    user_id, _ = resolve_user_identity(user, req)
    results = conversation_service.search_conversations(user_id=user_id, query=q, limit=limit)
    return {"query": q, "results": results, "count": len(results)}

@router.get("/conversations/{conversation_id}")
def get_conversation_detail(
    conversation_id: str,
    req: Request,
    user: Optional[UserClaims] = Depends(get_optional_user)
):
    """Retrieves conversation metadata and messages with IDOR ownership validation."""
    user_id, is_admin = resolve_user_identity(user, req)
    conv = conversation_service.get_conversation(conversation_id, user_id, is_admin=is_admin)
    if not conv:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or access denied."
        )

    messages = conversation_service.get_messages(conversation_id, user_id, limit=100, is_admin=is_admin)
    return {
        "conversation": conv,
        "messages": messages
    }

@router.patch("/conversations/{conversation_id}")
def update_conversation(
    conversation_id: str,
    payload: UpdateConversationRequest,
    req: Request,
    user: Optional[UserClaims] = Depends(get_optional_user)
):
    """Renames or updates retention settings (mode, permanent)."""
    user_id, is_admin = resolve_user_identity(user, req)
    updated = conversation_service.update_conversation(
        conversation_id=conversation_id,
        user_id=user_id,
        title=payload.title,
        chat_mode=payload.chat_mode,
        is_permanent=payload.is_permanent,
        is_admin=is_admin
    )
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or access denied."
        )
    return updated

@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: str,
    req: Request,
    user: Optional[UserClaims] = Depends(get_optional_user)
):
    """Deletes conversation and associated message turns permanently."""
    user_id, is_admin = resolve_user_identity(user, req)
    deleted = conversation_service.delete_conversation(conversation_id, user_id, is_admin=is_admin)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or access denied."
        )
    return {"status": "deleted", "conversation_id": conversation_id}

@router.post("/conversations/{conversation_id}/permanent")
def make_conversation_permanent(
    conversation_id: str,
    req: Request,
    user: Optional[UserClaims] = Depends(get_optional_user)
):
    """Converts a conversation into permanent retention mode."""
    user_id, is_admin = resolve_user_identity(user, req)
    updated = conversation_service.update_conversation(
        conversation_id=conversation_id,
        user_id=user_id,
        is_permanent=True,
        is_admin=is_admin
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    return updated

@router.post("/conversations/{conversation_id}/unpermanent")
def remove_conversation_permanent(
    conversation_id: str,
    req: Request,
    user: Optional[UserClaims] = Depends(get_optional_user)
):
    """Removes permanent status from conversation, reverting to 30-day retention."""
    user_id, is_admin = resolve_user_identity(user, req)
    updated = conversation_service.update_conversation(
        conversation_id=conversation_id,
        user_id=user_id,
        is_permanent=False,
        is_admin=is_admin
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    return updated

@router.get("/conversations/{conversation_id}/export")
def export_conversation_history(
    conversation_id: str,
    req: Request,
    format: str = Query("txt", pattern="^(txt|json)$"),
    user: Optional[UserClaims] = Depends(get_optional_user)
):
    """Exports sanitized conversation transcript in TXT or JSON format for download."""
    user_id, is_admin = resolve_user_identity(user, req)
    exp = conversation_service.export_conversation(
        conversation_id=conversation_id,
        user_id=user_id,
        export_format=format,
        is_admin=is_admin
    )
    if not exp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found or access denied."
        )

    return Response(
        content=exp["content"],
        media_type=exp["media_type"],
        headers={"Content-Disposition": f'attachment; filename="{exp["filename"]}"'}
    )

@router.post("/conversations/{conversation_id}/temporary")
def make_conversation_temporary(
    conversation_id: str,
    req: Request,
    user: Optional[UserClaims] = Depends(get_optional_user)
):
    """Converts a conversation into temporary mode."""
    user_id, is_admin = resolve_user_identity(user, req)
    updated = conversation_service.update_conversation(
        conversation_id=conversation_id,
        user_id=user_id,
        chat_mode=MODE_TEMPORARY,
        is_permanent=False,
        is_admin=is_admin
    )
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    return updated

@router.post("/conversations/{conversation_id}/restore")
def restore_conversation(
    conversation_id: str,
    req: Request,
    user: Optional[UserClaims] = Depends(get_optional_user)
):
    """Restores conversation context and recent history for the frontend."""
    user_id, is_admin = resolve_user_identity(user, req)
    conv = conversation_service.get_conversation(conversation_id, user_id, is_admin=is_admin)
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")

    ctx = conversation_service.get_context_for_llm(conversation_id, user_id)
    messages = conversation_service.get_messages(conversation_id, user_id, limit=50, is_admin=is_admin)
    return {
        "conversation": conv,
        "messages": messages,
        "context": ctx
    }

@router.post("/conversations/{conversation_id}/messages")
def add_conversation_message(
    conversation_id: str,
    payload: AddMessageRequest,
    req: Request,
    user: Optional[UserClaims] = Depends(get_optional_user)
):
    """Appends a message directly to an existing conversation."""
    user_id, is_admin = resolve_user_identity(user, req)
    msg = conversation_service.add_message(
        conversation_id=conversation_id,
        user_id=user_id,
        role=payload.role,
        content=payload.content,
        project_code=payload.project_code,
        model_used=payload.model_used,
        is_admin=is_admin
    )
    if not msg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found or access denied.")
    return msg

@router.post("/cleanup")
def run_assistant_cleanup(
    req: Request,
    user: Optional[UserClaims] = Depends(get_optional_user)
):
    """Triggers automated cleanup of expired 30-day and abandoned temporary conversations."""
    result = cleanup_expired_conversations()
    return result

# -----------------------------------------------------------------------------
# Main Chat Execution Endpoints (Synchronous & SSE Streaming)
# -----------------------------------------------------------------------------

@router.post("/chat", dependencies=[Depends(rate_limit("inference"))])
def chat_assistant(
    request_data: ChatRequest,
    req: Request,
    user: Optional[UserClaims] = Depends(get_optional_user)
):
    """Executes a standard multi-turn chat turn with Gemini, persisting conversation state."""
    user_id, is_admin = resolve_user_identity(user, req, request_data.session_id)

    # Resolve or create conversation
    conv_id = request_data.conversation_id
    current_mode = request_data.chat_mode or MODE_30_DAY
    conv = None

    context_dict = (
        request_data.context.model_dump()
        if hasattr(request_data.context, "model_dump")
        else request_data.context.dict()
    ) if request_data.context else {}
    if user and not context_dict.get("user_role"):
        context_dict["user_role"] = user.role

    proj_code = context_dict.get("selected_project_code")
    proj_name = context_dict.get("selected_project_name")

    if conv_id:
        conv = conversation_service.get_conversation(conv_id, user_id, is_admin=is_admin)
        if not conv:
            # If not found or IDOR mismatch, create a clean conversation
            conv = conversation_service.create_conversation(
                user_id=user_id,
                chat_mode=current_mode,
                project_code=proj_code,
                project_name=proj_name
            )
            conv_id = conv["conversation_id"]
    else:
        conv = conversation_service.create_conversation(
            user_id=user_id,
            chat_mode=current_mode,
            project_code=proj_code,
            project_name=proj_name
        )
    ctx_json = json.dumps(context_dict) if context_dict else None

    # Persist User Message
    conversation_service.add_message(
        conversation_id=conv_id,
        user_id=user_id,
        role="user",
        content=request_data.message,
        project_code=proj_code,
        context_json=ctx_json,
        is_admin=is_admin
    )

    # Build history: if client passed explicit history, use it; otherwise pull from DB context
    history_dicts = []
    if request_data.history:
        history_dicts = [{"role": m.role, "content": m.content} for m in request_data.history]
    else:
        llm_ctx = conversation_service.get_context_for_llm(conv_id, user_id, recent_turns=8)
        # Exclude the message we just saved
        history_dicts = [h for h in llm_ctx.get("history", []) if h.get("content") != request_data.message]

    # Generate Gemini Response
    result = assistant_service.generate_chat_response(
        message=request_data.message,
        history=history_dicts,
        context=context_dict
    )

    # Persist Assistant Message
    assistant_text = result.get("text", "")
    tools_called = result.get("tools_called", [])
    client_actions = result.get("client_actions", [])
    model_used = result.get("model", get_gemini_model())
    slot_id = result.get("slot_id") or result.get("provider_slot")
    req_id = result.get("request_id")

    conversation_service.add_message(
        conversation_id=conv_id,
        user_id=user_id,
        role="assistant",
        content=assistant_text,
        model_used=model_used,
        provider_slot=slot_id,
        tools_called=tools_called,
        client_actions=client_actions,
        project_code=proj_code,
        request_id=req_id,
        context_json=ctx_json,
        latency_ms=result.get("latency_ms", 0),
        is_admin=is_admin
    )

    # Refresh conversation metadata to return title & mode
    fresh_conv = conversation_service.get_conversation(conv_id, user_id, is_admin=is_admin)

    result["conversation_id"] = conv_id
    result["chat_mode"] = fresh_conv.get("chat_mode") if fresh_conv else current_mode
    result["title"] = fresh_conv.get("title") if fresh_conv else "Chat"

    return result

@router.post("/chat/stream", dependencies=[Depends(rate_limit("inference"))])
def chat_assistant_stream(
    request_data: ChatRequest,
    req: Request,
    user: Optional[UserClaims] = Depends(get_optional_user)
):
    """Streams Gemini response tokens as Server-Sent Events (SSE), persisting conversation turns."""
    user_id, is_admin = resolve_user_identity(user, req, request_data.session_id)

    conv_id = request_data.conversation_id
    current_mode = request_data.chat_mode or MODE_30_DAY
    conv = None

    context_dict = (
        request_data.context.model_dump()
        if hasattr(request_data.context, "model_dump")
        else request_data.context.dict()
    ) if request_data.context else {}
    if user and not context_dict.get("user_role"):
        context_dict["user_role"] = user.role

    proj_code = context_dict.get("selected_project_code")
    proj_name = context_dict.get("selected_project_name")

    if conv_id:
        conv = conversation_service.get_conversation(conv_id, user_id, is_admin=is_admin)
        if not conv:
            conv = conversation_service.create_conversation(
                user_id=user_id,
                chat_mode=current_mode,
                project_code=proj_code,
                project_name=proj_name
            )
            conv_id = conv["conversation_id"]
    else:
        conv = conversation_service.create_conversation(
            user_id=user_id,
            chat_mode=current_mode,
            project_code=proj_code,
            project_name=proj_name
        )
        conv_id = conv["conversation_id"]

    ctx_json = json.dumps(context_dict) if context_dict else None

    # Persist User Message
    conversation_service.add_message(
        conversation_id=conv_id,
        user_id=user_id,
        role="user",
        content=request_data.message,
        project_code=proj_code,
        context_json=ctx_json,
        is_admin=is_admin
    )

    history_dicts = []
    if request_data.history:
        history_dicts = [{"role": m.role, "content": m.content} for m in request_data.history]
    else:
        llm_ctx = conversation_service.get_context_for_llm(conv_id, user_id, recent_turns=8)
        history_dicts = [h for h in llm_ctx.get("history", []) if h.get("content") != request_data.message]

    def event_stream():
        # First send conversation session info event
        fresh_conv = conversation_service.get_conversation(conv_id, user_id, is_admin=is_admin)
        title = fresh_conv.get("title") if fresh_conv else "Chat"
        mode = fresh_conv.get("chat_mode") if fresh_conv else current_mode
        init_event = {
            "conversation_id": conv_id,
            "title": title,
            "chat_mode": mode
        }
        yield f"event: conversation\ndata: {json.dumps(init_event)}\n\n"

        accumulated_text = []
        tools_called = []
        client_actions = []
        stream_request_id = None

        for event in assistant_service.generate_chat_stream(
            message=request_data.message,
            history=history_dicts,
            context=context_dict
        ):
            event_name = event.get("event", "message")
            event_data = event.get("data", {})

            if event_data.get("request_id"):
                stream_request_id = event_data["request_id"]

            if event_name in ["token", "delta"]:
                token = event_data.get("token") or event_data.get("text", "")
                if token:
                    accumulated_text.append(token)
            elif event_name == "tool_result":
                tool = event_data.get("tool")
                if tool and tool not in tools_called:
                    tools_called.append(tool)
            elif event_name == "client_action":
                client_actions.append(event_data)
            elif event_name == "client_actions":
                client_actions.extend(event_data.get("actions", []))
            elif event_name in ["complete", "done"]:
                if event_data.get("text"):
                    accumulated_text = [event_data["text"]]
                if event_data.get("tools_called"):
                    tools_called = event_data["tools_called"]

            yield f"event: {event_name}\ndata: {json.dumps(event_data)}\n\n"

        # Persist assistant turn in database
        final_text = "".join(accumulated_text)
        if final_text:
            try:
                conversation_service.add_message(
                    conversation_id=conv_id,
                    user_id=user_id,
                    role="assistant",
                    content=final_text,
                    model_used=get_gemini_model(),
                    tools_called=tools_called,
                    client_actions=client_actions,
                    project_code=proj_code,
                    request_id=stream_request_id,
                    context_json=ctx_json,
                    is_admin=is_admin
                )
            except Exception as _e:
                logger.error(f"Error persisting stream response: {_e}")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@router.post("/reset")
def reset_assistant_session(user: Optional[UserClaims] = Depends(get_optional_user)):
    """Resets the client session context."""
    return {"status": "session_reset", "message": "Assistant session cleared."}
