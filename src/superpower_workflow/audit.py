from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


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


class AuditTrail:
    def __init__(self, path: Path, key: bytes | None = None) -> None:
        self._path = path
        self._key = key
        self._seq = 0
        self._prev_hash = ""
        self._enabled = key is not None
        if self._enabled:
            self._load_last()

    def _load_last(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                if size == 0:
                    return
                chunk = min(size, 4096)
                f.seek(-chunk, 2)
                tail = f.read().decode("utf-8")
            for line in reversed(tail.splitlines()):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    self._seq = entry.get("seq", 0) + 1
                    self._prev_hash = entry.get("hash", "")
                    return
                except json.JSONDecodeError:
                    continue
        except OSError:
            return

    def append(
        self,
        event: str,
        run_id: str = "",
        milestone: str = "",
        data: dict | None = None,
    ) -> None:
        if not self._enabled:
            return
        entry = {
            "seq": self._seq,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "event": event,
            "run_id": run_id,
            "milestone": milestone,
            "data": data or {},
            "prev_hash": self._prev_hash,
        }
        canonical = _canonical_json(entry)
        entry["hash"] = _compute_hash(canonical, self._key)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")
        self._prev_hash = entry["hash"]
        self._seq += 1

    def verify(self) -> tuple[bool, int]:
        if not self._path.exists():
            return True, -1
        prev_hash = ""
        last_valid = -1
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                return False, last_valid
            if entry.get("prev_hash", "") != prev_hash:
                return False, last_valid
            canonical = _canonical_json(entry)
            computed = _compute_hash(canonical, self._key)
            if entry.get("hash", "") != computed:
                return False, last_valid
            prev_hash = entry["hash"]
            last_valid = entry.get("seq", last_valid)
        return True, last_valid

    @classmethod
    def disabled(cls) -> AuditTrail:
        return cls(Path(os.devnull), key=None)
