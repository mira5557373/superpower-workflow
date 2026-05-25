from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class RemoteResult:
    success: bool = False
    cost_usd: float = 0.0
    error: str = ""


@dataclass
class RemoteConfig:
    host: str
    user: str | None = None
    port: int = 22
    path: str | None = None

    @classmethod
    def from_url(cls, url: str) -> RemoteConfig:
        if not url.startswith("ssh://"):
            raise ValueError(f"URL must start with ssh:// (got: {url})")
        parsed = urlparse(url)
        return cls(
            host=parsed.hostname or "",
            user=parsed.username,
            port=parsed.port or 22,
            path=parsed.path or None,
        )

    @property
    def ssh_target(self) -> str:
        if self.user:
            return f"{self.user}@{self.host}"
        return self.host


class RemoteRunner:
    def __init__(self, config: RemoteConfig, cwd: str, timeout: int = 7200) -> None:
        self._config = config
        self._cwd = cwd
        self._timeout = timeout

    def sync(self) -> None:
        target = self._config.ssh_target
        path = self._config.path or "."
        subprocess.run(
            ["git", "push", f"{target}:{path}", "HEAD"],
            capture_output=True,
            text=True,
            cwd=self._cwd,
            timeout=120,
        )

    def run_milestone(self, milestone: str) -> RemoteResult:
        ssh_cmd = ["ssh"]
        if self._config.port != 22:
            ssh_cmd.extend(["-p", str(self._config.port)])
        ssh_cmd.append(self._config.ssh_target)

        remote_path = self._config.path or "."
        sw_cmd = f"cd {remote_path} && sw run --milestone {milestone}"
        ssh_cmd.append(sw_cmd)

        result = subprocess.run(
            ssh_cmd,
            capture_output=True,
            text=True,
            cwd=self._cwd,
            timeout=self._timeout,
        )

        if result.returncode != 0:
            return RemoteResult(success=False, error=result.stderr.strip())

        try:
            data = json.loads(result.stdout.strip())
            return RemoteResult(
                success=data.get("success", True),
                cost_usd=data.get("cost_usd", 0.0),
            )
        except (json.JSONDecodeError, ValueError):
            return RemoteResult(success=True)

    def pull_results(self) -> None:
        target = self._config.ssh_target
        path = self._config.path or "."
        subprocess.run(
            ["git", "fetch", f"{target}:{path}"],
            capture_output=True,
            text=True,
            cwd=self._cwd,
            timeout=120,
        )
