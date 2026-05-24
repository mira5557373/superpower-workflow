# SP4: Security & Compliance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add tamper-evident HMAC-chained audit trail, SBOM generation, Ed25519 signed artifacts, secrets broker, and configurable policy engine -- compliance guarantees for AI-generated code.

**Architecture:** Audit trail wraps every orchestrator action in a hash-chained JSONL log. Policy engine runs as an additional quality gate (same checkpoint as SP1). Signing and SBOM happen at milestone completion (Phase D, before git tag). Secrets broker injects env-var references into prompts without ever exposing values.

**Tech Stack:** Python 3.11+, `hmac` + `hashlib` (HMAC-SHA256, stdlib), `ast` (import/type-hint analysis), `json`, `subprocess`, `os`, `time`, `dataclasses`. Optional: `cryptography` for Ed25519 signing (`pip install superpower-workflow[security]`). Zero new required dependencies.

**Spec reference:** `docs/superpowers/specs/2026-05-24-sp4-security.md` (v1.0).

**Working directory:** `superpower-workflow/` (the repo root).

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/superpower_workflow/audit.py` | New | AuditEntry, derive_key, AuditTrail (HMAC chain, append, verify) |
| `src/superpower_workflow/security.py` | New | SecretsHandler, generate_sbom, sign_artifact, verify_signature |
| `src/superpower_workflow/policy.py` | New | PolicyEngine (load rules, check changed files) |
| `src/superpower_workflow/orchestrator.py` | Edit | Emit audit events, run policies, invoke signing/SBOM, inject secrets |
| `src/superpower_workflow/cli.py` | Edit | Add `sw audit verify` and `sw audit verify-sig` |
| `templates/workflow.json` | Edit | Add security, secrets, policies schema sections |
| `pyproject.toml` | Edit | Add `security` optional dependency group |
| `tests/test_audit.py` | New | Chain integrity, tamper detection, key derivation |
| `tests/test_security.py` | New | Secrets resolution, SBOM invocation, Ed25519 round-trip |
| `tests/test_policy.py` | New | Each policy rule, changed-files-only scoping |
| `tests/test_orchestrator.py` | Edit | Audit, secrets, policy, SBOM, signing integration |
| `tests/test_cli.py` | Edit | `sw audit verify` and `sw audit verify-sig` commands |

---

### Task 1: AuditEntry dataclass + canonical JSON + HMAC-SHA256 hash

**Files:**
- New: `src/superpower_workflow/audit.py`
- New: `tests/test_audit.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_audit.py
from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json

from superpower_workflow.audit import AuditEntry, _canonical_json, _compute_hash


class TestAuditEntry:
    def test_default_entry_has_seq_zero(self):
        e = AuditEntry(event="TEST")
        assert e.seq == 0

    def test_auto_timestamp(self):
        e = AuditEntry(event="TEST")
        assert e.timestamp != ""
        assert "T" in e.timestamp
        assert e.timestamp.endswith("Z")

    def test_explicit_fields(self):
        e = AuditEntry(
            seq=5,
            timestamp="2026-01-01T00:00:00Z",
            event="PHASE_COMPLETE",
            run_id="r1",
            milestone="m1",
            data={"phase": "B", "cost": 4.20},
            prev_hash="abc",
            hash="def",
        )
        assert e.seq == 5
        assert e.event == "PHASE_COMPLETE"
        assert e.data == {"phase": "B", "cost": 4.20}

    def test_to_dict(self):
        e = AuditEntry(event="TEST", run_id="r1")
        d = e.to_dict()
        assert d["event"] == "TEST"
        assert d["run_id"] == "r1"
        assert "seq" in d
        assert "hash" in d

    def test_to_dict_is_json_serializable(self):
        e = AuditEntry(event="TEST", data={"key": [1, 2, 3]})
        raw = json.dumps(e.to_dict())
        parsed = json.loads(raw)
        assert parsed["data"] == {"key": [1, 2, 3]}


class TestCanonicalJson:
    def test_excludes_hash_field(self):
        d = {"seq": 0, "event": "TEST", "hash": "abc123", "prev_hash": ""}
        canonical = _canonical_json(d)
        parsed = json.loads(canonical)
        assert "hash" not in parsed

    def test_keys_sorted(self):
        d = {"z_field": 1, "a_field": 2, "m_field": 3}
        canonical = _canonical_json(d)
        keys = list(json.loads(canonical).keys())
        assert keys == sorted(keys)

    def test_deterministic(self):
        d = {"seq": 0, "event": "TEST", "data": {"b": 2, "a": 1}, "prev_hash": ""}
        assert _canonical_json(d) == _canonical_json(d)

    def test_no_whitespace(self):
        d = {"seq": 0, "event": "TEST", "prev_hash": ""}
        canonical = _canonical_json(d)
        assert " " not in canonical


class TestComputeHash:
    def test_returns_hex_string(self):
        key = b"test-key-32-bytes-exactly-here!!"
        h = _compute_hash('{"event":"TEST","seq":0}', key)
        assert isinstance(h, str)
        assert len(h) == 64

    def test_deterministic(self):
        key = b"test-key-32-bytes-exactly-here!!"
        canonical = '{"event":"TEST","seq":0}'
        assert _compute_hash(canonical, key) == _compute_hash(canonical, key)

    def test_different_key_different_hash(self):
        c = '{"event":"TEST","seq":0}'
        h1 = _compute_hash(c, b"key-aaaaaaaaaaaaaaaaaaaaaaaaaaaa")
        h2 = _compute_hash(c, b"key-bbbbbbbbbbbbbbbbbbbbbbbbbbbb")
        assert h1 != h2

    def test_different_data_different_hash(self):
        key = b"test-key-32-bytes-exactly-here!!"
        h1 = _compute_hash('{"event":"A","seq":0}', key)
        h2 = _compute_hash('{"event":"B","seq":0}', key)
        assert h1 != h2

    def test_matches_stdlib_hmac(self):
        key = b"test-key-32-bytes-exactly-here!!"
        data = '{"event":"TEST","seq":0}'
        expected = hmac_mod.new(key, data.encode(), hashlib.sha256).hexdigest()
        assert _compute_hash(data, key) == expected
```

- [ ] **Step 2: Run tests — expect FAIL** (module doesn't exist)

- [ ] **Step 3: Create audit module with AuditEntry and hash primitives**

```python
# src/superpower_workflow/audit.py
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
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/audit.py tests/test_audit.py --fix
ruff format src/superpower_workflow/audit.py tests/test_audit.py
git add src/superpower_workflow/audit.py tests/test_audit.py
git commit -m "feat: add AuditEntry dataclass with HMAC-SHA256 hash primitives"
```

---

### Task 2: HKDF-SHA256 key derivation (stdlib-only)

**Files:**
- Modify: `src/superpower_workflow/audit.py`
- Modify: `tests/test_audit.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_audit.py — add imports and class
import os
from unittest.mock import patch

from superpower_workflow.audit import _hkdf_sha256, derive_key


class TestHkdfSha256:
    def test_returns_32_bytes(self):
        result = _hkdf_sha256(b"input-key-material", info=b"test")
        assert isinstance(result, bytes)
        assert len(result) == 32

    def test_deterministic(self):
        ikm = b"same-key"
        assert _hkdf_sha256(ikm, info=b"ctx") == _hkdf_sha256(ikm, info=b"ctx")

    def test_different_info_different_key(self):
        ikm = b"same-key"
        k1 = _hkdf_sha256(ikm, info=b"context-a")
        k2 = _hkdf_sha256(ikm, info=b"context-b")
        assert k1 != k2

    def test_different_ikm_different_key(self):
        k1 = _hkdf_sha256(b"key-a", info=b"ctx")
        k2 = _hkdf_sha256(b"key-b", info=b"ctx")
        assert k1 != k2

    def test_custom_salt(self):
        k1 = _hkdf_sha256(b"key", salt=b"salt-a" + b"\x00" * 26)
        k2 = _hkdf_sha256(b"key", salt=b"salt-b" + b"\x00" * 26)
        assert k1 != k2

    def test_default_salt_is_zeros(self):
        k1 = _hkdf_sha256(b"key", salt=b"")
        k2 = _hkdf_sha256(b"key", salt=b"\x00" * 32)
        assert k1 == k2


class TestDeriveKey:
    def test_returns_bytes_when_env_set(self):
        with patch.dict(os.environ, {"SW_AUDIT_KEY": "my-secret-key"}):
            key = derive_key()
        assert isinstance(key, bytes)
        assert len(key) == 32

    def test_returns_none_when_env_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            key = derive_key()
        assert key is None

    def test_custom_env_var_name(self):
        with patch.dict(os.environ, {"CUSTOM_KEY": "value"}):
            key = derive_key(env_var="CUSTOM_KEY")
        assert key is not None

    def test_deterministic_for_same_input(self):
        with patch.dict(os.environ, {"SW_AUDIT_KEY": "fixed"}):
            k1 = derive_key()
            k2 = derive_key()
        assert k1 == k2

    def test_different_env_values_different_keys(self):
        with patch.dict(os.environ, {"SW_AUDIT_KEY": "key-a"}):
            k1 = derive_key()
        with patch.dict(os.environ, {"SW_AUDIT_KEY": "key-b"}):
            k2 = derive_key()
        assert k1 != k2

    def test_empty_env_value_returns_none(self):
        with patch.dict(os.environ, {"SW_AUDIT_KEY": ""}):
            key = derive_key()
        assert key is None
