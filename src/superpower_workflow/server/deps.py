from __future__ import annotations

import hmac
import os


def get_api_key() -> str:
    return os.environ.get("SW_API_KEY", "")


def verify_api_key(provided: str, configured: str) -> bool:
    if not configured:
        return True
    return hmac.compare_digest(provided, configured)
