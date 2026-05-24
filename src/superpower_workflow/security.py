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
