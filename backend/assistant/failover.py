"""
Gemini Multi-Key & Multi-Model Gateway with Circuit Breaker — SIH26017 Platform
Provides high availability, fault tolerance, cooldown management, and concurrency control.
Never exposes raw API keys in logs, responses, or storage.
"""

import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple

from backend.assistant.config import (
    get_gemini_credentials_pool,
    DEFAULT_GEMINI_MODEL,
    GEMINI_FALLBACK_MODELS,
    mask_key
)
from backend.database import get_db_connection, adapt_query

logger = logging.getLogger("assistant.failover")
_telemetry_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ai_telemetry")

# Circuit breaker states
STATE_HEALTHY = "HEALTHY"
STATE_DEGRADED = "DEGRADED"
STATE_COOLDOWN = "COOLDOWN"
STATE_DISABLED = "DISABLED"

STATUS_HEALTHY = STATE_HEALTHY
STATUS_DEGRADED = STATE_DEGRADED
STATUS_COOLDOWN = STATE_COOLDOWN
STATUS_DISABLED = STATE_DISABLED

# -----------------------------------------------------------------------------
# Structured Error Hierarchy & Classification
# -----------------------------------------------------------------------------

class AssistantError(Exception):
    """Base exception for AI Assistant operations."""
    pass

class TransientProviderError(AssistantError):
    """Temporary 5xx or server instability from Google Gemini."""
    pass

class RateLimitError(AssistantError):
    """HTTP 429 or rate limit quota exceeded."""
    pass

class QuotaError(AssistantError):
    """Project or daily quota exhausted."""
    pass

class AuthenticationError(AssistantError):
    """Invalid or deactivated API key."""
    pass

class InvalidRequestError(AssistantError):
    """Malformed prompt, invalid argument, or oversized input."""
    pass

class TimeoutError(AssistantError):
    """Provider request timed out or deadline exceeded."""
    pass

class NetworkError(AssistantError):
    """Socket, DNS, or network connection drop."""
    pass

class UnknownProviderError(AssistantError):
    """Unclassified provider exception."""
    pass

def classify_gemini_error(error_msg: str) -> Tuple[str, bool, bool]:
    """
    Classifies a Gemini error string into standard categories.
    Returns: (error_type, should_failover, should_disable_slot)
    """
    err_lower = error_msg.lower()
    
    # 1. Auth failure -> Permanent DISABLED
    if any(s in err_lower for s in ["api key not valid", "api_key_invalid", "invalid api key", "unauthenticated", "permission_denied"]):
        return "AuthenticationError", True, True
        
    # 2. Rate Limit (429) -> COOLDOWN & failover
    if "429" in err_lower or "resource_exhausted" in err_lower or "rate limit" in err_lower:
        return "RateLimitError", True, False
        
    # 3. Quota -> COOLDOWN & failover
    if "quota" in err_lower:
        return "QuotaError", True, False
        
    # 4. Timeout -> failover
    if any(s in err_lower for s in ["timeout", "timed out", "deadline_exceeded"]):
        return "TimeoutError", True, False
        
    # 5. Network -> failover
    if any(s in err_lower for s in ["connection reset", "connection refused", "socket", "network unreachable", "dns"]):
        return "NetworkError", True, False
        
    # 6. Transient 5xx -> failover
    if any(s in err_lower for s in ["500", "502", "503", "504", "unavailable", "internal server error"]):
        return "TransientProviderError", True, False
        
    # 7. Invalid user / prompt request (400) -> do NOT failover (client error)
    if "invalid argument" in err_lower or "bad request" in err_lower or "400" in err_lower:
        return "InvalidRequestError", False, False
        
    return "UnknownProviderError", True, False

# -----------------------------------------------------------------------------
# Structured Telemetry Logging Helpers
# -----------------------------------------------------------------------------

def log_request_start(request_id: str, conversation_id: Optional[str], model: str, key_slot: str):
    logger.info(f"AI_REQUEST_START request_id={request_id} conversation_id={conversation_id or 'none'} model={model} key_slot={key_slot}")

