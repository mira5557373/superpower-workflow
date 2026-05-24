from __future__ import annotations

import hashlib
import hmac
import json
import os
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


def _hkdf_sha256(ikm: bytes, info: bytes = b"", salt: bytes = b"") -> bytes:
    if not salt:
        salt = b"\x00" * 32
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()


def derive_key(env_var: str = "SW_AUDIT_KEY") -> bytes | None:
    raw = os.environ.get(env_var, "")
    if not raw:
        return None
    return _hkdf_sha256(raw.encode(), info=b"sw-audit-trail")