```

- [ ] **Step 2: Run tests — expect FAIL** (functions don't exist)

- [ ] **Step 3: Implement HKDF and derive_key**

Add to `src/superpower_workflow/audit.py`:

```python
import os


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
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/audit.py tests/test_audit.py --fix
ruff format src/superpower_workflow/audit.py tests/test_audit.py
git add src/superpower_workflow/audit.py tests/test_audit.py
git commit -m "feat: add HKDF-SHA256 key derivation for audit trail (stdlib-only)"
```

---

### Task 3: AuditTrail.append() — chain-linked entry writing

**Files:**
- Modify: `src/superpower_workflow/audit.py`
- Modify: `tests/test_audit.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_audit.py — add class

from superpower_workflow.audit import AuditTrail


class TestAuditTrailAppend:
    def _key(self):
        return _hkdf_sha256(b"test-key", info=b"sw-audit-trail")

    def test_creates_file(self, tmp_path):
        path = tmp_path / "audit-trail.jsonl"
        trail = AuditTrail(path, key=self._key())
        trail.append("TEST_EVENT", run_id="r1")
        assert path.exists()

    def test_writes_valid_jsonl(self, tmp_path):
        path = tmp_path / "audit-trail.jsonl"
        trail = AuditTrail(path, key=self._key())
        trail.append("EVENT_A", run_id="r1")
        trail.append("EVENT_B", run_id="r1", milestone="m1")
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            parsed = json.loads(line)
            assert "seq" in parsed
            assert "hash" in parsed

    def test_seq_increments(self, tmp_path):
        path = tmp_path / "audit-trail.jsonl"
        trail = AuditTrail(path, key=self._key())
        trail.append("A")
        trail.append("B")
        trail.append("C")
        lines = [json.loads(l) for l in path.read_text().strip().split("\n")]
        assert lines[0]["seq"] == 0
        assert lines[1]["seq"] == 1
        assert lines[2]["seq"] == 2

    def test_chain_links_prev_hash(self, tmp_path):
        path = tmp_path / "audit-trail.jsonl"
        trail = AuditTrail(path, key=self._key())
        trail.append("A")
        trail.append("B")
        lines = [json.loads(l) for l in path.read_text().strip().split("\n")]
        assert lines[0]["prev_hash"] == ""
        assert lines[1]["prev_hash"] == lines[0]["hash"]

    def test_hash_is_valid_hex(self, tmp_path):
        path = tmp_path / "audit-trail.jsonl"
        trail = AuditTrail(path, key=self._key())
        trail.append("TEST")
        entry = json.loads(path.read_text().strip())
        assert len(entry["hash"]) == 64
        int(entry["hash"], 16)

    def test_data_field_stored(self, tmp_path):
        path = tmp_path / "audit-trail.jsonl"
        trail = AuditTrail(path, key=self._key())
        trail.append("TEST", data={"cost": 4.20, "phase": "B"})
        entry = json.loads(path.read_text().strip())
        assert entry["data"] == {"cost": 4.20, "phase": "B"}

    def test_appends_to_existing_file(self, tmp_path):
        path = tmp_path / "audit-trail.jsonl"
        trail = AuditTrail(path, key=self._key())
        trail.append("A")
        trail.append("B")
        trail2 = AuditTrail(path, key=self._key())
        trail2.append("C")
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 3
        entries = [json.loads(l) for l in lines]
        assert entries[2]["seq"] == 2
        assert entries[2]["prev_hash"] == entries[1]["hash"]

    def test_disabled_trail_writes_nothing(self, tmp_path):
        trail = AuditTrail.disabled()
        trail.append("TEST")

    def test_creates_parent_directory(self, tmp_path):
        path = tmp_path / "nested" / "dir" / "audit-trail.jsonl"
        trail = AuditTrail(path, key=self._key())
        trail.append("TEST")
        assert path.exists()
```

- [ ] **Step 2: Run tests — expect FAIL** (AuditTrail doesn't exist)

- [ ] **Step 3: Implement AuditTrail**

Add to `src/superpower_workflow/audit.py`:

```python
from pathlib import Path


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
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                self._seq = entry.get("seq", 0) + 1
                self._prev_hash = entry.get("hash", "")
            except json.JSONDecodeError:
                continue

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

    @classmethod
    def disabled(cls) -> AuditTrail:
        return cls(Path(os.devnull), key=None)
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/audit.py tests/test_audit.py --fix
ruff format src/superpower_workflow/audit.py tests/test_audit.py
git add src/superpower_workflow/audit.py tests/test_audit.py
git commit -m "feat: add AuditTrail with HMAC-chained append and file I/O"
```

---

### Task 4: AuditTrail.verify() — chain integrity verification

**Files:**
- Modify: `src/superpower_workflow/audit.py`
- Modify: `tests/test_audit.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_audit.py — add class


class TestAuditTrailVerify:
    def _key(self):
        return _hkdf_sha256(b"test-key", info=b"sw-audit-trail")

    def test_valid_chain(self, tmp_path):
        path = tmp_path / "audit-trail.jsonl"
        trail = AuditTrail(path, key=self._key())
        trail.append("A", run_id="r1")
        trail.append("B", run_id="r1")
        trail.append("C", run_id="r1")
        valid, last_seq = trail.verify()
        assert valid is True
        assert last_seq == 2

    def test_empty_file_is_valid(self, tmp_path):
        path = tmp_path / "audit-trail.jsonl"
        path.write_text("")
        trail = AuditTrail(path, key=self._key())
        valid, last_seq = trail.verify()
        assert valid is True
        assert last_seq == -1

    def test_missing_file_is_valid(self, tmp_path):
        path = tmp_path / "nonexistent.jsonl"
        trail = AuditTrail(path, key=self._key())
        valid, last_seq = trail.verify()
        assert valid is True
        assert last_seq == -1

    def test_tampered_hash_detected(self, tmp_path):
        path = tmp_path / "audit-trail.jsonl"
        trail = AuditTrail(path, key=self._key())
        trail.append("A")
        trail.append("B")
        lines = path.read_text().strip().split("\n")
        entry = json.loads(lines[0])
        entry["hash"] = "0" * 64
        lines[0] = json.dumps(entry)
        path.write_text("\n".join(lines) + "\n")
        valid, last_seq = AuditTrail(path, key=self._key()).verify()
        assert valid is False
        assert last_seq == -1

    def test_tampered_data_detected(self, tmp_path):
        path = tmp_path / "audit-trail.jsonl"
        trail = AuditTrail(path, key=self._key())
        trail.append("A", data={"cost": 10.0})
        trail.append("B")
        lines = path.read_text().strip().split("\n")
        entry = json.loads(lines[0])
        entry["data"]["cost"] = 0.0
        lines[0] = json.dumps(entry)
        path.write_text("\n".join(lines) + "\n")
        valid, last_seq = AuditTrail(path, key=self._key()).verify()
        assert valid is False
        assert last_seq == -1

    def test_broken_chain_link_detected(self, tmp_path):
        path = tmp_path / "audit-trail.jsonl"
        trail = AuditTrail(path, key=self._key())
        trail.append("A")
        trail.append("B")
        trail.append("C")
        lines = path.read_text().strip().split("\n")
        # Remove middle entry, breaking chain
        path.write_text(lines[0] + "\n" + lines[2] + "\n")
        valid, last_seq = AuditTrail(path, key=self._key()).verify()
        assert valid is False
        assert last_seq == 0

    def test_wrong_key_fails_verification(self, tmp_path):
        path = tmp_path / "audit-trail.jsonl"
        trail = AuditTrail(path, key=self._key())
        trail.append("A")
        wrong_key = _hkdf_sha256(b"wrong-key", info=b"sw-audit-trail")
        valid, _ = AuditTrail(path, key=wrong_key).verify()
        assert valid is False

    def test_single_entry_valid(self, tmp_path):
        path = tmp_path / "audit-trail.jsonl"
        trail = AuditTrail(path, key=self._key())
        trail.append("ONLY")
        valid, last_seq = trail.verify()
        assert valid is True
        assert last_seq == 0

    def test_malformed_json_fails(self, tmp_path):
        path = tmp_path / "audit-trail.jsonl"
        trail = AuditTrail(path, key=self._key())
        trail.append("A")
        with open(path, "a") as f:
            f.write("not-json\n")
        valid, last_seq = trail.verify()
        assert valid is False
        assert last_seq == 0
```

- [ ] **Step 2: Run tests — expect FAIL** (verify method doesn't exist)

- [ ] **Step 3: Implement verify**

Add to `AuditTrail` class in `audit.py`:

```python
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
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/audit.py tests/test_audit.py --fix
ruff format src/superpower_workflow/audit.py tests/test_audit.py
git add src/superpower_workflow/audit.py tests/test_audit.py
git commit -m "feat: add AuditTrail.verify() for chain integrity verification"
```

---

### Task 5: SecretsHandler — resolve, prompt_fragment, redact

**Files:**
- New: `src/superpower_workflow/security.py`
- New: `tests/test_security.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_security.py
from __future__ import annotations

import os
from unittest.mock import patch

from superpower_workflow.security import SecretsHandler


