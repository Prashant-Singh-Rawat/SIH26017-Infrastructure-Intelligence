"""
Gemini AI Assistant Configuration — SIH26017 Platform
Loads server-side environment variables and sets defaults for model inference.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Robust project root resolution from file location (backend/assistant/config.py -> parents[2] = project root)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

def reload_environment():
    """Reloads .env and .env.local from the project root."""
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)
    env_local_path = PROJECT_ROOT / ".env.local"
    if env_local_path.exists():
        load_dotenv(dotenv_path=env_local_path, override=False)

# Initial load
reload_environment()

def get_gemini_api_key() -> str:
    """Returns the current server-side Gemini API key."""
    return (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()

def get_gemini_model() -> str:
    """Returns the configured Gemini model name."""
    return os.getenv("GEMINI_MODEL", "gemini-3.7-flash").strip()

GEMINI_API_KEY = get_gemini_api_key()
DEFAULT_GEMINI_MODEL = get_gemini_model()
FALLBACK_GEMINI_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash").strip()
GEMINI_FALLBACK_MODELS = [
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-flash-lite-latest"
]

# Generation configuration defaults
DEFAULT_TEMPERATURE = float(os.getenv("GEMINI_TEMPERATURE", "0.2"))
DEFAULT_MAX_OUTPUT_TOKENS = int(os.getenv("GEMINI_MAX_TOKENS", "2048"))

# Rate limiting for AI assistant (calls per minute per user/session)
def mask_key(key: Optional[str]) -> str:
    """Safely masks an API key, showing only the last 4 characters."""
    if not key:
        return "UNCONFIGURED"
    key = str(key).strip()
    if len(key) <= 6:
        return "****"
    return f"****{key[-4:]}"

def get_gemini_models_pool() -> List[str]:
    """Returns list of configured and fallback models in preference order."""
    models = [get_gemini_model()]
    for i in range(1, 7):
        m = (os.getenv(f"GEMINI_MODEL_{i}") or "").strip()
        if m and m not in models:
            models.append(m)
    for m in GEMINI_FALLBACK_MODELS:
        if m not in models:
            models.append(m)
    return models

def get_gemini_credentials_pool():
    """
    Scans environment for GEMINI_API_KEY_1..6 and primary GEMINI_API_KEY / GOOGLE_API_KEY.
    Returns list of slot dicts with masked identifiers. Never exposes raw keys in logs or UI.
    """
    pool = []
    seen_keys = set()

    # 1. Primary default key
    default_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if default_key and len(default_key) > 6:
        seen_keys.add(default_key)
        pool.append({
            "slot_id": "slot_1",
            "slot_number": 1,
            "api_key": default_key,
            "masked_key": mask_key(default_key),
            "model": get_gemini_model(),
            "priority": 1
        })

    # 2. Numbered slots 1 to 6
    for i in range(1, 7):
        k = (os.getenv(f"GEMINI_API_KEY_{i}") or "").strip()
        m = (os.getenv(f"GEMINI_MODEL_{i}") or "").strip() or get_gemini_model()
        if k and len(k) > 6 and k not in seen_keys:
            seen_keys.add(k)
            slot_num = len(pool) + 1
            pool.append({
                "slot_id": f"slot_{slot_num}",
                "slot_number": slot_num,
                "api_key": k,
                "masked_key": mask_key(k),
                "model": m,
                "priority": slot_num
            })

    return pool

def is_gemini_configured() -> bool:
    """Returns True if at least one valid Gemini key is present in the pool."""
    pool = get_gemini_credentials_pool()
    return len(pool) > 0

