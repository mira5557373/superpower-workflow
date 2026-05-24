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