class TestSecretsHandlerResolve:
    def test_resolve_all_present(self):
        config = {"db_password": "DB_PASSWORD", "api_key": "API_KEY"}
        with patch.dict(os.environ, {"DB_PASSWORD": "secret1", "API_KEY": "secret2"}):
            handler = SecretsHandler(config)
            handler.resolve()

    def test_resolve_missing_env_var_raises(self):
        config = {"db_password": "MISSING_VAR"}
        with patch.dict(os.environ, {}, clear=True):
            handler = SecretsHandler(config)
            try:
                handler.resolve()
                assert False, "Should have raised"
            except ValueError as e:
                assert "MISSING_VAR" in str(e)

    def test_resolve_empty_config(self):
        handler = SecretsHandler({})
        handler.resolve()

    def test_resolve_partial_missing(self):
        config = {"a": "A_VAR", "b": "B_VAR"}
        with patch.dict(os.environ, {"A_VAR": "val"}, clear=True):
            handler = SecretsHandler(config)
            try:
                handler.resolve()
                assert False, "Should have raised"
            except ValueError as e:
                assert "B_VAR" in str(e)


class TestSecretsHandlerPromptFragment:
    def test_generates_fragment_for_each_secret(self):
        config = {"db_password": "DB_PASSWORD", "api_key": "API_KEY"}
        with patch.dict(os.environ, {"DB_PASSWORD": "s1", "API_KEY": "s2"}):
            handler = SecretsHandler(config)
            fragment = handler.prompt_fragment()
        assert "db_password" in fragment
        assert "$DB_PASSWORD" in fragment
        assert "api_key" in fragment
        assert "$API_KEY" in fragment

    def test_fragment_contains_never_hardcode(self):
        config = {"token": "TOKEN_VAR"}
        with patch.dict(os.environ, {"TOKEN_VAR": "abc"}):
            handler = SecretsHandler(config)
            fragment = handler.prompt_fragment()
        assert "NEVER" in fragment

    def test_actual_values_not_in_fragment(self):
        config = {"token": "TOKEN_VAR"}
        with patch.dict(os.environ, {"TOKEN_VAR": "super-secret-value-123"}):
            handler = SecretsHandler(config)
            fragment = handler.prompt_fragment()
        assert "super-secret-value-123" not in fragment

    def test_empty_config_returns_empty(self):
        handler = SecretsHandler({})
        assert handler.prompt_fragment() == ""


class TestSecretsHandlerRedact:
    def test_redacts_secret_values(self):
        config = {"db_password": "DB_PASSWORD"}
        with patch.dict(os.environ, {"DB_PASSWORD": "hunter2"}):
            handler = SecretsHandler(config)
            handler.resolve()
            result = handler.redact("password is hunter2 in config")
        assert "hunter2" not in result
        assert "[REDACTED]" in result

    def test_redacts_multiple_secrets(self):
        config = {"a": "A_VAR", "b": "B_VAR"}
        with patch.dict(os.environ, {"A_VAR": "alpha", "B_VAR": "beta"}):
            handler = SecretsHandler(config)
            handler.resolve()
            result = handler.redact("alpha and beta values")
        assert "alpha" not in result
        assert "beta" not in result

    def test_no_secrets_returns_unchanged(self):
        handler = SecretsHandler({})
        assert handler.redact("some text") == "some text"

    def test_redact_before_resolve_is_safe(self):
        config = {"token": "TOKEN"}
        with patch.dict(os.environ, {"TOKEN": "abc"}):
            handler = SecretsHandler(config)
            result = handler.redact("abc text")
        assert result == "abc text"
```

- [ ] **Step 2: Run tests — expect FAIL** (module doesn't exist)

- [ ] **Step 3: Implement SecretsHandler**

```python
# src/superpower_workflow/security.py
from __future__ import annotations

import os


class SecretsHandler:
    def __init__(self, config: dict) -> None:
        self._config = config
        self._resolved: dict[str, str] = {}

    def resolve(self) -> None:
        missing = []
        for logical_name, env_var in self._config.items():
            val = os.environ.get(env_var, "")
            if not val:
                missing.append(env_var)
            else:
                self._resolved[logical_name] = val
        if missing:
            raise ValueError(
                f"Missing required env vars for secrets: {', '.join(missing)}"
            )

    def prompt_fragment(self) -> str:
        if not self._config:
            return ""
        lines = []
        for logical_name, env_var in self._config.items():
            lines.append(f"Secret {logical_name} is in env var ${env_var}.")
        lines.append("Use env vars in code. NEVER hardcode secret values.")
        return "\n".join(lines)

    def redact(self, text: str) -> str:
        for value in self._resolved.values():
            if value:
                text = text.replace(value, "[REDACTED]")
        return text
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/security.py tests/test_security.py --fix
ruff format src/superpower_workflow/security.py tests/test_security.py
git add src/superpower_workflow/security.py tests/test_security.py
git commit -m "feat: add SecretsHandler with resolve, prompt_fragment, and redact"
```

---

### Task 6: PolicyEngine — max_file_lines + banned_imports

**Files:**
- New: `src/superpower_workflow/policy.py`
- New: `tests/test_policy.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_policy.py
from __future__ import annotations

from pathlib import Path

from superpower_workflow.policy import PolicyEngine


class TestMaxFileLines:
    def test_passes_when_under_limit(self, tmp_path):
        (tmp_path / "short.py").write_text("x = 1\ny = 2\n")
        engine = PolicyEngine({"max_file_lines": 100})
        passed, violations = engine.check(tmp_path, files=[tmp_path / "short.py"])
        assert passed is True
        assert violations == []

    def test_fails_when_over_limit(self, tmp_path):
        content = "\n".join(f"line_{i} = {i}" for i in range(101))
        (tmp_path / "long.py").write_text(content)
        engine = PolicyEngine({"max_file_lines": 100})
        passed, violations = engine.check(tmp_path, files=[tmp_path / "long.py"])
        assert passed is False
        assert any("long.py" in v for v in violations)
        assert any("101" in v or "100" in v for v in violations)

    def test_exactly_at_limit_passes(self, tmp_path):
        content = "\n".join(f"line_{i} = {i}" for i in range(100))
        (tmp_path / "exact.py").write_text(content)
        engine = PolicyEngine({"max_file_lines": 100})
        passed, _ = engine.check(tmp_path, files=[tmp_path / "exact.py"])
        assert passed is True

    def test_skipped_when_not_configured(self, tmp_path):
        content = "\n".join(f"line_{i} = {i}" for i in range(1000))
        (tmp_path / "huge.py").write_text(content)
        engine = PolicyEngine({})
        passed, _ = engine.check(tmp_path, files=[tmp_path / "huge.py"])
        assert passed is True


class TestBannedImports:
    def test_detects_banned_import(self, tmp_path):
        (tmp_path / "bad.py").write_text("import os\nos.system('rm -rf /')\n")
        engine = PolicyEngine({"banned_imports": ["os.system"]})
        passed, violations = engine.check(tmp_path, files=[tmp_path / "bad.py"])
        assert passed is False
        assert any("os.system" in v for v in violations)

    def test_detects_banned_from_import(self, tmp_path):
        (tmp_path / "bad.py").write_text("from subprocess import call\ncall('ls')\n")
        engine = PolicyEngine({"banned_imports": ["subprocess.call"]})
        passed, violations = engine.check(tmp_path, files=[tmp_path / "bad.py"])
        assert passed is False
        assert any("subprocess.call" in v for v in violations)

    def test_allows_non_banned_imports(self, tmp_path):
        (tmp_path / "good.py").write_text("import json\nimport pathlib\n")
        engine = PolicyEngine({"banned_imports": ["os.system"]})
        passed, _ = engine.check(tmp_path, files=[tmp_path / "good.py"])
        assert passed is True

    def test_skipped_when_not_configured(self, tmp_path):
        (tmp_path / "any.py").write_text("import os\nos.system('x')\n")
        engine = PolicyEngine({})
        passed, _ = engine.check(tmp_path, files=[tmp_path / "any.py"])
        assert passed is True

    def test_handles_syntax_error_gracefully(self, tmp_path):
        (tmp_path / "broken.py").write_text("def (\n")
        engine = PolicyEngine({"banned_imports": ["os.system"]})
        passed, _ = engine.check(tmp_path, files=[tmp_path / "broken.py"])
        assert passed is True

    def test_multiple_banned_in_same_file(self, tmp_path):
        code = "import os\nos.system('a')\nfrom subprocess import call\ncall('b')\n"
        (tmp_path / "multi.py").write_text(code)
        engine = PolicyEngine({"banned_imports": ["os.system", "subprocess.call"]})
        passed, violations = engine.check(tmp_path, files=[tmp_path / "multi.py"])
        assert passed is False
        assert len(violations) >= 2

    def test_non_python_files_skipped(self, tmp_path):
        (tmp_path / "data.txt").write_text("import os\nos.system('x')\n")
        engine = PolicyEngine({"banned_imports": ["os.system"]})
        passed, _ = engine.check(tmp_path, files=[tmp_path / "data.txt"])
        assert passed is True
```

- [ ] **Step 2: Run tests — expect FAIL** (module doesn't exist)

- [ ] **Step 3: Implement PolicyEngine with first two rules**

```python
# src/superpower_workflow/policy.py
from __future__ import annotations

import ast
from pathlib import Path


