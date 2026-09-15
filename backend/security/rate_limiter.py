"""
Sliding-Window Rate Limiter — SIH26017
In-memory thread-safe rate limiter protecting ML inference, administrative, and public endpoints.
"""

import time
import threading
from typing import Dict, List
from fastapi import Request, HTTPException, status

import os

INFERENCE_RATE_LIMIT = int(os.getenv("RATE_LIMIT_PER_MINUTE", os.getenv("RATE_LIMIT_INFERENCE", "30")))
STANDARD_RATE_LIMIT = int(os.getenv("RATE_LIMIT_STANDARD", "150"))
ADMIN_RATE_LIMIT = int(os.getenv("RATE_LIMIT_ADMIN", "15"))

RATE_LIMIT_CONFIG = {
    "standard": {"requests": STANDARD_RATE_LIMIT, "window_seconds": 60},
    "inference": {"requests": INFERENCE_RATE_LIMIT, "window_seconds": 60},
    "admin": {"requests": ADMIN_RATE_LIMIT, "window_seconds": 60},
    "test_strict": {"requests": 3, "window_seconds": 60}
}

class SlidingWindowRateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        # Storage: { "bucket_type:ip": [timestamp1, timestamp2, ...] }
        self._requests: Dict[str, List[float]] = {}

    def is_rate_limited(self, key: str, max_requests: int, window_seconds: int) -> bool:
        now = time.time()
        window_start = now - window_seconds

        with self._lock:
            if key not in self._requests:
                self._requests[key] = [now]
                return False

            # Purge timestamps outside sliding window
            timestamps = [t for t in self._requests[key] if t > window_start]
            
            if len(timestamps) >= max_requests:
                self._requests[key] = timestamps
                return True

            timestamps.append(now)
            self._requests[key] = timestamps
            return False

_limiter = SlidingWindowRateLimiter()

def rate_limit(bucket: str = "standard"):
    """FastAPI dependency for rate limiting."""
    config = RATE_LIMIT_CONFIG.get(bucket, RATE_LIMIT_CONFIG["standard"])
    max_req = config["requests"]
    window = config["window_seconds"]

    async def limiter_dependency(request: Request):
        if os.getenv("PYTEST_CURRENT_TEST"):
            return

        client_ip = request.client.host if request.client else "unknown"
        if client_ip == "testclient":
            return

        # Forwarded for header if behind reverse proxy
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()

        key = f"{bucket}:{client_ip}"
        if _limiter.is_rate_limited(key, max_req, window):
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(window)},
                detail={
                    "error": {
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": f"Rate limit exceeded ({max_req} req/{window}s). Please slow down.",
                        "retry_after_seconds": window
                    }
                }
            )
    return limiter_dependency