def log_request_success(request_id: str, key_slot: str, latency_ms: int):
    logger.info(f"AI_REQUEST_SUCCESS request_id={request_id} key_slot={key_slot} latency_ms={latency_ms}")

def log_provider_failure(request_id: str, key_slot: str, error: str):
    logger.warning(f"AI_PROVIDER_FAILURE request_id={request_id} key_slot={key_slot} error={error}")

def log_failover(request_id: str, from_key: str, to_key: str):
    logger.warning(f"AI_FAILOVER request_id={request_id} from_key={from_key} to_key={to_key}")

def log_request_success_after_failover(request_id: str, key_slot: str):
    logger.info(f"AI_REQUEST_SUCCESS_AFTER_FAILOVER request_id={request_id} key_slot={key_slot}")

class SlotHealth:
    def __init__(self, slot_id: str, api_key: str, masked_key: str, default_model: str = "gemini-2.5-flash", priority: int = 1, cooldown_duration_sec: Optional[float] = None, model: Optional[str] = None):
        self.slot_id = slot_id
        self.api_key = api_key
        self.masked_key = masked_key
        self.default_model = model or default_model
        self.priority = priority
        self.cooldown_duration_sec = cooldown_duration_sec
        
        self.status = STATE_HEALTHY
        self.consecutive_failures = 0
        self.consecutive_429s = 0
        self.cooldown_until: float = 0.0
        
        self.last_used_at: float = 0.0
        self.last_success_at: Optional[float] = None
        self.last_failure_at: Optional[float] = None
        self.last_error_reason: str = ""
        
        self.request_count = 0
        self.success_count = 0
        self.failure_count = 0
        self.rate_limit_count = 0
        self.timeout_count = 0
        
        self.active_requests = 0

    def is_available(self, current_time: Optional[float] = None) -> bool:
        """Determines if the slot is currently eligible to receive requests."""
        if current_time is None:
            current_time = time.time()
        if self.status == STATE_DISABLED:
            return False
            
        if self.status == STATE_COOLDOWN:
            if current_time >= self.cooldown_until:
                # Cooldown expired: probe health
                self.status = STATE_DEGRADED
                logger.info(f"Slot {self.slot_id} ({self.masked_key}) cooldown expired; now DEGRADED (probing).")
                return True
            return False
            
        return True

    def record_failure(self, error_msg: str, is_rate_limit: bool = False, retry_delay_seconds: Optional[float] = None):
        now = time.time()
        self.failure_count += 1
        self.consecutive_failures += 1
        self.last_failure_at = now
        self.last_error_reason = error_msg[:160]
        if is_rate_limit or "429" in error_msg.lower() or "quota" in error_msg.lower():
            self.rate_limit_count += 1
            self.consecutive_429s += 1
            if self.cooldown_duration_sec:
                cooldown = self.cooldown_duration_sec
            elif retry_delay_seconds and 1 <= retry_delay_seconds <= 120:
                cooldown = retry_delay_seconds
            else:
                cooldown = min(15 * (2 ** (self.consecutive_429s - 1)), 120)
            self.cooldown_until = now + cooldown
            self.status = STATE_COOLDOWN
        else:
            if self.consecutive_failures >= 3:
                self.cooldown_until = now + 30.0
                self.status = STATE_COOLDOWN
            else:
                self.status = STATE_DEGRADED

    def record_success(self, latency_ms: int = 0):
        self.consecutive_failures = 0
        self.consecutive_429s = 0
        self.success_count += 1
        self.status = STATE_HEALTHY
        self.last_success_at = time.time()

    def to_diagnostic_dict(self, current_time: Optional[float] = None) -> Dict[str, Any]:
        if current_time is None:
            current_time = time.time()
        cooldown_remaining = max(0.0, self.cooldown_until - current_time) if self.status == STATE_COOLDOWN else 0.0
        return {
            "slot_id": self.slot_id,
            "masked_key": self.masked_key,
            "model": self.default_model,
            "status": self.status,
            "active_requests": self.active_requests,
            "cooldown_remaining_seconds": round(cooldown_remaining, 1),
            "total_requests": self.request_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "rate_limit_count": self.rate_limit_count,
            "timeout_count": self.timeout_count,
            "last_used_at": datetime.fromtimestamp(self.last_used_at, tz=timezone.utc).isoformat() if self.last_used_at else None,
            "last_success_at": datetime.fromtimestamp(self.last_success_at, tz=timezone.utc).isoformat() if self.last_success_at else None,
            "last_failure_at": datetime.fromtimestamp(self.last_failure_at, tz=timezone.utc).isoformat() if self.last_failure_at else None,
            "last_error_reason": self.last_error_reason
        }

