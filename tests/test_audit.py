from __future__ import annotations

import hashlib
import hmac as hmac_mod
import json
import os
from unittest.mock import patch

from superpower_workflow.audit import (
    AuditEntry,
    _canonical_json,
    _compute_hash,
    _hkdf_sha256,
    derive_key,
)


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
