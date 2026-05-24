# SP4: Security & Compliance — Design Spec

**Date:** 2026-05-24
**Spec version:** 1.0
**Status:** Approved for implementation planning
**Roadmap:** SP4 of 7 -> v0.5.0
**Goal:** Tamper-evident audit trail, signed artifacts, secrets isolation, and policy enforcement -- compliance guarantees for AI-generated code.

> Depends on SP1 (quality gates serve as the policy enforcement point).

---

## 1. Overview

Five capabilities that make AI-generated workflows auditable and policy-compliant:

1. **HMAC-chained audit trail** -- tamper-evident log at `.claude/audit-trail.jsonl`
2. **SBOM generation** -- CycloneDX bill of materials per milestone
3. **Ed25519 signed artifacts** -- cryptographic proof of milestone output
4. **Secrets broker** -- env-only secrets, never written to disk or prompts
5. **Policy engine** -- configurable rules enforced as quality gates

**Architecture:** Audit trail wraps every orchestrator action in a hash-chained JSONL log. Policy engine runs as an additional quality gate (same checkpoint as SP1). Signing and SBOM happen at milestone completion (Phase D), before the git tag.

---

## 2. Configuration

New `security`, `secrets`, and `policies` sections in workflow.json:

```json
{
  "security": {
    "audit_trail": true,
    "sign_artifacts": false,
    "sbom_tool": "pip-audit --format=cyclonedx-json",
    "sbom_output": ".claude/sbom-{milestone}.json"
  },
  "secrets": {
    "db_password": "DB_PASSWORD",
    "api_key": "OPENAI_API_KEY"
  },
  "policies": {
    "max_file_lines": 500,
    "banned_imports": ["os.system", "subprocess.call"],
    "required_license": "MIT",
    "require_type_hints": true
  }
}
```

All sections optional. Missing = disabled.

---

## 3. HMAC-Chained Audit Trail

Each entry contains HMAC-SHA256 of the previous entry's hash, forming a tamper-evident chain:

```json
{
  "seq": 42,
  "timestamp": "2026-05-24T14:30:00Z",
  "event": "PHASE_COMPLETE",
  "run_id": "abc123",
  "milestone": "milestone-03-auth",
  "data": {"phase": "B", "cost": 4.20},
  "prev_hash": "a1b2c3...",
  "hash": "d4e5f6..."
}
```

`AuditTrail` class: `append(event, run_id, milestone, data)` writes chain-linked entry. `verify()` checks entire chain, returns `(valid, last_valid_seq)`. `derive_key()` reads `SW_AUDIT_KEY` env var, derives HMAC key via HKDF-SHA256. If env var unset, audit disabled with warning. `hash` = HMAC-SHA256 of canonical JSON (excluding hash field). `prev_hash` = previous entry's hash (empty string for seq 0).

---

## 4. SBOM Generation

After each milestone (Phase D, before tag), run the configured SBOM tool:

- Python: `pip-audit --format=cyclonedx-json`
- Node: `npx @cyclonedx/cyclonedx-npm --output-file`
- Rust: `cargo cyclonedx`

Output committed alongside the milestone tag.

---

## 5. Ed25519 Signed Artifacts

Sign the milestone tag's tree hash with Ed25519. Private key read from `SW_SIGN_KEY` env var (64-char hex). If unset, signing skipped with warning. Signature stored as git note: `git notes add -m "sig:{signature}"`.

Verification: `sw audit verify-sig <tag>` reads note, reconstructs tree hash, verifies against public key (derived from private key or stored in `security.public_key`).

---

## 6. Secrets Broker

`SecretsHandler` maps logical names to env var names. `resolve()` verifies all env vars exist (raises if missing). `prompt_fragment()` generates system prompt addition: `"Secret db_password is in env var $DB_PASSWORD. Use env vars in code. NEVER hardcode."` Orchestrator passes fragment via `--append-system-prompt`. Actual values never appear in prompts, logs, telemetry, or audit trail.

---

## 7. Policy Engine

Rules enforced at quality gate checkpoints (same mechanism as SP1):

```python
class PolicyEngine:
    def __init__(self, policies: dict): ...
    def check(self, cwd: Path) -> tuple[bool, list[str]]:
        """Run all policy checks against changed files only."""
```

| Policy | Check |
|---|---|
| `max_file_lines` | No file exceeds N lines |
| `banned_imports` | No file contains banned import statements |
| `required_license` | LICENSE file exists with correct SPDX identifier |
| `require_type_hints` | All public functions have type annotations |

Checks run against changed files only (`git diff --name-only {base_sha}..HEAD`). Violations trigger one-shot fix (same pattern as SP1).

---

## 8. Files Changed

| File | Change |
|---|---|
| `src/superpower_workflow/audit.py` | **Create.** AuditTrail -- HMAC chain, append, verify |
| `src/superpower_workflow/security.py` | **Create.** sign_artifact, generate_sbom, SecretsHandler |
| `src/superpower_workflow/policy.py` | **Create.** PolicyEngine -- load rules, check changed files |
| `src/superpower_workflow/orchestrator.py` | **Modify.** Emit audit events, run policies, invoke signing/SBOM |
| `src/superpower_workflow/cli.py` | **Modify.** Add `sw audit verify` and `sw audit verify-sig` |
| `templates/workflow.json` | **Modify.** Add security, secrets, policies schema sections |
| `tests/test_audit.py` | **Create.** Chain integrity, tamper detection, key derivation |
| `tests/test_security.py` | **Create.** Signing round-trip, SBOM invocation, secrets resolution |
| `tests/test_policy.py` | **Create.** Each policy rule, changed-files-only scoping |

---

## 9. Appendix

### Cryptographic Dependencies

Uses `cryptography` library: HKDF-SHA256 for key derivation, Ed25519 for signing. Added as optional dependency: `pip install superpower-workflow[security]`.

### Threat Model

Audit trail protects against silent tampering of logs after the fact. Does NOT protect against an attacker with the HMAC key. Key must be stored securely (CI secret, vault).

### Backward Compatibility

All security features are opt-in. A workflow.json without `security`, `secrets`, or `policies` sections behaves identically to v0.4.0.