class GeminiFailoverGateway:
    """
    Gateway managing multi-credential slots (Slots 1..6) and candidate models.
    Provides intelligent selection, circuit breaking, concurrency tracking, and DB persistence.
    """
    def __init__(self):
        self._lock = threading.RLock()
        self._slots: Dict[str, SlotHealth] = {}
        self._rr_index = 0
        self.reload_slots()

    @property
    def slots(self) -> Dict[str, SlotHealth]:
        return self._slots

    @slots.setter
    def slots(self, value: Dict[str, SlotHealth]):
        with self._lock:
            self._slots = value

    def reload_slots(self):
        """Initializes or updates slots from environment configuration."""
        with self._lock:
            pool = get_gemini_credentials_pool()
            active_ids = {s["slot_id"] for s in pool}
            for sid in list(self._slots.keys()):
                if sid not in active_ids:
                    del self._slots[sid]
            for slot_info in pool:
                sid = slot_info["slot_id"]
                if sid not in self._slots:
                    self._slots[sid] = SlotHealth(
                        slot_id=sid,
                        api_key=slot_info["api_key"],
                        masked_key=slot_info["masked_key"],
                        default_model=slot_info["model"],
                        priority=slot_info.get("priority", 1)
                    )
                else:
                    self._slots[sid].api_key = slot_info["api_key"]
                    self._slots[sid].masked_key = slot_info["masked_key"]
            logger.info(f"Initialized Gemini Failover Gateway with {len(self._slots)} slots.")

    def get_candidate_plan(self, requested_model: Optional[str] = None) -> List[Tuple[SlotHealth, str]]:
        """
        Builds an ordered sequence of (slot, model) pairs to attempt for a request.
        Applies round-robin load distribution across healthy slots, preserving priority & circuit state.
        """
        now = time.time()
        with self._lock:
            all_available = [s for s in self._slots.values() if s.is_available(now)]

            healthy_slots = [s for s in all_available if s.status == STATE_HEALTHY]
            degraded_slots = [s for s in all_available if s.status == STATE_DEGRADED]

            # Round-robin among healthy slots to prevent always hammering Key 1
            if len(healthy_slots) > 1:
                rr_offset = self._rr_index % len(healthy_slots)
                self._rr_index = (self._rr_index + 1) % len(healthy_slots)
                healthy_slots = healthy_slots[rr_offset:] + healthy_slots[:rr_offset]

            available_slots = healthy_slots + degraded_slots

            plan = []
            models_to_try = [requested_model] if requested_model else []
            models_to_try.extend([DEFAULT_GEMINI_MODEL] + GEMINI_FALLBACK_MODELS)
            
            # Deduplicate models preserving order
            seen_models = set()
            unique_models = []
            for m in models_to_try:
                if m and m not in seen_models:
                    seen_models.add(m)
                    unique_models.append(m)

            # Interleave candidate plan: try all healthy slots with primary model first,
            # then fallback to secondary models across slots
            for model in unique_models:
                for slot in available_slots:
                    plan.append((slot, model))

            # Limit max candidates to 6 attempts per request (e.g. slots 1..6)
            return plan[:6]

    def record_start(self, slot_id: str):
        with self._lock:
            if slot_id in self._slots:
                slot = self._slots[slot_id]
                slot.active_requests += 1
                slot.request_count += 1
                slot.last_used_at = time.time()

    def record_success(self, slot_id: str, model_name: str, latency_ms: int = 0):
        now = time.time()
        with self._lock:
            if slot_id in self._slots:
                slot = self._slots[slot_id]
                slot.active_requests = max(0, slot.active_requests - 1)
                slot.success_count += 1
                slot.consecutive_failures = 0
                slot.consecutive_429s = 0
                slot.status = STATE_HEALTHY
                slot.last_success_at = now
                logger.info(f"Slot {slot_id} ({slot.masked_key}) request SUCCESS with {model_name} in {latency_ms}ms.")

        # Persist health state asynchronously/safely
        self._persist_slot_health(slot_id, model_name)

    def record_failure(
        self,
        slot_id: str,
        model_name: str,
        error_msg: str,
        retry_delay_seconds: Optional[float] = None
    ):
        now = time.time()
        err_lower = error_msg.lower()
        with self._lock:
            if slot_id in self._slots:
                slot = self._slots[slot_id]
                slot.active_requests = max(0, slot.active_requests - 1)
                slot.failure_count += 1
                slot.consecutive_failures += 1
                slot.last_failure_at = now
                slot.last_error_reason = error_msg[:160]

                # 1. Invalid API Key -> Permanent DISABLED
                if "api key not valid" in err_lower or "api_key_invalid" in err_lower or "invalid api key" in err_lower:
                    slot.status = STATE_DISABLED
                    logger.warning(f"Slot {slot_id} ({slot.masked_key}) DISABLED due to invalid key.")

                # 2. Quota / 429 -> Circuit COOLDOWN
                elif any(q in err_lower for q in ["quota", "rate limit", "429", "resource_exhausted"]):
                    slot.rate_limit_count += 1
                    slot.consecutive_429s += 1
                    cooldown = retry_delay_seconds if (retry_delay_seconds and 1 <= retry_delay_seconds <= 120) else min(15 * (2 ** (slot.consecutive_429s - 1)), 120)
                    slot.cooldown_until = now + cooldown
                    slot.status = STATE_COOLDOWN
                    logger.warning(f"Slot {slot_id} ({slot.masked_key}) put in COOLDOWN for {cooldown}s (429/quota).")

                # 3. Timeout or 5xx -> DEGRADED or COOLDOWN
                elif "timeout" in err_lower or "timed out" in err_lower or "503" in err_lower or "500" in err_lower:
                    slot.timeout_count += 1
                    if slot.consecutive_failures >= 3:
                        slot.cooldown_until = now + 30.0
                        slot.status = STATE_COOLDOWN
                        logger.warning(f"Slot {slot_id} ({slot.masked_key}) put in COOLDOWN for 30s after 3 consecutive errors.")
                    else:
                        slot.status = STATE_DEGRADED
                        logger.info(f"Slot {slot_id} ({slot.masked_key}) DEGRADED after error: {error_msg[:60]}")
                else:
                    slot.status = STATE_DEGRADED

        self._persist_slot_health(slot_id, model_name)

    def _persist_slot_health(self, slot_id: str, model_name: str):
        """Asynchronously records health stats in database table ai_model_health."""
        slot = self._slots.get(slot_id)
        if not slot:
            return

        now_iso = datetime.now(timezone.utc).isoformat()
        cooldown_iso = datetime.fromtimestamp(slot.cooldown_until, tz=timezone.utc).isoformat() if slot.cooldown_until else None
        last_succ_iso = datetime.fromtimestamp(slot.last_success_at, tz=timezone.utc).isoformat() if slot.last_success_at else None
        last_fail_iso = datetime.fromtimestamp(slot.last_failure_at, tz=timezone.utc).isoformat() if slot.last_failure_at else None
        status = slot.status
        request_count = slot.request_count
        success_count = slot.success_count
        failure_count = slot.failure_count
        rate_limit_count = slot.rate_limit_count
        timeout_count = slot.timeout_count

        def _do_write():
            conn = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                query = adapt_query("""
                    INSERT INTO ai_model_health (
                        credential_slot, model_name, status, last_success_at, last_failure_at,
                        cooldown_until, request_count, success_count, failure_count,
                        rate_limit_count, timeout_count, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(credential_slot, model_name) DO UPDATE SET
                        status = excluded.status,
                        last_success_at = excluded.last_success_at,
                        last_failure_at = excluded.last_failure_at,
                        cooldown_until = excluded.cooldown_until,
                        request_count = excluded.request_count,
                        success_count = excluded.success_count,
                        failure_count = excluded.failure_count,
                        rate_limit_count = excluded.rate_limit_count,
                        timeout_count = excluded.timeout_count,
                        updated_at = excluded.updated_at;
                """)
                cursor.execute(query, (
                    slot_id, model_name, status, last_succ_iso, last_fail_iso,
                    cooldown_iso, request_count, success_count, failure_count,
                    rate_limit_count, timeout_count, now_iso
                ))
                conn.commit()
            except Exception as e:
                logger.debug(f"Could not persist slot health: {e}")
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

        _telemetry_executor.submit(_do_write)

    def record_usage_telemetry(
        self,
        request_id: str,
        conversation_id: Optional[str],
        slot_id: str,
        model: str,
        started_at: str,
        completed_at: str,
        success: bool,
        error_type: Optional[str] = None,
        http_status: Optional[int] = 200,
        latency_ms: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0
    ):
        """Records granular API usage in database tables gemini_usage and ai_usage_events."""
        def _do_write():
            conn = None
            try:
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute(adapt_query("""
                    INSERT INTO gemini_usage (
                        request_id, conversation_id, key_slot, model, started_at, completed_at,
                        success, error_type, http_status, latency_ms, input_tokens, output_tokens
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """), (
                    request_id, conversation_id, slot_id, model, started_at, completed_at,
                    1 if success else 0, error_type, http_status, latency_ms, input_tokens, output_tokens
                ))
                cursor.execute(adapt_query("""
                    INSERT INTO ai_usage_events (
                        request_id, conversation_id, credential_slot, model_used,
                        event_type, status, latency_ms, error_type, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """), (
                    request_id, conversation_id, slot_id, model,
                    "gemini_inference", "success" if success else "failure",
                    latency_ms, error_type, completed_at
                ))
                conn.commit()
            except Exception as e:
                logger.debug(f"Could not record usage telemetry: {e}")
            finally:
                if conn:
                    try:
                        conn.close()
                    except Exception:
                        pass

        _telemetry_executor.submit(_do_write)

    def get_health_summary(self) -> Dict[str, Any]:
        """Returns non-sensitive health totals for public status endpoint."""
        now = time.time()
        with self._lock:
            healthy = sum(1 for s in self._slots.values() if s.status == STATE_HEALTHY)
            degraded = sum(1 for s in self._slots.values() if s.status == STATE_DEGRADED)
            cooldown = sum(1 for s in self._slots.values() if s.status == STATE_COOLDOWN and s.cooldown_until > now)
            disabled = sum(1 for s in self._slots.values() if s.status == STATE_DISABLED)
            total = len(self._slots)

            return {
                "total_slots": total,
                "healthy_slots": healthy,
                "healthy_credentials": healthy,
                "degraded_slots": degraded,
                "cooldown_slots": cooldown,
                "cooldown_credentials": cooldown,
                "disabled_slots": disabled,
                "ready": bool(healthy > 0 or degraded > 0)
            }

    def get_diagnostics_report(self) -> List[Dict[str, Any]]:
        """Returns safe diagnostic metrics for authorized admin dashboard."""
        now = time.time()
        with self._lock:
            return [s.to_diagnostic_dict(now) for s in self._slots.values()]

# Global gateway singleton
failover_gateway = GeminiFailoverGateway()