class PolicyEngine:
    def __init__(self, policies: dict) -> None:
        self._policies = policies

    def check(
        self,
        cwd: Path,
        files: list[Path] | None = None,
        base_sha: str | None = None,
    ) -> tuple[bool, list[str]]:
        if files is None:
            files = self._changed_files(cwd, base_sha)
        violations: list[str] = []
        max_lines = self._policies.get("max_file_lines")
        if max_lines is not None:
            violations.extend(self._check_max_file_lines(files, max_lines))
        banned = self._policies.get("banned_imports")
        if banned is not None:
            violations.extend(self._check_banned_imports(files, banned))
        return len(violations) == 0, violations

    def _changed_files(self, cwd: Path, base_sha: str | None) -> list[Path]:
        if not base_sha:
            return []
        import subprocess

        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", f"{base_sha}..HEAD"],
                capture_output=True,
                text=True,
                cwd=str(cwd),
                timeout=10,
            )
            if result.returncode != 0:
                return []
            return [cwd / f.strip() for f in result.stdout.splitlines() if f.strip()]
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return []

    def _check_max_file_lines(self, files: list[Path], max_lines: int) -> list[str]:
        violations: list[str] = []
        for f in files:
            if not f.exists() or not f.suffix == ".py":
                continue
            try:
                count = len(f.read_text(encoding="utf-8").splitlines())
                if count > max_lines:
                    violations.append(
                        f"max_file_lines: {f.name} has {count} lines (limit {max_lines})"
                    )
            except OSError:
                continue
        return violations

    def _check_banned_imports(self, files: list[Path], banned: list[str]) -> list[str]:
        violations: list[str] = []
        banned_set = set(banned)
        for f in files:
            if not f.exists() or f.suffix != ".py":
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
            except (SyntaxError, OSError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    for alias in node.names:
                        full = f"{node.module}.{alias.name}"
                        if full in banned_set:
                            violations.append(
                                f"banned_imports: {f.name} imports {full}"
                            )
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                    full = f"{node.value.id}.{node.attr}"
                    if full in banned_set:
                        violations.append(
                            f"banned_imports: {f.name} uses {full}"
                        )
        return violations
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/policy.py tests/test_policy.py --fix
ruff format src/superpower_workflow/policy.py tests/test_policy.py
git add src/superpower_workflow/policy.py tests/test_policy.py
git commit -m "feat: add PolicyEngine with max_file_lines and banned_imports checks"
```

---

### Task 7: PolicyEngine — required_license + require_type_hints

**Files:**
- Modify: `src/superpower_workflow/policy.py`
- Modify: `tests/test_policy.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_policy.py — add classes


class TestRequiredLicense:
    def test_passes_when_license_present(self, tmp_path):
        (tmp_path / "LICENSE").write_text("MIT License\n\nCopyright 2026...")
        engine = PolicyEngine({"required_license": "MIT"})
        passed, _ = engine.check(tmp_path, files=[])
        assert passed is True

    def test_fails_when_no_license_file(self, tmp_path):
        engine = PolicyEngine({"required_license": "MIT"})
        passed, violations = engine.check(tmp_path, files=[])
        assert passed is False
        assert any("LICENSE" in v for v in violations)

    def test_fails_when_wrong_license(self, tmp_path):
        (tmp_path / "LICENSE").write_text("Apache License 2.0\n...")
        engine = PolicyEngine({"required_license": "MIT"})
        passed, violations = engine.check(tmp_path, files=[])
        assert passed is False
        assert any("MIT" in v for v in violations)

    def test_checks_license_txt_variant(self, tmp_path):
        (tmp_path / "LICENSE.txt").write_text("MIT License\n...")
        engine = PolicyEngine({"required_license": "MIT"})
        passed, _ = engine.check(tmp_path, files=[])
        assert passed is True

    def test_skipped_when_not_configured(self, tmp_path):
        engine = PolicyEngine({})
        passed, _ = engine.check(tmp_path, files=[])
        assert passed is True


class TestRequireTypeHints:
    def test_passes_with_hints(self, tmp_path):
        code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        (tmp_path / "good.py").write_text(code)
        engine = PolicyEngine({"require_type_hints": True})
        passed, _ = engine.check(tmp_path, files=[tmp_path / "good.py"])
        assert passed is True

    def test_fails_without_return_hint(self, tmp_path):
        code = "def add(a: int, b: int):\n    return a + b\n"
        (tmp_path / "bad.py").write_text(code)
        engine = PolicyEngine({"require_type_hints": True})
        passed, violations = engine.check(tmp_path, files=[tmp_path / "bad.py"])
        assert passed is False
        assert any("add" in v for v in violations)

    def test_fails_without_arg_hints(self, tmp_path):
        code = "def add(a, b) -> int:\n    return a + b\n"
        (tmp_path / "bad.py").write_text(code)
        engine = PolicyEngine({"require_type_hints": True})
        passed, violations = engine.check(tmp_path, files=[tmp_path / "bad.py"])
        assert passed is False

    def test_skips_private_functions(self, tmp_path):
        code = "def _helper(x):\n    return x\n"
        (tmp_path / "priv.py").write_text(code)
        engine = PolicyEngine({"require_type_hints": True})
        passed, _ = engine.check(tmp_path, files=[tmp_path / "priv.py"])
        assert passed is True

    def test_skips_dunder_methods(self, tmp_path):
        code = "class A:\n    def __init__(self):\n        pass\n"
        (tmp_path / "cls.py").write_text(code)
        engine = PolicyEngine({"require_type_hints": True})
        passed, _ = engine.check(tmp_path, files=[tmp_path / "cls.py"])
        assert passed is True

    def test_allows_self_without_annotation(self, tmp_path):
        code = "class A:\n    def method(self, x: int) -> None:\n        pass\n"
        (tmp_path / "cls.py").write_text(code)
        engine = PolicyEngine({"require_type_hints": True})
        passed, _ = engine.check(tmp_path, files=[tmp_path / "cls.py"])
        assert passed is True

    def test_skipped_when_not_configured(self, tmp_path):
        code = "def add(a, b):\n    return a + b\n"
        (tmp_path / "any.py").write_text(code)
        engine = PolicyEngine({})
        passed, _ = engine.check(tmp_path, files=[tmp_path / "any.py"])
        assert passed is True

    def test_handles_syntax_error(self, tmp_path):
        (tmp_path / "broken.py").write_text("def (\n")
        engine = PolicyEngine({"require_type_hints": True})
        passed, _ = engine.check(tmp_path, files=[tmp_path / "broken.py"])
        assert passed is True


class TestChangedFilesScoping:
    def test_check_uses_changed_files_when_base_sha_provided(self, tmp_path):
        (tmp_path / "changed.py").write_text("\n".join(f"x{i}=1" for i in range(200)))
        (tmp_path / "unchanged.py").write_text("\n".join(f"x{i}=1" for i in range(200)))
        engine = PolicyEngine({"max_file_lines": 100})
        passed, violations = engine.check(
            tmp_path, files=[tmp_path / "changed.py"]
        )
        assert passed is False
        assert any("changed.py" in v for v in violations)
        assert not any("unchanged.py" in v for v in violations)
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement required_license and require_type_hints**

Add to `PolicyEngine.check()` in `policy.py`, after the banned_imports block:

```python
        license_id = self._policies.get("required_license")
        if license_id is not None:
            violations.extend(self._check_required_license(cwd, license_id))
        if self._policies.get("require_type_hints"):
            violations.extend(self._check_type_hints(files))
        return len(violations) == 0, violations
```

Add methods to `PolicyEngine`:

```python
    def _check_required_license(self, cwd: Path, spdx_id: str) -> list[str]:
        for name in ("LICENSE", "LICENSE.txt", "LICENSE.md", "LICENCE"):
            path = cwd / name
            if path.exists():
                content = path.read_text(encoding="utf-8", errors="replace")
                if spdx_id.upper() in content.upper():
                    return []
                return [
                    f"required_license: {name} does not contain '{spdx_id}'"
                ]
        return [f"required_license: no LICENSE file found (expected {spdx_id})"]

    def _check_type_hints(self, files: list[Path]) -> list[str]:
        violations: list[str] = []
        for f in files:
            if not f.exists() or f.suffix != ".py":
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
            except (SyntaxError, OSError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name.startswith("_"):
                    continue
                if node.returns is None:
                    violations.append(
                        f"require_type_hints: {f.name}:{node.name} missing return annotation"
                    )
                    continue
                for arg in node.args.args:
                    if arg.arg in ("self", "cls"):
                        continue
                    if arg.annotation is None:
                        violations.append(
                            f"require_type_hints: {f.name}:{node.name} "
                            f"param '{arg.arg}' missing annotation"
                        )
        return violations
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/policy.py tests/test_policy.py --fix
ruff format src/superpower_workflow/policy.py tests/test_policy.py
git add src/superpower_workflow/policy.py tests/test_policy.py
git commit -m "feat: add required_license and require_type_hints policy checks"
```

---

### Task 8: generate_sbom() — invoke configured SBOM tool

**Files:**
- Modify: `src/superpower_workflow/security.py`
- Modify: `tests/test_security.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_security.py — add imports and class
import json
import subprocess as subprocess_mod
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from superpower_workflow.security import generate_sbom


class TestGenerateSbom:
    def test_runs_configured_tool(self, tmp_path):
        calls = []

        def mock_run(cmd, **kwargs):
            calls.append(cmd)
            output = tmp_path / "sbom.json"
            output.write_text('{"bomFormat": "CycloneDX"}')
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("superpower_workflow.security.subprocess.run", side_effect=mock_run):
            ok, path = generate_sbom(
                tool_cmd="pip-audit --format=cyclonedx-json --output {output}",
                output_path=str(tmp_path / "sbom.json"),
                cwd=str(tmp_path),
            )
        assert ok is True
        assert len(calls) == 1
        assert "pip-audit" in calls[0]

    def test_returns_false_on_failure(self, tmp_path):
        fail = CompletedProcess(args=[], returncode=1, stdout="", stderr="err")
        with patch("superpower_workflow.security.subprocess.run", return_value=fail):
            ok, _ = generate_sbom(
                tool_cmd="bad-tool",
                output_path=str(tmp_path / "sbom.json"),
                cwd=str(tmp_path),
            )
        assert ok is False

    def test_returns_false_on_timeout(self, tmp_path):
        def mock_run(cmd, **kwargs):
            raise subprocess_mod.TimeoutExpired(cmd=cmd, timeout=300)

        with patch("superpower_workflow.security.subprocess.run", side_effect=mock_run):
            ok, _ = generate_sbom(
                tool_cmd="slow-tool",
                output_path=str(tmp_path / "sbom.json"),
                cwd=str(tmp_path),
            )
        assert ok is False

    def test_returns_false_on_missing_tool(self, tmp_path):
        def mock_run(cmd, **kwargs):
            raise FileNotFoundError("tool not found")

        with patch("superpower_workflow.security.subprocess.run", side_effect=mock_run):
            ok, _ = generate_sbom(
                tool_cmd="nonexistent",
                output_path=str(tmp_path / "sbom.json"),
                cwd=str(tmp_path),
            )
        assert ok is False

    def test_milestone_placeholder_in_output_path(self, tmp_path):
        calls = []

        def mock_run(cmd, **kwargs):
            calls.append(cmd)
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("superpower_workflow.security.subprocess.run", side_effect=mock_run):
            ok, path = generate_sbom(
                tool_cmd="pip-audit --format=cyclonedx-json --output {output}",
                output_path=str(tmp_path / "sbom-{milestone}.json"),
                cwd=str(tmp_path),
                milestone="auth-module",
            )
        assert "auth-module" in path

    def test_skipped_when_no_tool(self, tmp_path):
        ok, path = generate_sbom(
            tool_cmd="",
            output_path="",
            cwd=str(tmp_path),
        )
        assert ok is True
        assert path == ""
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement generate_sbom**

Add to `src/superpower_workflow/security.py`:

```python
import shlex
import subprocess
from pathlib import Path


def generate_sbom(
    tool_cmd: str,
    output_path: str,
    cwd: str,
    milestone: str = "",
) -> tuple[bool, str]:
    if not tool_cmd:
        return True, ""
    resolved_path = output_path.replace("{milestone}", milestone)
    expanded = tool_cmd.replace("{output}", resolved_path)
    try:
        result = subprocess.run(
            shlex.split(expanded),
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=300,
        )
        return result.returncode == 0, resolved_path
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return False, resolved_path
```

> **Note:** The tool_cmd uses `{output}` placeholder for the output path (e.g., `"pip-audit --format=cyclonedx-json --output {output}"`). This avoids hardcoding any single tool's output flag and uses `shlex.split` instead of `shell=True` to prevent command injection.

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/security.py tests/test_security.py --fix
ruff format src/superpower_workflow/security.py tests/test_security.py
git add src/superpower_workflow/security.py tests/test_security.py
git commit -m "feat: add generate_sbom for CycloneDX SBOM generation"
```

---

### Task 9: sign_artifact() + verify_signature() — Ed25519 (optional dep)

**Files:**
- Modify: `src/superpower_workflow/security.py`
- Modify: `tests/test_security.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_security.py — add class
from superpower_workflow.security import HAS_CRYPTO, sign_artifact, verify_signature


class TestSignArtifact:
    def test_skipped_when_no_key(self, tmp_path):
        with patch.dict(os.environ, {}, clear=True):
            sig = sign_artifact(tag="v1.0", cwd=str(tmp_path))
        assert sig is None

    def test_skipped_when_no_crypto(self, tmp_path):
        with (
            patch("superpower_workflow.security.HAS_CRYPTO", False),
            patch.dict(os.environ, {"SW_SIGN_KEY": "a" * 64}),
        ):
            sig = sign_artifact(tag="v1.0", cwd=str(tmp_path))
        assert sig is None

    def test_sign_and_verify_roundtrip(self, tmp_path):
        if not HAS_CRYPTO:
            return

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        private_key = Ed25519PrivateKey.generate()
        key_bytes = private_key.private_bytes_raw()
        key_hex = key_bytes.hex()
        pub_hex = private_key.public_key().public_bytes_raw().hex()

        tree_hash = "abc123def456"

        def mock_run(cmd, **kwargs):
            if isinstance(cmd, list) and "rev-parse" in cmd:
                return CompletedProcess(
                    args=cmd, returncode=0, stdout=f"{tree_hash}\n", stderr=""
                )
            if isinstance(cmd, list) and "notes" in cmd and "add" in cmd:
                return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if isinstance(cmd, list) and "notes" in cmd and "show" in cmd:
                sig = sign_result[0]
                return CompletedProcess(
                    args=cmd, returncode=0, stdout=f"sig:{sig}\n", stderr=""
                )
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        sign_result = [None]
        original_run = subprocess_mod.run

        def capture_run(cmd, **kwargs):
            r = mock_run(cmd, **kwargs)
            if isinstance(cmd, list) and "notes" in cmd and "add" in cmd:
                for arg in cmd:
                    if arg.startswith("sig:"):
                        sign_result[0] = arg.removeprefix("sig:")
            return r

        with (
            patch.dict(os.environ, {"SW_SIGN_KEY": key_hex}),
            patch("superpower_workflow.security.subprocess.run", side_effect=capture_run),
        ):
            sig = sign_artifact(tag="v1.0", cwd=str(tmp_path))

        assert sig is not None
        assert sign_result[0] is not None

        with (
            patch.dict(os.environ, {}),
            patch("superpower_workflow.security.subprocess.run", side_effect=mock_run),
        ):
            valid = verify_signature(
                tag="v1.0", public_key_hex=pub_hex, cwd=str(tmp_path)
            )

        assert valid is True

    def test_verify_returns_false_on_bad_sig(self, tmp_path):
        if not HAS_CRYPTO:
            return

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        pub_hex = Ed25519PrivateKey.generate().public_key().public_bytes_raw().hex()

        def mock_run(cmd, **kwargs):
            if isinstance(cmd, list) and "rev-parse" in cmd:
                return CompletedProcess(
                    args=cmd, returncode=0, stdout="abc123\n", stderr=""
                )
            if isinstance(cmd, list) and "notes" in cmd and "show" in cmd:
                return CompletedProcess(
                    args=cmd, returncode=0, stdout="sig:" + "ff" * 64 + "\n", stderr=""
                )
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("superpower_workflow.security.subprocess.run", side_effect=mock_run):
            valid = verify_signature(
                tag="v1.0", public_key_hex=pub_hex, cwd=str(tmp_path)
            )
        assert valid is False

    def test_verify_returns_false_when_no_note(self, tmp_path):
        if not HAS_CRYPTO:
            return

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        pub_hex = Ed25519PrivateKey.generate().public_key().public_bytes_raw().hex()

        def mock_run(cmd, **kwargs):
            if isinstance(cmd, list) and "notes" in cmd:
                return CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")
            return CompletedProcess(args=cmd, returncode=0, stdout="abc\n", stderr="")

        with patch("superpower_workflow.security.subprocess.run", side_effect=mock_run):
            valid = verify_signature(
                tag="v1.0", public_key_hex=pub_hex, cwd=str(tmp_path)
            )
        assert valid is False
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Implement sign_artifact and verify_signature**

Add to `src/superpower_workflow/security.py`:

```python
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )

    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


