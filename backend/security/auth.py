"""
Authentication & Role-Based Access Control (RBAC) Module — SIH26017
Supports Supabase Auth JWT tokens, local development tokens, and server-side role validation.
"""

import os
import time
from typing import Optional, List
from fastapi import Request, HTTPException, Security, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import jwt

JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET") or os.getenv("JWT_SECRET") or "sih26017-dev-super-secret-key-change-in-production"
JWT_ALGORITHM = "HS256"
security_scheme = HTTPBearer(auto_error=False)

ROLE_HIERARCHY = {
    "NATIONAL_ADMIN": 6,
    "ADMIN": 6,
    "STATE_OFFICER": 5,
    "DISTRICT_OFFICER": 4,
    "OFFICER": 4,
    "PROJECT_OFFICER": 3,
    "ANALYST": 3,
    "AUDITOR": 2,
    "VIEWER": 1
}

ROLE_ALIASES = {
    "NATIONAL_ADMIN": "NATIONAL_ADMIN",
    "ADMIN": "ADMIN",
    "STATE_OFFICER": "STATE_OFFICER",
    "STATE": "STATE_OFFICER",
    "DISTRICT_OFFICER": "DISTRICT_OFFICER",
    "DISTRICT": "DISTRICT_OFFICER",
    "OFFICER": "OFFICER",
    "MINISTRY": "OFFICER",
    "PROJECT_OFFICER": "PROJECT_OFFICER",
    "ANALYST": "ANALYST",
    "AUDITOR": "AUDITOR",
    "VIEWER": "VIEWER",
    "PUBLIC": "VIEWER"
}

class UserClaims(BaseModel):
    user_id: str
    email: str
    role: str
    full_name: Optional[str] = None
    department: Optional[str] = None

def create_access_token(
    user_id: str,
    email: str,
    role: str,
    full_name: Optional[str] = None,
    expires_in_seconds: int = 86400
) -> str:
    """Generates a signed JWT access token for user authentication."""
    payload = {
        "sub": user_id,
        "email": email,
        "role": role.upper(),
        "full_name": full_name or email.split("@")[0],
        "iat": int(time.time()),
        "exp": int(time.time()) + expires_in_seconds,
        "iss": "sih26017-auth-service"
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    return token

def decode_token(token: str) -> UserClaims:
    """Decodes and validates a signed JWT token."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM], options={"verify_exp": True})
        role = payload.get("role", "VIEWER").upper()
        if role not in ROLE_HIERARCHY:
            role = "VIEWER"
        return UserClaims(
            user_id=payload.get("sub", "anonymous"),
            email=payload.get("email", ""),
            role=role,
            full_name=payload.get("full_name"),
            department=payload.get("department")
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "TOKEN_EXPIRED", "message": "Authentication token has expired."}}
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "INVALID_TOKEN", "message": "Authentication token is invalid."}}
        )

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_scheme)
) -> UserClaims:
    """
    Mandatory authentication dependency.
    Rejects requests without valid Bearer tokens with 401.
    """
    if not credentials or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "AUTH_REQUIRED", "message": "Bearer authentication token required for this resource."}}
        )
    return decode_token(credentials.credentials)

async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_scheme)
) -> Optional[UserClaims]:
    """
    Optional authentication dependency for read endpoints that allow public views
    while enriching audit logs if a token is presented.
    """
    if not credentials or not credentials.credentials:
        return None
    try:
        return decode_token(credentials.credentials)
    except Exception:
        return None

def require_role(allowed_roles: List[str]):
    """
    Role-Based Access Control (RBAC) guard.
    Enforces minimum role permissions server-side.
    """
    allowed_upper = [ROLE_ALIASES.get(r.upper(), r.upper()) for r in allowed_roles]
    async def role_checker(current_user: UserClaims = Depends(get_current_user)):
        user_role = ROLE_ALIASES.get(current_user.role.upper(), current_user.role.upper())
        if user_role in ["ADMIN", "NATIONAL_ADMIN"] or user_role in allowed_upper:
            return current_user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN_ROLE",
                    "message": f"Access denied: User role '{current_user.role}' lacks permission for this operation. Required: {allowed_upper}"
                }
            }
        )
    return role_checker
