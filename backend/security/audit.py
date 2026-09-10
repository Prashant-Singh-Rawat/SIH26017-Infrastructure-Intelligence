"""
Audit Logger Helper — SIH26017
Captures immutable system audit events into the database with client and user context.
"""

from typing import Optional, Dict, Any
from fastapi import Request
from backend.database import record_audit_log
from backend.security.auth import UserClaims

def log_audit_event(
    request: Request,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    user: Optional[UserClaims] = None,
    result: str = "SUCCESS",
    metadata: Optional[Dict[str, Any]] = None
):
    """Logs an audit event using request headers, IP address, and authenticated user context."""
    user_id = user.user_id if user else "anonymous"
    client_ip = request.client.host if request.client else "unknown"
    request_id = request.headers.get("X-Request-ID", getattr(request.state, "request_id", None))

    record_audit_log(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        user_id=user_id,
        request_id=request_id,
        ip_address=client_ip,
        result=result,
        metadata=metadata
    )