def sign_artifact(tag: str, cwd: str) -> str | None:
    if not HAS_CRYPTO:
        return None
    key_hex = os.environ.get("SW_SIGN_KEY", "")
    if not key_hex:
        return None
    try:
        private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(key_hex))
    except (ValueError, TypeError):
        return None
    try:
        tree_result = subprocess.run(
            ["git", "rev-parse", f"{tag}^{{tree}}"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=10,
        )
        if tree_result.returncode != 0:
            return None
        tree_hash = tree_result.stdout.strip()
        signature = private_key.sign(tree_hash.encode())
        sig_hex = signature.hex()
        note_result = subprocess.run(
            ["git", "notes", "add", "-f", "-m", f"sig:{sig_hex}", tag],
            capture_output=True,
            cwd=cwd,
            timeout=10,
        )
        if note_result.returncode != 0:
            return None
        return sig_hex
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def verify_signature(tag: str, public_key_hex: str, cwd: str) -> bool:
    if not HAS_CRYPTO:
        return False
    try:
        public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
    except (ValueError, TypeError):
        return False
    note_result = subprocess.run(
        ["git", "notes", "show", tag],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=10,
    )
    if note_result.returncode != 0:
        return False
    note = note_result.stdout.strip()
    if not note.startswith("sig:"):
        return False
    sig_hex = note.removeprefix("sig:")
    tree_result = subprocess.run(
        ["git", "rev-parse", f"{tag}^{{tree}}"],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=10,
    )
    if tree_result.returncode != 0:
        return False
    tree_hash = tree_result.stdout.strip()
    try:
        public_key.verify(bytes.fromhex(sig_hex), tree_hash.encode())
        return True
    except Exception:
        return False
```

Update `pyproject.toml` optional dependencies:

```toml
[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.5"]
security = ["cryptography>=42.0"]
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/security.py tests/test_security.py --fix
ruff format src/superpower_workflow/security.py tests/test_security.py
git add src/superpower_workflow/security.py tests/test_security.py pyproject.toml
git commit -m "feat: add Ed25519 artifact signing with optional cryptography dep"
```

---

### Task 10: Integrate AuditTrail into Orchestrator.run()

**Files:**
- Modify: `src/superpower_workflow/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_orchestrator.py — add imports and helpers
import os as os_mod
from superpower_workflow.audit import AuditTrail, _hkdf_sha256


def _read_audit_trail(tmp_path):
    path = tmp_path / ".claude" / "audit-trail.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().strip().split("\n") if line.strip()]


def _config_with_security(tmp_path, security=None, gates=None):
    config = _config(tmp_path)
    config["security"] = security or {"audit_trail": True}
    if gates:
        config["quality_gates"] = gates
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))
    return config


