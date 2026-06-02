# p1-m1-core-types-storage — Implementation Plan

**Milestone:** p1-m1-core-types-storage  
**Date:** 2026-06-02  
**Focus:** Core types (Entry, ShortCode), atomic storage abstraction, JSON schema versioning, base62 hash computation  
**Spec sections:** Functional requirements, Non-functional requirements  
**Depends on:** None

## Overview

This milestone establishes the foundation for shrt by building:
1. **Type definitions** — Entry dataclass with versioning, ShortCode NewType, Timestamp type
2. **Exception types** — StorageError and subclasses for p1-m2 use
3. **Hash computation** — Deterministic base62 encoding/decoding, 6-char URL hash
4. **Schema versioning** — Version field on Entry, migration hooks for future compatibility

**Scope note:** Storage abstraction (StoreBackend protocol) is deferred to p1-m2; p1-m1 is types and hashing only.

All code is internal-only (no CLI surface yet). Tests are comprehensive with ≥90% branch coverage.

## Architecture

```
shrt/
  __init__.py       — Exports all public types/functions
  types.py          — Entry, ShortCode, SCHEMA_VERSION, error types
  hash.py           — base62_encode, base62_decode, hash_url
  storage.py        — StoreBackend protocol, error handling
  exceptions.py     — Custom exception hierarchy
```

### Types

**Entry (dataclass)**
- `short_code: ShortCode` — The short identifier
- `url: str` — The long URL
- `created: float` — Unix timestamp
- `version: int = SCHEMA_VERSION` — For future migrations

**ShortCode (NewType)**
- String constraint: `[a-zA-Z0-9_-]{1,32}`
- Used for both auto-generated (6-char base62) and user aliases

**Timestamp**
- `float` epoch seconds (from `time.time()`)
- Used consistently across Entry.created and stats queries

### Exception types

Exception hierarchy for storage operations (used by p1-m2):
- `StorageError` — Base exception (inherits from Exception)
- `StorageNotFoundError` — File/resource doesn't exist
- `StorageIOError` — Disk I/O failure
- `StorageCorruptedError` — Invalid JSON or schema mismatch
- `StoragePermissionError` — Access denied

All are defined in p1-m1; actual storage I/O error handling deferred to p1-m2.

### Hash computation

**base62_encode(n: int) -> str**
- Encodes integer to base62 using `[0-9a-zA-Z]` alphabet
- Used to convert hash digest to short code

**base62_decode(s: str) -> int**
- Decodes base62 string back to integer
- Validates character set, rejects non-base62 input

