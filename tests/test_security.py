from __future__ import annotations

import os
import subprocess as subprocess_mod
from subprocess import CompletedProcess
from unittest.mock import patch

from superpower_workflow.security import (
    HAS_CRYPTO,
    SecretsHandler,
    generate_sbom,
    sign_artifact,
    verify_signature,
)


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
                raise AssertionError("Should have raised")
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
                raise AssertionError("Should have raised")
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
        sign_result = [None]

        def capture_run(cmd, **kwargs):
            if isinstance(cmd, list) and "rev-parse" in cmd:
                return CompletedProcess(args=cmd, returncode=0, stdout=f"{tree_hash}\n", stderr="")
            if isinstance(cmd, list) and "notes" in cmd and "add" in cmd:
                for arg in cmd:
                    if arg.startswith("sig:"):
                        sign_result[0] = arg.removeprefix("sig:")
                return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if isinstance(cmd, list) and "notes" in cmd and "show" in cmd:
                sig = sign_result[0]
                return CompletedProcess(args=cmd, returncode=0, stdout=f"sig:{sig}\n", stderr="")
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with (
            patch.dict(os.environ, {"SW_SIGN_KEY": key_hex}),
            patch("superpower_workflow.security.subprocess.run", side_effect=capture_run),
        ):
            sig = sign_artifact(tag="v1.0", cwd=str(tmp_path))

        assert sig is not None
        assert sign_result[0] is not None

        with patch("superpower_workflow.security.subprocess.run", side_effect=capture_run):
            valid = verify_signature(tag="v1.0", public_key_hex=pub_hex, cwd=str(tmp_path))

        assert valid is True

    def test_verify_returns_false_on_bad_sig(self, tmp_path):
        if not HAS_CRYPTO:
            return

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        pub_hex = Ed25519PrivateKey.generate().public_key().public_bytes_raw().hex()

        def mock_run(cmd, **kwargs):
            if isinstance(cmd, list) and "rev-parse" in cmd:
                return CompletedProcess(args=cmd, returncode=0, stdout="abc123\n", stderr="")
            if isinstance(cmd, list) and "notes" in cmd and "show" in cmd:
                return CompletedProcess(
                    args=cmd, returncode=0, stdout="sig:" + "ff" * 64 + "\n", stderr=""
                )
            return CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("superpower_workflow.security.subprocess.run", side_effect=mock_run):
            valid = verify_signature(tag="v1.0", public_key_hex=pub_hex, cwd=str(tmp_path))
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
            valid = verify_signature(tag="v1.0", public_key_hex=pub_hex, cwd=str(tmp_path))
        assert valid is False