# Add class:
class TestAuditTrailIntegration:
    def test_audit_trail_created_when_enabled(self, tmp_path):
        _config_with_security(tmp_path)
        with (
            patch.dict(os_mod.environ, {"SW_AUDIT_KEY": "test-key"}),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        trail = _read_audit_trail(tmp_path)
        assert len(trail) > 0

    def test_audit_trail_has_run_events(self, tmp_path):
        _config_with_security(tmp_path)
        with (
            patch.dict(os_mod.environ, {"SW_AUDIT_KEY": "test-key"}),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        trail = _read_audit_trail(tmp_path)
        events = [e["event"] for e in trail]
        assert "RUN_START" in events
        assert "RUN_COMPLETE" in events

    def test_audit_trail_has_milestone_events(self, tmp_path):
        _config_with_security(tmp_path)
        with (
            patch.dict(os_mod.environ, {"SW_AUDIT_KEY": "test-key"}),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        trail = _read_audit_trail(tmp_path)
        events = [e["event"] for e in trail]
        assert "MILESTONE_START" in events
        assert "MILESTONE_COMPLETE" in events

    def test_audit_trail_has_phase_events(self, tmp_path):
        _config_with_security(tmp_path)
        with (
            patch.dict(os_mod.environ, {"SW_AUDIT_KEY": "test-key"}),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        trail = _read_audit_trail(tmp_path)
        events = [e["event"] for e in trail]
        assert "PHASE_COMPLETE" in events

    def test_audit_chain_verifies(self, tmp_path):
        _config_with_security(tmp_path)
        key = _hkdf_sha256(b"test-key", info=b"sw-audit-trail")
        with (
            patch.dict(os_mod.environ, {"SW_AUDIT_KEY": "test-key"}),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        audit_path = tmp_path / ".claude" / "audit-trail.jsonl"
        trail = AuditTrail(audit_path, key=key)
        valid, _ = trail.verify()
        assert valid is True

    def test_no_audit_when_disabled(self, tmp_path):
        _config_with_security(tmp_path, security={"audit_trail": False})
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        assert not (tmp_path / ".claude" / "audit-trail.jsonl").exists()

    def test_no_audit_when_no_security_section(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        assert not (tmp_path / ".claude" / "audit-trail.jsonl").exists()

    def test_no_audit_when_key_missing(self, tmp_path):
        _config_with_security(tmp_path)
        with (
            patch.dict(os_mod.environ, {}, clear=True),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        assert not (tmp_path / ".claude" / "audit-trail.jsonl").exists()
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Wire AuditTrail into Orchestrator**

Add import at top of `orchestrator.py`:

```python
from superpower_workflow.audit import AuditTrail, derive_key
```

Add to `Orchestrator.__init__`:

```python
self._audit = AuditTrail.disabled()
```

In `Orchestrator.run()`, after telemetry setup and before the milestone loop, add:

```python
security_config = self.config.get("security", {})
if security_config.get("audit_trail", False):
    audit_key = derive_key()
    if audit_key:
        audit_path = Path(self.cwd) / ".claude" / "audit-trail.jsonl"
        self._audit = AuditTrail(audit_path, key=audit_key)
    else:
        self._audit = AuditTrail.disabled()
else:
    self._audit = AuditTrail.disabled()

self._audit.append("RUN_START", run_id=run_id, data={
    "model": self.config["model"],
    "milestone_count": len(milestones),
})
```

After `logger.log("MILESTONE_START", ...)`:

```python
self._audit.append("MILESTONE_START", run_id=run_id, milestone=name)
```

After `logger.log("MILESTONE_COMPLETE", ...)`:

```python
self._audit.append("MILESTONE_COMPLETE", run_id=run_id, milestone=name, data={
    "cost": round(cost, 2),
})
```

In `_run_milestone`, after each `logger.log("PHASE_X_COMPLETE", ...)`, add:

```python
self._audit.append("PHASE_COMPLETE", run_id=self.state.run_id, milestone=name, data={
    "phase": "plan",  # or "implement", "review", "push"
    "cost": round(r.cost_usd, 2),
})
```

In `_completion_notification`, before the summary write:

```python
self._audit.append("RUN_COMPLETE", run_id=self.state.run_id, data={
    "status": status,
    "completed": len(self.state.completed),
    "cost": round(self.state.total_cost_usd, 2),
})
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py --fix
ruff format src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: integrate HMAC-chained audit trail into orchestrator lifecycle"
```

---

### Task 11: Integrate SecretsHandler into Orchestrator prompts

**Files:**
- Modify: `src/superpower_workflow/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_orchestrator.py — add class


def _config_with_secrets(tmp_path, secrets=None):
    config = _config(tmp_path)
    config["secrets"] = secrets or {"db_password": "DB_PASS"}
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))
    return config


class TestSecretsIntegration:
    def test_secrets_fragment_in_system_prompt(self, tmp_path):
        _config_with_secrets(tmp_path)
        prompts = []

        def mock_run_claude(prompt, **kwargs):
            prompts.append(kwargs.get("system_prompt", ""))
            return _ok_result()

        with (
            patch.dict(os_mod.environ, {"DB_PASS": "hunter2"}),
            patch("superpower_workflow.orchestrator.run_claude", side_effect=mock_run_claude),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        assert any("$DB_PASS" in p for p in prompts)
        assert not any("hunter2" in p for p in prompts)

    def test_no_secrets_section_works(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed

    def test_missing_env_var_warns_and_continues(self, tmp_path, capsys):
        _config_with_secrets(tmp_path)
        with (
            patch.dict(os_mod.environ, {}, clear=True),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        captured = capsys.readouterr()
        assert "Warning" in captured.out or "m1" in load_state(tmp_path / ".claude").completed
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Wire SecretsHandler into Orchestrator**

Add import at top of `orchestrator.py`:

```python
from superpower_workflow.security import SecretsHandler
```

In `Orchestrator.__init__`, after `self.sys_prompt = system_prompt()`:

```python
secrets_config = self.config.get("secrets", {})
if secrets_config:
    self._secrets = SecretsHandler(secrets_config)
    try:
        self._secrets.resolve()
    except ValueError as e:
        print(f"  Warning: {e}")
        self._secrets = SecretsHandler({})
    fragment = self._secrets.prompt_fragment()
    if fragment:
        self.sys_prompt = self.sys_prompt + "\n\n" + fragment
else:
    self._secrets = SecretsHandler({})
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py --fix
ruff format src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: integrate SecretsHandler into orchestrator system prompt"
```

---

### Task 12: Integrate PolicyEngine into quality gate checkpoints

**Files:**
- Modify: `src/superpower_workflow/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_orchestrator.py — add class


def _config_with_policies(tmp_path, policies=None):
    config = _config(tmp_path)
    config["policies"] = policies or {"max_file_lines": 500}
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))
    return config


class TestPolicyIntegration:
    def test_policy_check_runs_at_checkpoints(self, tmp_path):
        _config_with_policies(tmp_path, policies={"max_file_lines": 500})
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed

    def test_policy_violation_triggers_fix(self, tmp_path):
        _config_with_policies(tmp_path, policies={"banned_imports": ["os.system"]})
        prompts = []
        call_count = {"n": 0}

        def mock_run_claude(prompt, **kwargs):
            call_count["n"] += 1
            prompts.append(prompt)
            if call_count["n"] == 2:
                bad_file = tmp_path / "src" / "bad.py"
                bad_file.parent.mkdir(parents=True, exist_ok=True)
                bad_file.write_text("import json\n")
            return _ok_result()

        bad_file = tmp_path / "src" / "bad.py"
        bad_file.parent.mkdir(parents=True, exist_ok=True)
        bad_file.write_text("import os\nos.system('ls')\n")

        def mock_subprocess(cmd, **kwargs):
            if isinstance(cmd, list) and "diff" in cmd and "--name-only" in cmd:
                return CompletedProcess(
                    args=cmd, returncode=0, stdout="src/bad.py\n", stderr=""
                )
            return _smart_subprocess(cmd, **kwargs)

        with (
            patch(
                "superpower_workflow.orchestrator.run_claude",
                side_effect=mock_run_claude,
            ),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=mock_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        fix_prompts = [p for p in prompts if "Policy" in p or "policy" in p]
        assert len(fix_prompts) >= 1

    def test_no_policies_section_works(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Wire PolicyEngine into quality gate checkpoints**

Add import at top of `orchestrator.py`:

```python
from superpower_workflow.policy import PolicyEngine
```

Add new method to `Orchestrator`:

```python
def _check_policies(
    self,
    logger: WorkflowLogger,
    milestone: str = "",
    checkpoint: str = "",
) -> tuple[bool, list[str]]:
    policies_config = self.config.get("policies", {})
    if not policies_config:
        return True, []
    engine = PolicyEngine(policies_config)
    base_sha = self.state.plan_commit_sha or ""
    passed, violations = engine.check(Path(self.cwd), base_sha=base_sha)
    for v in violations:
        logger.log("POLICY_VIOLATION", checkpoint=checkpoint, detail=v)
        self._audit.append(
            "POLICY_VIOLATION",
            run_id=self.state.run_id,
            milestone=milestone,
            data={"checkpoint": checkpoint, "violation": v},
        )
    if passed:
        logger.log("POLICY_CHECK_PASSED", checkpoint=checkpoint)
    return passed, violations
```

In `_run_milestone`, after each `_verify_quality_gates` call (at both checkpoints), add:

```python
policy_passed, policy_violations = self._check_policies(
    logger, milestone=name, checkpoint="quality_check_b"  # or "quality_check_c"
)
if not policy_passed:
    fix_prompt = (
        f"Policy violations after {name}:\n"
        + "\n".join(f"- {v}" for v in policy_violations)
        + "\nFix ALL violations. Commit the fix."
    )
    r = run_claude(
        fix_prompt,
        model=model,
        effort="high",
        budget=10.0,
        cwd=self.cwd,
        system_prompt=self.sys_prompt,
        fallback_model=fallback,
    )
    cost += r.cost_usd
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py --fix
ruff format src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: integrate PolicyEngine into quality gate checkpoints"
```

---

### Task 13: Integrate SBOM generation + artifact signing into Phase D

**Files:**
- Modify: `src/superpower_workflow/orchestrator.py`
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_orchestrator.py — add class


class TestSbomAndSigningIntegration:
    def test_sbom_generated_in_phase_d(self, tmp_path):
        config = _config(tmp_path)
        config["security"] = {
            "audit_trail": False,
            "sbom_tool": "echo sbom",
            "sbom_output": ".claude/sbom-{milestone}.json",
        }
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))
        sbom_calls = []

        def mock_subprocess(cmd, **kwargs):
            if isinstance(cmd, str) and "sbom" in cmd:
                sbom_calls.append(cmd)
                return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if isinstance(cmd, str):
                return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            return _smart_subprocess(cmd, **kwargs)

        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=mock_subprocess,
            ),
            patch("superpower_workflow.security.subprocess.run", side_effect=mock_subprocess),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        assert len(sbom_calls) >= 1

    def test_signing_called_in_phase_d(self, tmp_path):
        if not __import__("superpower_workflow.security", fromlist=["HAS_CRYPTO"]).HAS_CRYPTO:
            return
        config = _config(tmp_path)
        config["security"] = {
            "audit_trail": False,
            "sign_artifacts": True,
        }
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        key_hex = Ed25519PrivateKey.generate().private_bytes_raw().hex()

        note_calls = []

        def mock_subprocess(cmd, **kwargs):
            if isinstance(cmd, list) and "notes" in cmd:
                note_calls.append(cmd)
            return _smart_subprocess(cmd, **kwargs)

        with (
            patch.dict(os_mod.environ, {"SW_SIGN_KEY": key_hex}),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=mock_subprocess,
            ),
            patch("superpower_workflow.security.subprocess.run", side_effect=mock_subprocess),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        assert any("notes" in str(c) for c in note_calls)

    def test_no_security_config_skips_both(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Add SBOM + signing to Phase D in _run_milestone**

Add import at top of `orchestrator.py`:

```python
from superpower_workflow.security import generate_sbom, sign_artifact
```

In `_run_milestone`, after Phase D's `logger.log("PHASE_D_COMPLETE", ...)`, before `return cost`:

```python
# SBOM generation
security = self.config.get("security", {})
sbom_tool = security.get("sbom_tool", "")
sbom_output = security.get("sbom_output", "")
if sbom_tool:
    ok, sbom_path = generate_sbom(
        tool_cmd=sbom_tool,
        output_path=sbom_output,
        cwd=self.cwd,
        milestone=name,
    )
    if ok and sbom_path:
        logger.log("SBOM_GENERATED", milestone=name, path=sbom_path)
        self._audit.append(
            "SBOM_GENERATED",
            run_id=self.state.run_id,
            milestone=name,
            data={"path": sbom_path},
        )
    else:
        logger.log("SBOM_FAILED", milestone=name)

# Artifact signing
if security.get("sign_artifacts", False):
    tag = name
    sig = sign_artifact(tag=tag, cwd=self.cwd)
    if sig:
        logger.log("ARTIFACT_SIGNED", milestone=name)
        self._audit.append(
            "ARTIFACT_SIGNED",
            run_id=self.state.run_id,
            milestone=name,
            data={"tag": tag},
        )
    else:
        logger.log("SIGNING_SKIPPED", milestone=name)
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py --fix
ruff format src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: integrate SBOM generation and artifact signing into Phase D"
```

---

### Task 14: CLI — `sw audit verify` + `sw audit verify-sig`

**Files:**
- Modify: `src/superpower_workflow/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli.py — add imports and tests
from superpower_workflow.cli import build_parser


def test_parser_audit_verify_command():
    parser = build_parser()
    args = parser.parse_args(["audit", "verify"])
    assert args.command == "audit"
    assert args.audit_command == "verify"


def test_parser_audit_verify_sig_command():
    parser = build_parser()
    args = parser.parse_args(["audit", "verify-sig", "v1.0"])
    assert args.command == "audit"
    assert args.audit_command == "verify-sig"
    assert args.tag == "v1.0"


def test_parser_audit_verify_sig_with_key():
    parser = build_parser()
    args = parser.parse_args(["audit", "verify-sig", "v1.0", "--public-key", "abc"])
    assert args.public_key == "abc"


def test_audit_verify_no_trail(tmp_path, capsys):
    from superpower_workflow.cli import _cmd_audit_verify

    _cmd_audit_verify(tmp_path)
    captured = capsys.readouterr()
    assert "No audit trail" in captured.out or "valid" in captured.out.lower()


def test_audit_verify_valid_chain(tmp_path, capsys):
    from superpower_workflow.audit import AuditTrail, _hkdf_sha256
    from superpower_workflow.cli import _cmd_audit_verify

    key = _hkdf_sha256(b"test-key", info=b"sw-audit-trail")
    path = tmp_path / ".claude" / "audit-trail.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    trail = AuditTrail(path, key=key)
    trail.append("A")
    trail.append("B")

    with patch.dict(os.environ, {"SW_AUDIT_KEY": "test-key"}):
        _cmd_audit_verify(tmp_path)
    captured = capsys.readouterr()
    assert "valid" in captured.out.lower() or "OK" in captured.out


def test_audit_verify_tampered_chain(tmp_path, capsys):
    from superpower_workflow.audit import AuditTrail, _hkdf_sha256
    from superpower_workflow.cli import _cmd_audit_verify

    key = _hkdf_sha256(b"test-key", info=b"sw-audit-trail")
    path = tmp_path / ".claude" / "audit-trail.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    trail = AuditTrail(path, key=key)
    trail.append("A")
    trail.append("B")
    # Tamper
    lines = path.read_text().strip().split("\n")
    entry = json.loads(lines[0])
    entry["data"] = {"tampered": True}
    lines[0] = json.dumps(entry)
    path.write_text("\n".join(lines) + "\n")

    with patch.dict(os.environ, {"SW_AUDIT_KEY": "test-key"}):
        _cmd_audit_verify(tmp_path)
    captured = capsys.readouterr()
    assert "INVALID" in captured.out or "tamper" in captured.out.lower()
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Add audit subcommand to CLI**

In `cli.py`, add the subparser in `build_parser()`:

```python
    audit_p = sub.add_parser("audit", help="Audit trail commands")
    audit_sub = audit_p.add_subparsers(dest="audit_command")
    audit_sub.add_parser("verify", help="Verify audit trail chain integrity")
    sig_p = audit_sub.add_parser("verify-sig", help="Verify artifact signature")
    sig_p.add_argument("tag", help="Git tag to verify")
    sig_p.add_argument("--public-key", help="Ed25519 public key (hex)")
```

Add the handler functions:

```python
def _cmd_audit_verify(project_root: Path) -> None:
    from superpower_workflow.audit import AuditTrail, derive_key

    audit_path = project_root / ".claude" / "audit-trail.jsonl"
    if not audit_path.exists():
        print("  No audit trail found.")
        return
    key = derive_key()
    if not key:
        print("  Error: SW_AUDIT_KEY not set. Cannot verify.")
        return
    trail = AuditTrail(audit_path, key=key)
    valid, last_seq = trail.verify()
    if valid:
        print(f"  Audit trail OK. {last_seq + 1} entries verified.")
    else:
        print(f"  INVALID: chain broken after seq {last_seq}. Possible tampering.")


def _cmd_audit_verify_sig(project_root: Path, tag: str, public_key: str | None) -> None:
    from superpower_workflow.security import verify_signature

    if not public_key:
        config_path = project_root / ".claude" / "workflow.json"
        if config_path.exists():
            try:
                config = json.loads(config_path.read_text())
                public_key = config.get("security", {}).get("public_key", "")
            except (json.JSONDecodeError, OSError):
                pass
    if not public_key:
        print("  Error: No public key. Use --public-key or set security.public_key in config.")
        return
    valid = verify_signature(tag=tag, public_key_hex=public_key, cwd=str(project_root))
    if valid:
        print(f"  Signature valid for {tag}.")
    else:
        print(f"  Signature INVALID or missing for {tag}.")
```

Wire into `main()`:

```python
    if args.command == "audit":
        if args.audit_command == "verify":
            _cmd_audit_verify(project_root)
        elif args.audit_command == "verify-sig":
            _cmd_audit_verify_sig(
                project_root,
                tag=args.tag,
                public_key=getattr(args, "public_key", None),
            )
        else:
            parser.parse_args(["audit", "--help"])
        return
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/cli.py tests/test_cli.py --fix
ruff format src/superpower_workflow/cli.py tests/test_cli.py
git add src/superpower_workflow/cli.py tests/test_cli.py
git commit -m "feat: add sw audit verify and sw audit verify-sig CLI commands"
```

---

### Task 15: Config — security/secrets/policies in workflow.json + _cmd_init + gitignore

**Files:**
- Modify: `src/superpower_workflow/cli.py`
- Modify: `templates/workflow.json`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_cli.py — add tests


def test_init_config_has_security_section(tmp_path):
    from superpower_workflow.cli import _cmd_init

    _cmd_init(tmp_path)
    config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    assert "security" in config
    assert config["security"]["audit_trail"] is False
    assert config["security"]["sign_artifacts"] is False


def test_init_config_has_policies_section(tmp_path):
    from superpower_workflow.cli import _cmd_init

    _cmd_init(tmp_path)
    config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    assert "policies" in config
    assert config["policies"] == {}


def test_init_config_has_secrets_section(tmp_path):
    from superpower_workflow.cli import _cmd_init

    _cmd_init(tmp_path)
    config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    assert "secrets" in config
    assert config["secrets"] == {}


def test_init_audit_trail_in_gitignore(tmp_path):
    from superpower_workflow.cli import _cmd_init

    _cmd_init(tmp_path)
    gitignore = (tmp_path / ".gitignore").read_text()
    assert "audit-trail.jsonl" in gitignore
```

- [ ] **Step 2: Run tests — expect FAIL**

- [ ] **Step 3: Add security config sections**

In `cli.py`, update the `default_config` dict in `_cmd_init`:

After the `"dashboard"` key, add:

```python
        "security": {
            "audit_trail": False,
            "sign_artifacts": False,
            "sbom_tool": "",
            "sbom_output": ".claude/sbom-{milestone}.json",
            "public_key": "",
        },
        "secrets": {},
        "policies": {},
```

Add to the `entries` list in `_cmd_init`:

```python
        ".claude/audit-trail.jsonl",
```

Update `templates/workflow.json` — add after the `"dashboard"` section:

```json
  "security": {
    "audit_trail": false,
    "sign_artifacts": false,
    "sbom_tool": "",
    "sbom_output": ".claude/sbom-{milestone}.json",
    "public_key": ""
  },
  "secrets": {},
  "policies": {},
```

- [ ] **Step 4: Run tests — expect PASS**
- [ ] **Step 5: Lint + commit**

```bash
ruff check src/superpower_workflow/cli.py templates/ tests/test_cli.py --fix
ruff format src/superpower_workflow/cli.py tests/test_cli.py
git add src/superpower_workflow/cli.py templates/workflow.json tests/test_cli.py
git commit -m "feat: add security, secrets, and policies config sections"
```

---

### Task 16: Full integration tests + backward compatibility + test suite verification

**Files:**
- Modify: `tests/test_orchestrator.py`

- [ ] **Step 1: Write integration tests**

```python
# tests/test_orchestrator.py — add class


class TestSP4Integration:
    def test_full_run_with_all_security_features(self, tmp_path):
        config = _config(tmp_path)
        config["security"] = {
            "audit_trail": True,
            "sign_artifacts": False,
            "sbom_tool": "",
        }
        config["secrets"] = {"token": "MY_TOKEN"}
        config["policies"] = {"max_file_lines": 1000}
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))

        with (
            patch.dict(os_mod.environ, {"SW_AUDIT_KEY": "key", "MY_TOKEN": "val"}),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()

        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed

        trail = _read_audit_trail(tmp_path)
        assert len(trail) > 0
        events = [e["event"] for e in trail]
        assert "RUN_START" in events
        assert "RUN_COMPLETE" in events

    def test_backward_compatible_no_security_keys(self, tmp_path):
        _config(tmp_path)
        with (
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        state = load_state(tmp_path / ".claude")
        assert "m1" in state.completed
        assert not (tmp_path / ".claude" / "audit-trail.jsonl").exists()

    def test_audit_trail_survives_milestone_failure(self, tmp_path):
        config = _config(tmp_path)
        config["security"] = {"audit_trail": True}
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))
        error_result = ClaudeResult(text="fail", is_error=True)
        with (
            patch.dict(os_mod.environ, {"SW_AUDIT_KEY": "key"}),
            patch("superpower_workflow.orchestrator.run_claude", return_value=error_result),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
            patch("superpower_workflow.orchestrator.time.sleep"),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        trail = _read_audit_trail(tmp_path)
        assert any(e["event"] == "RUN_START" for e in trail)
        assert any(e["event"] == "RUN_COMPLETE" for e in trail)

    def test_multi_milestone_audit_chain_valid(self, tmp_path):
        config = _config(
            tmp_path,
            milestones=[
                {"name": "m1", "spec_sections": "1", "depends_on": []},
                {"name": "m2", "spec_sections": "2", "depends_on": ["m1"]},
            ],
        )
        config["security"] = {"audit_trail": True}
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))
        with (
            patch.dict(os_mod.environ, {"SW_AUDIT_KEY": "key"}),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        from superpower_workflow.audit import AuditTrail, _hkdf_sha256

        key = _hkdf_sha256(b"key", info=b"sw-audit-trail")
        audit_path = tmp_path / ".claude" / "audit-trail.jsonl"
        trail = AuditTrail(audit_path, key=key)
        valid, last_seq = trail.verify()
        assert valid is True
        assert last_seq > 5

    def test_telemetry_and_audit_coexist(self, tmp_path):
        config = _config(tmp_path)
        config["security"] = {"audit_trail": True}
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))
        with (
            patch.dict(os_mod.environ, {"SW_AUDIT_KEY": "key"}),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        telemetry = _read_telemetry(tmp_path)
        audit = _read_audit_trail(tmp_path)
        assert len(telemetry) > 0
        assert len(audit) > 0
        assert any(e["type"] == "run_started" for e in telemetry)
        assert any(e["event"] == "RUN_START" for e in audit)

    def test_all_run_ids_consistent_in_audit(self, tmp_path):
        config = _config(tmp_path)
        config["security"] = {"audit_trail": True}
        (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(config))
        with (
            patch.dict(os_mod.environ, {"SW_AUDIT_KEY": "key"}),
            patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
            patch(
                "superpower_workflow.orchestrator.subprocess.run",
                side_effect=_smart_subprocess,
            ),
        ):
            orch = Orchestrator(tmp_path)
            orch.run()
        trail = _read_audit_trail(tmp_path)
        run_ids = {e["run_id"] for e in trail if e["run_id"]}
        assert len(run_ids) == 1
```

- [ ] **Step 2: Run tests — expect PASS** (all integration points already wired)

- [ ] **Step 3: Run full test suite**

```bash
.venv/Scripts/pytest -v
```

- [ ] **Step 4: Ruff check + format**

```bash
.venv/Scripts/ruff check src/ tests/ --fix
.venv/Scripts/ruff format src/ tests/
```

- [ ] **Step 5: Commit if any format changes**

```bash
git add -A
git commit -m "test: add full integration tests for SP4 security pipeline"
```

---

## Self-Review

**Spec coverage:**
- §3 (HMAC-chained audit trail) → Tasks 1-4 (AuditEntry, HKDF, AuditTrail.append/verify) + Task 10 (integration)
- §4 (SBOM generation) → Task 8 (generate_sbom) + Task 13 (Phase D integration)
- §5 (Ed25519 signed artifacts) → Task 9 (sign/verify) + Task 13 (Phase D integration)
- §6 (Secrets broker) → Task 5 (SecretsHandler) + Task 11 (prompt injection)
- §7 (Policy engine) → Tasks 6-7 (PolicyEngine rules) + Task 12 (quality gate integration)
- §2 (Configuration) → Task 15 (workflow.json, template, init, gitignore)
- §8 (Files changed) → All 9 files in spec covered by Tasks 1-16
- §9 (Cryptographic dependencies) → Task 9 (optional `cryptography` in pyproject.toml)
- §9 (Backward compatibility) → Task 16 (integration tests verify no-config-works)

**Zero new required dependencies:** HMAC-SHA256 and HKDF use stdlib `hmac` + `hashlib`. Ed25519 uses optional `cryptography`. PolicyEngine uses stdlib `ast`. SecretsHandler uses `os.environ`.

**Placeholder scan:** No TBD, TODO, or "implement later."

**Type consistency:** `AuditTrail.verify()` returns `tuple[bool, int]`. `PolicyEngine.check()` returns `tuple[bool, list[str]]` (same as `_verify_quality_gates`). `generate_sbom()` returns `tuple[bool, str]`. `sign_artifact()` returns `str | None`. `SecretsHandler.resolve()` raises `ValueError` on missing vars.

**Backward compatibility:** No `security`/`secrets`/`policies` sections in config → all features disabled, orchestrator runs identically to pre-SP4. All new methods have guard clauses for missing config.

**Security invariants:**
- Secret values never appear in prompts (only env var names via `$VAR`)
- Audit trail tamper-detection via HMAC chain
- Key material only from env vars, never from config files
- `SecretsHandler.redact()` strips values from any text before logging

**Test count estimate:** ~65-75 new tests across test_audit.py, test_security.py, test_policy.py, test_orchestrator.py, test_cli.py.