**hash_url(url: str) -> str**
- SHA256(url).digest() → first 4 bytes as uint32
- Modulo base62^6 to get 6-digit base62 (never needs padding)
- base62_encode → always exactly 6 characters
- Deterministic: same URL always produces same code
- Note: different URLs with trailing slashes (http://a.com vs http://a.com/) produce different hashes

## Tasks (TDD order)

### Task 1: Project setup
- [ ] Initialize `shrt/` package with `__init__.py` (empty exports for now)
- [ ] Create `tests/` directory
- [ ] Create `conftest.py` with pytest fixtures:
  - `sample_entry()` — fixture returning a valid Entry instance
  - `sample_urls()` — fixture returning list of valid http/https URLs
- [ ] Create `pyproject.toml` with hatchling, pytest, pytest-asyncio, ruff dependencies
- [ ] Create `.ruff.toml` with E, F, I, B, UP, SIM rules, 88-char line length
- [ ] Create `pytest.ini` with asyncio_mode = auto
- **Tests:** conftest loads, pytest discovers tests, ruff runs clean on boilerplate

### Task 2: Exception hierarchy
- [ ] Create `shrt/exceptions.py` with StorageError base class
- [ ] Add StorageNotFoundError, StorageIOError, StorageCorruptedError, StoragePermissionError
- [ ] All inherit from StorageError which inherits from Exception
- **Tests:** `test_exceptions.py` — instantiation, repr, inheritance chain

### Task 3: Base62 encoding (red)
- [ ] Write `test_hash.py` with test cases for base62_encode
  - [ ] Single digits (0-9 encode as "0"-"9")
  - [ ] 10-35 (encode as "a"-"z")
  - [ ] 36-61 (encode as "A"-"Z")
  - [ ] Multi-digit numbers (e.g., 62 → "10", 3843 → "zz")
  - [ ] Zero edge case
- [ ] All tests RED (function doesn't exist yet)

### Task 4: Base62 encoding (green)
- [ ] Create `shrt/hash.py` with `base62_encode(n: int) -> str`
- [ ] Implement simple algorithm: divide by 62 repeatedly, map each remainder to char
- [ ] Make tests GREEN
- **Tests:** All base62_encode tests pass

### Task 5: Base62 decoding (red)
- [ ] Add to `test_hash.py` test cases for base62_decode
  - [ ] Reverse of encoding tests (must round-trip: encode(n) → decode → n)
  - [ ] Invalid input rejection: non-base62 chars raise ValueError
  - [ ] Empty string edge case
- [ ] All tests RED

### Task 6: Base62 decoding (green)
- [ ] Implement `base62_decode(s: str) -> int` in `shrt/hash.py`
- [ ] Character validation, inverse map, accumulation
- [ ] Make tests GREEN
- **Tests:** All base62_decode tests pass, round-trip property holds

### Task 7: URL hashing (red)
- [ ] Add to `test_hash.py` test cases for `hash_url(url: str) -> str`
  - [ ] Determinism: hash_url(url) called twice returns identical 6-char result
  - [ ] Valid http/https URLs produce exactly 6-char base62 output
  - [ ] Different URLs produce different codes (sample http://a.com vs http://b.com)
  - [ ] URL variant handling: http://a.com and http://a.com/ produce different hashes
  - [ ] Output always 6 chars, uppercase/lowercase base62 (no padding)
- [ ] All tests RED

### Task 8: URL hashing (green)
- [ ] Implement `hash_url(url: str) -> str` in `shrt/hash.py`
  - [ ] `hashlib.sha256(url.encode()).digest()[:4]` → uint32
  - [ ] `uint32 % (62^6)` to get 6-digit base62 value (no padding needed)
  - [ ] `base62_encode(value)` → base62 string
  - [ ] Ensure output is exactly 6 characters (left-pad with "0" if encode produces < 6 chars)
- [ ] Make tests GREEN
- **Tests:** All hash_url tests pass, determinism verified, URL variants differ

### Task 9: Entry type definition (red)
- [ ] Write `test_types.py` with test cases for Entry dataclass
  - [ ] Creation from constructor with all fields
  - [ ] Version field defaults to SCHEMA_VERSION
  - [ ] Field types are correct (ShortCode, str, float, int)
  - [ ] Serialization to dict for JSON (using dataclasses.asdict)
  - [ ] Equality comparison
- [ ] All tests RED (Entry doesn't exist)

### Task 10: Entry type definition (green)
- [ ] Create `shrt/types.py` with imports
- [ ] Define `SCHEMA_VERSION = 1`
- [ ] Define `ShortCode = NewType('ShortCode', str)`
- [ ] Define `Timestamp = float` (alias for clarity)
- [ ] Implement `@dataclass Entry` with fields:
  - `short_code: ShortCode`
  - `url: str`
  - `created: float` (Timestamp)
  - `version: int = SCHEMA_VERSION` (plain default, not factory)
- [ ] Make tests GREEN
- **Tests:** All Entry tests pass, version field defaults correctly

### Task 11: ShortCode validation (red)
- [ ] Add to `test_types.py` a validation function test for ShortCode
  - [ ] Valid: [a-zA-Z0-9_-]{1,32}
  - [ ] Invalid: length 0, length > 32, invalid chars (spaces, dots, etc.)
  - [ ] Function: `validate_short_code(code: str) -> None` raises ValueError on invalid
  - [ ] Note: validation is permissive (allows full 1-32 range) because CLI will re-validate
- [ ] All tests RED

### Task 12: ShortCode validation (green)
- [ ] Implement `validate_short_code(code: str) -> None` in `shrt/types.py`
- [ ] Use regex or manual char-by-char validation
- [ ] Raise ValueError with descriptive message on validation failure
- [ ] Make tests GREEN
- **Tests:** All validation tests pass

### Task 13: (Deferred to p1-m2) StoreBackend protocol
- Storage abstraction protocol deferred to p1-m2-storage-layer
- p1-m1 builds only types and hashing; p1-m2 will define StoreBackend and JsonStore

### Task 14: Package exports
- [ ] Update `shrt/__init__.py` with `__all__`:
  - Entry, ShortCode, SCHEMA_VERSION, validate_short_code
  - hash_url, base62_encode, base62_decode
  - StorageError and all subclasses (StorageNotFoundError, StorageIOError, etc.)
- [ ] All imports work from package root
- [ ] **Tests:** `test_exports.py` verifies `__all__` completeness and importability

### Task 15: Schema version consistency check
- [ ] Verify all dataclasses with version field use SCHEMA_VERSION constant
- [ ] Currently only Entry has version field (correct)
- [ ] Document that future versioned types must import SCHEMA_VERSION from types.py
- [ ] **Tests:** Integration test checks Entry.version == SCHEMA_VERSION after creation

### Task 16: Type checking and linting
- [ ] Run `ruff check shrt/ tests/` — must pass zero violations
- [ ] Run `ruff format --check shrt/ tests/` — must pass
- [ ] No type stubs needed; inline annotations sufficient
- **Tests:** Linting passes cleanly

### Task 17: Coverage verification
- [ ] Run `pytest --cov=shrt --cov-branch -q tests/`
- [ ] Verify ≥90% branch coverage on all shrt/ modules
- [ ] Generate coverage report; identify any gaps
- [ ] Coverage checklist:
  - [ ] base62_encode: all digit ranges (0-9, 10-35, 36-61, multi-digit)
  - [ ] base62_decode: valid input, invalid chars, empty string, round-trip
  - [ ] hash_url: determinism, URL variants, base62 output validation
  - [ ] Entry: creation, defaults, serialization, equality
  - [ ] validate_short_code: all valid cases, all invalid cases
  - [ ] Exception classes: instantiation, inheritance
- [ ] **Tests:** Coverage ≥90% across all modules

### Task 18: Integration test — end-to-end flow (red)
- [ ] Write `test_e2e_milestone.py` integration test
  - [ ] Create an Entry with hashed short code
  - [ ] Validate short code
  - [ ] Store Entry in dict
  - [ ] Retrieve and verify
  - [ ] Check schema version is preserved
  - [ ] Round-trip base62 encode/decode
- [ ] Test RED (full flow may have gaps)

### Task 19: Integration test — end-to-end flow (green)
- [ ] Fix any remaining bugs in Entry, validation, or hash functions
- [ ] All integration tests GREEN
- [ ] Verify coverage checklist from Task 17
- **Tests:** Full end-to-end milestone flow works, ≥90% coverage confirmed

### Task 20: Documentation
- [ ] Add docstrings to all public functions and classes (module-level + class/function level)
- [ ] No multi-line docstrings; single-line per CLAUDE.md convention
- [ ] Update CLAUDE.md with any deviations discovered
- [ ] Document hash_url determinism behavior (URL variants differ)
- [ ] Document ShortCode validation scope (permissive by design)
- [ ] **Tests:** All docstrings present, no type errors

### Task 21: Commit and tag
- [ ] Ensure pytest passes with 90%+ coverage
- [ ] Ensure ruff check and ruff format pass
- [ ] Commit with message: `feat: p1-m1 core types, hashing, and exceptions`
- [ ] No push (handled by workflow)

## Acceptance criteria

- [ ] `pytest -q` passes with ≥90% branch coverage
- [ ] `ruff check . && ruff format --check .` reports zero violations
- [ ] All 4 exception classes implemented and tested
- [ ] base62_encode/decode are deterministic and round-trip correctly
- [ ] hash_url produces consistent 6-char codes (no padding needed)
- [ ] hash_url produces different codes for URL variants (http://a.com != http://a.com/)
- [ ] Entry dataclass with versioning defaults to SCHEMA_VERSION (plain default, not factory)
- [ ] ShortCode validation enforces [a-zA-Z0-9_-]{1,32} constraint
- [ ] All public symbols exported via `__all__` in `shrt/__init__.py` (StorageBackend NOT included)
- [ ] All versioned types use same SCHEMA_VERSION constant
- [ ] No uncommitted changes; head commit message: `feat: p1-m1 core types, hashing, and exceptions`

## Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| base62 algorithm has off-by-one errors | Extensive test cases covering boundaries (0, 61, 62, etc.) |
| hash_url determinism breaks | Always hash same input same way; log any non-determinism in tests |
| Protocol compliance unclear | Mock backends in tests; use `@runtime_checkable` |
| Coverage gaps in error paths | Test exception raising, not just happy path |
| Schema version field missed | Include in every Entry test; validate in e2e test |

## Timeline

- **Estimated effort:** 3-5 hours (20 tasks, mostly TDD test-first, no storage layer)
- **Order:** Follow task sequence strictly (dependencies marked)
- **Checkpoints:** After tasks 4, 6, 8 (hash complete), 10, 14 (exports), 19 (integration), 21 (final)
