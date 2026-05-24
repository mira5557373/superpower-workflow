from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import asdict, dataclass, field


@dataclass
class AuditEntry:
    seq: int = 0
    timestamp: str = ""
    event: str = ""
    run_id: str = ""
    milestone: str = ""
    data: dict = field(default_factory=dict)
    prev_hash: str = ""
    hash: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def to_dict(self) -> dict:
        return asdict(self)


def _canonical_json(entry: dict) -> str:
    filtered = {k: v for k, v in sorted(entry.items()) if k != "hash"}
    return json.dumps(filtered, sort_keys=True, separators=(",", ":"))


def _compute_hash(canonical: str, key: bytes) -> str:
    return hmac.new(key, canonical.encode(), hashlib.sha256).hexdigest()
