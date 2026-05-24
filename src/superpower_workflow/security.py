from __future__ import annotations

import os
import shlex
import subprocess


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
            raise ValueError(f"Missing required env vars for secrets: {', '.join(missing)}")

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
