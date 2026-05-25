from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


def format_message(event: str, payload: dict[str, Any]) -> str:
    milestone = payload.get("milestone", "unknown")
    if event == "milestone_start":
        return f"Starting milestone: {milestone}"
    if event == "milestone_complete":
        cost = payload.get("cost_usd", 0.0)
        tests = payload.get("test_count", 0)
        return f"Milestone {milestone} complete. Tests: {tests}, Cost: ${cost}"
    if event == "milestone_failed":
        phase = payload.get("phase", "unknown")
        reason = payload.get("reason", "")
        return f"Milestone {milestone} FAILED at {phase}. Error: {reason}"
    if event == "ci_fix":
        attempt = payload.get("attempt", 0)
        max_attempts = payload.get("max_attempts", 3)
        status = payload.get("status", "")
        return f"CI fix attempt {attempt}/{max_attempts} for {milestone}: {status}"
    return f"[{event}] {json.dumps(payload)}"


def send_notification(config: dict, event: str, payload: dict[str, Any]) -> bool:
    if not config:
        return False
    allowed_events = config.get("events", [])
    if event not in allowed_events:
        return False
    url_env = config.get("webhook_url_env", "")
    url = os.environ.get(url_env, "")
    if not url:
        return False
    text = format_message(event, payload)
    data = json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except OSError:
        return False
