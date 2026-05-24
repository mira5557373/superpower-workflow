# SP5: Integrations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect superpower-workflow to external systems -- issue trackers, CI pipelines, chat, and PR tooling -- so `sw run` operates from ticket to merged PR without manual glue.

**Architecture:** Five integration modules live under a new `integrations/` subpackage. Notifier sends webhooks at milestone lifecycle events. GitHub module ingests issues and creates PRs via `gh` CLI. Tracker module fetches tickets from Linear (GraphQL) and Jira (REST) via `urllib.request`. CI fix module polls CI status and invokes `claude -p` to fix failures. Orchestrator gains Phase E (CI fix) after Phase D, notification hooks at milestone boundaries, and PR creation at milestone completion.

**Tech Stack:** Python 3.11+, `subprocess` (gh CLI), `urllib.request` (HTTP), `json`, `time`, `re`, `dataclasses`. Zero new dependencies -- all stdlib.

**Spec reference:** `docs/superpowers/specs/2026-05-24-sp5-integrations.md` (v1.0).

**Working directory:** `superpower-workflow/` (the repo root).

---

## Design Decisions (Spec Open Questions)

1. **CI self-correction model:** Same as main model by default. Override via `integrations.ci.model`.
2. **PR creation:** Opt-in (default off). Config: `integrations.github.auto_pr: false`.
3. **Tracker status updates:** Idempotent. Safe to re-run on resume.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `src/superpower_workflow/integrations/__init__.py` | New | Package init + `__all__` exports |
| `src/superpower_workflow/integrations/notifier.py` | New | Webhook notifications (Slack/Discord/generic) |
| `src/superpower_workflow/integrations/github.py` | New | Issue ingestion + PR creation via `gh` CLI |
| `src/superpower_workflow/integrations/tracker.py` | New | TrackerAdapter protocol, LinearAdapter, JiraAdapter |
| `src/superpower_workflow/integrations/ci_fix.py` | New | CI status polling, log retrieval, fix loop |
| `src/superpower_workflow/state.py` | Edit | New step values: ci_wait, ci_fix, ci_fix_failed |
| `src/superpower_workflow/cli.py` | Edit | Add `--from-issue`, `--from-ticket` to `sw run` + integrations config |
| `src/superpower_workflow/orchestrator.py` | Edit | Phase E, notification hooks, PR creation, issue/ticket ingestion |
| `templates/workflow.json` | Edit | Add `integrations` config section |
| `tests/test_notifier.py` | New | Notifier tests |
| `tests/test_github.py` | New | GitHub integration tests |
| `tests/test_tracker.py` | New | Tracker adapter tests |
| `tests/test_ci_fix.py` | New | CI fix tests |
| `tests/test_state.py` | Edit | New step value tests |
| `tests/test_cli.py` | Edit | --from-issue, --from-ticket, integrations config tests |
| `tests/test_orchestrator.py` | Edit | Phase E, notifications, PR creation, ingestion tests |

---

### Task 1: Notifier module -- format_message + send_notification

**Files:**
- New: `src/superpower_workflow/integrations/__init__.py`
- New: `src/superpower_workflow/integrations/notifier.py`
- New: `tests/test_notifier.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_notifier.py
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from superpower_workflow.integrations.notifier import format_message, send_notification


class TestFormatMessage:
    def test_milestone_start(self):
        msg = format_message("milestone_start", {"milestone": "m1"})
        assert "m1" in msg
        assert "start" in msg.lower()

    def test_milestone_complete(self):
        msg = format_message(
            "milestone_complete",
            {"milestone": "m1", "cost_usd": 15.0, "test_count": 12},
        )
        assert "m1" in msg
        assert "15.0" in msg or "$15" in msg
        assert "12" in msg

    def test_milestone_failed(self):
        msg = format_message(
            "milestone_failed",
            {"milestone": "m1", "phase": "Phase B", "reason": "timeout"},
        )
        assert "m1" in msg
        assert "FAIL" in msg.upper() or "fail" in msg.lower()

    def test_ci_fix(self):
        msg = format_message(
            "ci_fix",
            {"milestone": "m1", "attempt": 1, "max_attempts": 3, "status": "retrying"},
        )
        assert "m1" in msg
        assert "1" in msg
        assert "3" in msg

    def test_unknown_event_returns_generic(self):
        msg = format_message("some_other_event", {"data": "value"})
        assert "some_other_event" in msg


class TestSendNotification:
    def test_sends_post_to_webhook(self):
        config = {"webhook_url_env": "SLACK_WEBHOOK_URL", "events": ["milestone_start"]}
        with patch.dict("os.environ", {"SLACK_WEBHOOK_URL": "https://hooks.example.com/abc"}):
            with patch("superpower_workflow.integrations.notifier.urllib.request.urlopen") as mock_url:
                mock_url.return_value = MagicMock(status=200)
                result = send_notification(config, "milestone_start", {"milestone": "m1"})
        assert result is True
        mock_url.assert_called_once()
        req = mock_url.call_args[0][0]
        assert req.full_url == "https://hooks.example.com/abc"
        body = json.loads(req.data)
        assert "text" in body

    def test_skips_unconfigured_events(self):
        config = {"webhook_url_env": "SLACK_WEBHOOK_URL", "events": ["milestone_start"]}
        with patch.dict("os.environ", {"SLACK_WEBHOOK_URL": "https://hooks.example.com/abc"}):
            with patch("superpower_workflow.integrations.notifier.urllib.request.urlopen") as mock_url:
                result = send_notification(config, "milestone_complete", {"milestone": "m1"})
        assert result is False
        mock_url.assert_not_called()

    def test_noop_when_url_missing(self):
        config = {"webhook_url_env": "MISSING_VAR", "events": ["milestone_start"]}
        with patch.dict("os.environ", {}, clear=True):
            with patch("superpower_workflow.integrations.notifier.urllib.request.urlopen") as mock_url:
                result = send_notification(config, "milestone_start", {"milestone": "m1"})
        assert result is False
        mock_url.assert_not_called()

    def test_returns_false_on_http_error(self):
        config = {"webhook_url_env": "SLACK_WEBHOOK_URL", "events": ["milestone_start"]}
        with patch.dict("os.environ", {"SLACK_WEBHOOK_URL": "https://hooks.example.com/abc"}):
            with patch(
                "superpower_workflow.integrations.notifier.urllib.request.urlopen",
                side_effect=OSError("connection refused"),
            ):
                result = send_notification(config, "milestone_start", {"milestone": "m1"})
        assert result is False

    def test_empty_config_is_noop(self):
        result = send_notification({}, "milestone_start", {"milestone": "m1"})
        assert result is False

    def test_sends_with_timeout(self):
        config = {"webhook_url_env": "SLACK_WEBHOOK_URL", "events": ["milestone_start"]}
        with patch.dict("os.environ", {"SLACK_WEBHOOK_URL": "https://hooks.example.com/abc"}):
            with patch("superpower_workflow.integrations.notifier.urllib.request.urlopen") as mock_url:
                mock_url.return_value = MagicMock(status=200)
                send_notification(config, "milestone_start", {"milestone": "m1"})
        _, kwargs = mock_url.call_args
        assert kwargs.get("timeout") == 10
```

- [ ] **Step 2: Run tests -- expect FAIL** (module doesn't exist)

```bash
cd superpower-workflow && python -m pytest tests/test_notifier.py -x -q 2>&1 | head -20
```

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/integrations/__init__.py
from __future__ import annotations
```

```python
# src/superpower_workflow/integrations/notifier.py
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any


def format_message(event: str, payload: dict[str, Any]) -> str:
    milestone = payload.get("milestone", "unknown")
    if event == "milestone_start":
        return f"Starting milestone: {milestone}"
    if event == "milestone_complete":
        cost = payload.get("cost_usd", 0.0)
        tests = payload.get("test_count", 0)
        return f"Milestone {milestone} complete. Tests: {tests}, Cost: ${cost}"
    if event == "milestone_failed":
        phase = payload.get("phase", "unknown")
        reason = payload.get("reason", "")
        return f"Milestone {milestone} FAILED at {phase}. Error: {reason}"
    if event == "ci_fix":
        attempt = payload.get("attempt", 0)
        max_attempts = payload.get("max_attempts", 3)
        status = payload.get("status", "")
        return f"CI fix attempt {attempt}/{max_attempts} for {milestone}: {status}"
    return f"[{event}] {json.dumps(payload)}"


def send_notification(config: dict, event: str, payload: dict[str, Any]) -> bool:
    if not config:
        return False
    allowed_events = config.get("events", [])
    if event not in allowed_events:
        return False
    url_env = config.get("webhook_url_env", "")
    url = os.environ.get(url_env, "")
    if not url:
        return False
    text = format_message(event, payload)
    data = json.dumps({"text": text}).encode()
    req = urllib.request.Request(
        url, data=data, method="POST", headers={"Content-Type": "application/json"}
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except OSError:
        return False
```

- [ ] **Step 4: Run tests -- expect PASS**

```bash
cd superpower-workflow && python -m pytest tests/test_notifier.py -x -q
```

- [ ] **Step 5: Lint + format**

```bash
cd superpower-workflow && python -m ruff check src/superpower_workflow/integrations/ tests/test_notifier.py && python -m ruff format --check src/superpower_workflow/integrations/ tests/test_notifier.py
```

- [ ] **Step 6: Commit**

```bash
cd superpower-workflow && git add src/superpower_workflow/integrations/__init__.py src/superpower_workflow/integrations/notifier.py tests/test_notifier.py && git commit -m "feat: add notifier module with webhook notifications

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: GitHub issue ingestion -- parse_issue_ref + fetch_issue + issue_to_milestone

**Files:**
- New: `src/superpower_workflow/integrations/github.py`
- New: `tests/test_github.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_github.py
from __future__ import annotations

import json
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from superpower_workflow.integrations.github import (
    fetch_issue,
    issue_to_milestone,
    parse_issue_ref,
)


class TestParseIssueRef:
    def test_bare_number(self):
        repo, number = parse_issue_ref("42", default_repo="owner/repo")
        assert repo == "owner/repo"
        assert number == 42

    def test_hash_prefix(self):
        repo, number = parse_issue_ref("#42", default_repo="owner/repo")
        assert repo == "owner/repo"
        assert number == 42

    def test_full_ref(self):
        repo, number = parse_issue_ref("myorg/myrepo#99")
        assert repo == "myorg/myrepo"
        assert number == 99

    def test_no_default_repo_bare_number(self):
        repo, number = parse_issue_ref("42")
        assert repo == ""
        assert number == 42

    def test_invalid_number_raises(self):
        with pytest.raises(ValueError):
            parse_issue_ref("not-a-number")


class TestFetchIssue:
    def test_fetches_via_gh_cli(self):
        issue_json = {
            "title": "Fix login",
            "body": "Login is broken for SSO users",
            "labels": [{"name": "bug"}],
            "assignees": [{"login": "dev1"}],
        }
        with patch("superpower_workflow.integrations.github.subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(issue_json), stderr=""
            )
            result = fetch_issue("42", default_repo="owner/repo")
        assert result["title"] == "Fix login"
        assert result["body"] == "Login is broken for SSO users"
        cmd = mock_run.call_args[0][0]
        assert "gh" in cmd
        assert "issue" in cmd
        assert "42" in cmd[cmd.index("view") + 1]

    def test_includes_repo_flag_when_provided(self):
        with patch("superpower_workflow.integrations.github.subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(
                args=[], returncode=0, stdout='{"title":"t","body":"b","labels":[],"assignees":[]}', stderr=""
            )
            fetch_issue("owner/repo#42")
        cmd = mock_run.call_args[0][0]
        assert "--repo" in cmd
        assert "owner/repo" in cmd

    def test_raises_on_gh_failure(self):
        with patch("superpower_workflow.integrations.github.subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(
                args=[], returncode=1, stdout="", stderr="not found"
            )
            with pytest.raises(RuntimeError, match="fetch issue"):
                fetch_issue("999", default_repo="owner/repo")


class TestIssueToMilestone:
    def test_basic_conversion(self):
        issue = {
            "title": "Add dark mode",
            "body": "Support dark mode in the settings page",
            "labels": [{"name": "feature"}],
            "assignees": [],
        }
        ms = issue_to_milestone(issue)
        assert ms["name"] == "add-dark-mode"
        assert ms["description"] == "Add dark mode"
        assert ms["spec_sections"] == "Support dark mode in the settings page"
        assert ms["depends_on"] == []

    def test_label_map(self):
        issue = {
            "title": "Fix crash",
            "body": "App crashes on startup",
            "labels": [{"name": "bug"}],
            "assignees": [],
        }
        ms = issue_to_milestone(issue, label_map={"bug": "fix", "feature": "feature"})
        assert ms["type"] == "fix"

    def test_no_matching_label(self):
        issue = {
            "title": "Something",
            "body": "Details",
            "labels": [{"name": "priority-high"}],
            "assignees": [],
        }
        ms = issue_to_milestone(issue, label_map={"bug": "fix"})
        assert "type" not in ms or ms.get("type") == ""

    def test_long_title_truncated(self):
        issue = {
            "title": "A" * 100,
            "body": "details",
            "labels": [],
            "assignees": [],
        }
        ms = issue_to_milestone(issue)
        assert len(ms["name"]) <= 50

    def test_special_chars_slugified(self):
        issue = {
            "title": "Fix: login & SSO [urgent]",
            "body": "details",
            "labels": [],
            "assignees": [],
        }
        ms = issue_to_milestone(issue)
        assert ms["name"] == "fix-login-sso-urgent"
```

- [ ] **Step 2: Run tests -- expect FAIL**

```bash
cd superpower-workflow && python -m pytest tests/test_github.py -x -q 2>&1 | head -20
```

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/integrations/github.py
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any


def parse_issue_ref(ref: str, default_repo: str = "") -> tuple[str, int]:
    ref = ref.strip().lstrip("#")
    if "#" in ref:
        parts = ref.split("#", 1)
        repo = parts[0] or default_repo
        number = int(parts[1])
    else:
        repo = default_repo
        number = int(ref)
    return repo, number


def fetch_issue(issue_ref: str, default_repo: str = "", cwd: str = ".") -> dict[str, Any]:
    repo, number = parse_issue_ref(issue_ref, default_repo)
    cmd = [
        "gh", "issue", "view", str(number),
        "--json", "title,body,labels,assignees",
    ]
    if repo:
        cmd.extend(["--repo", repo])
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to fetch issue {issue_ref}: {result.stderr.strip()}")
    return json.loads(result.stdout)


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:50]


def issue_to_milestone(
    issue_data: dict[str, Any],
    label_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    title = issue_data.get("title", "untitled")
    ms: dict[str, Any] = {
        "name": _slugify(title),
        "description": title,
        "spec_sections": issue_data.get("body", ""),
        "depends_on": [],
    }
    if label_map:
        labels = [lb.get("name", "") for lb in issue_data.get("labels", [])]
        for label in labels:
            if label in label_map:
                ms["type"] = label_map[label]
                break
        if "type" not in ms:
            ms["type"] = ""
    return ms
```

- [ ] **Step 4: Run tests -- expect PASS**

```bash
cd superpower-workflow && python -m pytest tests/test_github.py -x -q
```

- [ ] **Step 5: Lint + format**

```bash
cd superpower-workflow && python -m ruff check src/superpower_workflow/integrations/github.py tests/test_github.py && python -m ruff format --check src/superpower_workflow/integrations/github.py tests/test_github.py
```

- [ ] **Step 6: Commit**

```bash
cd superpower-workflow && git add src/superpower_workflow/integrations/github.py tests/test_github.py && git commit -m "feat: add GitHub issue ingestion via gh CLI

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: GitHub PR creation -- render_pr_body + create_pr

**Files:**
- Edit: `src/superpower_workflow/integrations/github.py`
- Edit: `tests/test_github.py`

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_github.py
from superpower_workflow.integrations.github import create_pr, render_pr_body


class TestRenderPrBody:
    def test_includes_milestone_name(self):
        body = render_pr_body("m1", description="First milestone", changes="abc123 feat: stuff")
        assert "m1" in body

    def test_includes_changes(self):
        body = render_pr_body("m1", description="desc", changes="abc123 feat: add X\ndef456 fix: Y")
        assert "abc123" in body
        assert "def456" in body

    def test_includes_cost_and_duration(self):
        body = render_pr_body(
            "m1", description="desc", cost_usd=15.50, duration_seconds=300.0, test_count=8,
        )
        assert "15.5" in body or "$15.50" in body
        assert "8" in body

    def test_includes_version(self):
        body = render_pr_body("m1", description="desc")
        assert "superpower-workflow" in body

    def test_empty_changes_section(self):
        body = render_pr_body("m1", description="desc", changes="")
        assert "m1" in body


class TestCreatePr:
    def test_creates_pr_via_gh(self):
        with patch("superpower_workflow.integrations.github.subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(
                args=[], returncode=0,
                stdout="https://github.com/owner/repo/pull/1\n",
                stderr="",
            )
            url = create_pr(
                title="m1",
                body="## m1\nChanges here",
                branch="milestone/m1",
                base="main",
            )
        assert url == "https://github.com/owner/repo/pull/1"
        cmd = mock_run.call_args[0][0]
        assert "gh" in cmd
        assert "pr" in cmd
        assert "create" in cmd
        assert "--title" in cmd
        assert "--head" in cmd

    def test_returns_empty_on_failure(self):
        with patch("superpower_workflow.integrations.github.subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(
                args=[], returncode=1, stdout="", stderr="already exists"
            )
            url = create_pr(title="m1", body="body", branch="b", base="main")
        assert url == ""

    def test_passes_repo_flag(self):
        with patch("superpower_workflow.integrations.github.subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(
                args=[], returncode=0, stdout="https://github.com/o/r/pull/1\n", stderr=""
            )
            create_pr(title="m1", body="body", branch="b", base="main", repo="o/r")
        cmd = mock_run.call_args[0][0]
        assert "--repo" in cmd
        assert "o/r" in cmd
```

- [ ] **Step 2: Run tests -- expect FAIL**

```bash
cd superpower-workflow && python -m pytest tests/test_github.py -x -q 2>&1 | head -20
```

- [ ] **Step 3: Implement** (append to github.py)

```python
# append to src/superpower_workflow/integrations/github.py

def render_pr_body(
    milestone: str,
    description: str = "",
    changes: str = "",
    cost_usd: float = 0.0,
    duration_seconds: float = 0.0,
    test_count: int = 0,
    coverage_pct: float = 0.0,
    total_tokens: int = 0,
) -> str:
    from superpower_workflow import __version__

    sections = [f"## {milestone}", ""]
    if description:
        sections.append(description)
        sections.append("")
    if changes:
        sections.extend(["### Changes", changes, ""])
    sections.append("### Test Results")
    sections.append(f"- Tests added: {test_count}")
    if coverage_pct > 0:
        sections.append(f"- Coverage: {coverage_pct:.0f}%")
    sections.append("")
    sections.append("### Cost")
    if total_tokens > 0:
        sections.append(f"- Tokens: {total_tokens}")
    sections.append(f"- Cost: ${cost_usd:.2f}")
    if duration_seconds > 0:
        sections.append(f"- Duration: {duration_seconds:.0f}s")
    sections.append("")
    sections.append(f"Generated by superpower-workflow v{__version__}")
    return "\n".join(sections)


def create_pr(
    title: str,
    body: str,
    branch: str,
    base: str = "main",
    cwd: str = ".",
    repo: str = "",
) -> str:
    cmd = [
        "gh", "pr", "create",
        "--title", title,
        "--body", body,
        "--head", branch,
        "--base", base,
    ]
    if repo:
        cmd.extend(["--repo", repo])
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=30)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()
```

- [ ] **Step 4: Run tests -- expect PASS**

```bash
cd superpower-workflow && python -m pytest tests/test_github.py -x -q
```

- [ ] **Step 5: Lint + format**

```bash
cd superpower-workflow && python -m ruff check src/superpower_workflow/integrations/github.py tests/test_github.py && python -m ruff format --check src/superpower_workflow/integrations/github.py tests/test_github.py
```

- [ ] **Step 6: Commit**

```bash
cd superpower-workflow && git add src/superpower_workflow/integrations/github.py tests/test_github.py && git commit -m "feat: add GitHub PR creation with cost and test summary

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Tracker protocol + Linear adapter

**Files:**
- New: `src/superpower_workflow/integrations/tracker.py`
- New: `tests/test_tracker.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_tracker.py
from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from superpower_workflow.integrations.tracker import (
    JiraAdapter,
    LinearAdapter,
    create_tracker,
)


class TestLinearAdapter:
    def _make_adapter(self) -> LinearAdapter:
        return LinearAdapter({
            "type": "linear",
            "api_url": "https://api.linear.app/graphql",
            "token_env": "LINEAR_API_TOKEN",
            "project_id": "proj-1",
        })

    def test_fetch_ticket(self):
        response_data = {
            "data": {
                "issue": {
                    "id": "abc-123",
                    "title": "Fix SSO login",
                    "description": "SSO users cannot authenticate",
                    "priority": {"label": "High"},
                    "assignee": {"name": "Alice"},
                    "state": {"name": "In Progress"},
                }
            }
        }
        adapter = self._make_adapter()
        with (
            patch.dict("os.environ", {"LINEAR_API_TOKEN": "tok-123"}),
            patch("superpower_workflow.integrations.tracker.urllib.request.urlopen") as mock_url,
        ):
            mock_url.return_value = BytesIO(json.dumps(response_data).encode())
            ticket = adapter.fetch_ticket("abc-123")
        assert ticket["title"] == "Fix SSO login"
        assert ticket["description"] == "SSO users cannot authenticate"
        assert ticket["priority"] == "High"

    def test_fetch_ticket_missing_token(self):
        adapter = self._make_adapter()
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="token"):
                adapter.fetch_ticket("abc-123")

    def test_ticket_to_milestone(self):
        adapter = self._make_adapter()
        ticket = {
            "title": "Fix SSO login",
            "description": "SSO users cannot authenticate",
            "priority": "High",
        }
        ms = adapter.ticket_to_milestone(ticket)
        assert ms["name"] == "fix-sso-login"
        assert ms["description"] == "Fix SSO login"
        assert ms["spec_sections"] == "SSO users cannot authenticate"
        assert ms["depends_on"] == []

    def test_update_status(self):
        adapter = self._make_adapter()
        with (
            patch.dict("os.environ", {"LINEAR_API_TOKEN": "tok-123"}),
            patch("superpower_workflow.integrations.tracker.urllib.request.urlopen") as mock_url,
        ):
            mock_url.return_value = BytesIO(b'{"data":{"issueUpdate":{"success":true}}}')
            result = adapter.update_status("abc-123", "Done", comment="PR merged")
        assert result is True


class TestJiraAdapter:
    def _make_adapter(self) -> JiraAdapter:
        return JiraAdapter({
            "type": "jira",
            "api_url": "https://mycompany.atlassian.net",
            "token_env": "JIRA_API_TOKEN",
            "user_env": "JIRA_USER_EMAIL",
        })

    def test_fetch_ticket(self):
        response_data = {
            "key": "PROJ-123",
            "fields": {
                "summary": "Update API docs",
                "description": "Docs are outdated",
                "priority": {"name": "Medium"},
                "assignee": {"displayName": "Bob"},
                "status": {"name": "To Do"},
            },
        }
        adapter = self._make_adapter()
        with (
            patch.dict("os.environ", {"JIRA_API_TOKEN": "tok-j", "JIRA_USER_EMAIL": "a@b.com"}),
            patch("superpower_workflow.integrations.tracker.urllib.request.urlopen") as mock_url,
        ):
            mock_url.return_value = BytesIO(json.dumps(response_data).encode())
            ticket = adapter.fetch_ticket("PROJ-123")
        assert ticket["title"] == "Update API docs"
        assert ticket["description"] == "Docs are outdated"
        assert ticket["priority"] == "Medium"

    def test_ticket_to_milestone(self):
        adapter = self._make_adapter()
        ticket = {"title": "Update API docs", "description": "Details", "priority": "Medium"}
        ms = adapter.ticket_to_milestone(ticket)
        assert ms["name"] == "update-api-docs"
        assert ms["depends_on"] == []

    def test_update_status(self):
        adapter = self._make_adapter()
        with (
            patch.dict("os.environ", {"JIRA_API_TOKEN": "tok-j", "JIRA_USER_EMAIL": "a@b.com"}),
            patch("superpower_workflow.integrations.tracker.urllib.request.urlopen") as mock_url,
        ):
            mock_url.return_value = BytesIO(b'{}')
            result = adapter.update_status("PROJ-123", "Done")
        assert result is True


class TestCreateTracker:
    def test_creates_linear_adapter(self):
        config = {"integrations": {"tracker": {"type": "linear", "api_url": "https://api.linear.app/graphql", "token_env": "T"}}}
        adapter = create_tracker(config)
        assert isinstance(adapter, LinearAdapter)

    def test_creates_jira_adapter(self):
        config = {"integrations": {"tracker": {"type": "jira", "api_url": "https://jira.example.com", "token_env": "T"}}}
        adapter = create_tracker(config)
        assert isinstance(adapter, JiraAdapter)

    def test_returns_none_for_unknown(self):
        config = {"integrations": {"tracker": {"type": "unknown"}}}
        assert create_tracker(config) is None

    def test_returns_none_when_no_tracker(self):
        assert create_tracker({}) is None
        assert create_tracker({"integrations": {}}) is None
```

- [ ] **Step 2: Run tests -- expect FAIL**

```bash
cd superpower-workflow && python -m pytest tests/test_tracker.py -x -q 2>&1 | head -20
```

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/integrations/tracker.py
from __future__ import annotations

import base64
import json
import os
import re
import urllib.request
from typing import Any, Protocol


class TrackerAdapter(Protocol):
    def fetch_ticket(self, ticket_id: str) -> dict[str, Any]: ...
    def update_status(self, ticket_id: str, status: str, comment: str = "") -> bool: ...
    def ticket_to_milestone(self, ticket_data: dict[str, Any]) -> dict[str, Any]: ...


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:50]


class LinearAdapter:
    def __init__(self, config: dict[str, Any]) -> None:
        self._api_url = config.get("api_url", "https://api.linear.app/graphql")
        self._token_env = config.get("token_env", "LINEAR_API_TOKEN")

    def _get_token(self) -> str:
        token = os.environ.get(self._token_env, "")
        if not token:
            raise ValueError(f"Missing token: env var '{self._token_env}' not set")
        return token

    def fetch_ticket(self, ticket_id: str) -> dict[str, Any]:
        token = self._get_token()
        query = {
            "query": "query($id: String!) { issue(id: $id) { id title description priority { label } assignee { name } state { name } } }",
            "variables": {"id": ticket_id},
        }
        req = urllib.request.Request(
            self._api_url,
            data=json.dumps(query).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": token,
            },
        )
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        issue = data.get("data", {}).get("issue", {})
        return {
            "id": issue.get("id", ""),
            "title": issue.get("title", ""),
            "description": issue.get("description", ""),
            "priority": issue.get("priority", {}).get("label", ""),
            "assignee": issue.get("assignee", {}).get("name", "") if issue.get("assignee") else "",
            "status": issue.get("state", {}).get("name", ""),
        }

    def update_status(self, ticket_id: str, status: str, comment: str = "") -> bool:
        token = self._get_token()
        mutation = {
            "query": "mutation($id: String!, $stateId: String!) { issueUpdate(id: $id, input: { stateId: $stateId }) { success } }",
            "variables": {"id": ticket_id, "stateId": status},
        }
        req = urllib.request.Request(
            self._api_url,
            data=json.dumps(mutation).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": token,
            },
        )
        try:
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read())
            return data.get("data", {}).get("issueUpdate", {}).get("success", False)
        except OSError:
            return False

    def ticket_to_milestone(self, ticket_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": _slugify(ticket_data.get("title", "untitled")),
            "description": ticket_data.get("title", ""),
            "spec_sections": ticket_data.get("description", ""),
            "depends_on": [],
        }


class JiraAdapter:
    def __init__(self, config: dict[str, Any]) -> None:
        self._api_url = config.get("api_url", "").rstrip("/")
        self._token_env = config.get("token_env", "JIRA_API_TOKEN")
        self._user_env = config.get("user_env", "JIRA_USER_EMAIL")

    def _auth_header(self) -> str:
        token = os.environ.get(self._token_env, "")
        user = os.environ.get(self._user_env, "")
        if not token:
            raise ValueError(f"Missing token: env var '{self._token_env}' not set")
        creds = base64.b64encode(f"{user}:{token}".encode()).decode()
        return f"Basic {creds}"

    def fetch_ticket(self, ticket_id: str) -> dict[str, Any]:
        auth = self._auth_header()
        url = f"{self._api_url}/rest/api/3/issue/{ticket_id}"
        req = urllib.request.Request(url, headers={"Authorization": auth, "Accept": "application/json"})
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        fields = data.get("fields", {})
        return {
            "id": data.get("key", ""),
            "title": fields.get("summary", ""),
            "description": fields.get("description", ""),
            "priority": fields.get("priority", {}).get("name", "") if fields.get("priority") else "",
            "assignee": fields.get("assignee", {}).get("displayName", "") if fields.get("assignee") else "",
            "status": fields.get("status", {}).get("name", ""),
        }

    def update_status(self, ticket_id: str, status: str, comment: str = "") -> bool:
        auth = self._auth_header()
        if comment:
            url = f"{self._api_url}/rest/api/3/issue/{ticket_id}/comment"
            body = json.dumps({"body": {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": comment}]}]}}).encode()
            req = urllib.request.Request(
                url, data=body, method="POST",
                headers={"Authorization": auth, "Content-Type": "application/json"},
            )
            try:
                urllib.request.urlopen(req, timeout=15)
            except OSError:
                return False
        return True

    def ticket_to_milestone(self, ticket_data: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": _slugify(ticket_data.get("title", "untitled")),
            "description": ticket_data.get("title", ""),
            "spec_sections": ticket_data.get("description", ""),
            "depends_on": [],
        }


def create_tracker(config: dict[str, Any]) -> TrackerAdapter | None:
    tracker_config = config.get("integrations", {}).get("tracker")
    if not tracker_config:
        return None
    tracker_type = tracker_config.get("type", "")
    if tracker_type == "linear":
        return LinearAdapter(tracker_config)
    if tracker_type == "jira":
        return JiraAdapter(tracker_config)
    return None
```

- [ ] **Step 4: Run tests -- expect PASS**

```bash
cd superpower-workflow && python -m pytest tests/test_tracker.py -x -q
```

- [ ] **Step 5: Lint + format**

```bash
cd superpower-workflow && python -m ruff check src/superpower_workflow/integrations/tracker.py tests/test_tracker.py && python -m ruff format --check src/superpower_workflow/integrations/tracker.py tests/test_tracker.py
```

- [ ] **Step 6: Commit**

```bash
cd superpower-workflow && git add src/superpower_workflow/integrations/tracker.py tests/test_tracker.py && git commit -m "feat: add Linear and Jira tracker adapters with fetch/update/milestone

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: CI wait + log retrieval

**Files:**
- New: `src/superpower_workflow/integrations/ci_fix.py`
- New: `tests/test_ci_fix.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_ci_fix.py
from __future__ import annotations

import json
from subprocess import CompletedProcess
from unittest.mock import call, patch

import pytest

from superpower_workflow.integrations.ci_fix import CIResult, get_failure_logs, wait_for_ci


class TestWaitForCi:
    def test_returns_passed_on_success(self):
        run_data = [{"status": "completed", "conclusion": "success", "databaseId": 100}]
        with patch("superpower_workflow.integrations.ci_fix.subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(run_data), stderr=""
            )
            result = wait_for_ci(".", timeout_seconds=5, poll_interval_seconds=1)
        assert result.status == "passed"

    def test_returns_failed_on_failure(self):
        run_data = [{"status": "completed", "conclusion": "failure", "databaseId": 101}]
        with patch("superpower_workflow.integrations.ci_fix.subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(run_data), stderr=""
            )
            result = wait_for_ci(".", timeout_seconds=5, poll_interval_seconds=1)
        assert result.status == "failed"
        assert result.run_id == "101"

    def test_polls_until_completed(self):
        pending = [{"status": "in_progress", "conclusion": None, "databaseId": 102}]
        done = [{"status": "completed", "conclusion": "success", "databaseId": 102}]
        responses = [
            CompletedProcess(args=[], returncode=0, stdout=json.dumps(pending), stderr=""),
            CompletedProcess(args=[], returncode=0, stdout=json.dumps(done), stderr=""),
        ]
        with (
            patch("superpower_workflow.integrations.ci_fix.subprocess.run", side_effect=responses),
            patch("superpower_workflow.integrations.ci_fix.time.sleep"),
        ):
            result = wait_for_ci(".", timeout_seconds=120, poll_interval_seconds=1)
        assert result.status == "passed"

    def test_returns_timeout_when_exceeded(self):
        pending = [{"status": "in_progress", "conclusion": None, "databaseId": 103}]
        with (
            patch("superpower_workflow.integrations.ci_fix.subprocess.run") as mock_run,
            patch("superpower_workflow.integrations.ci_fix.time.sleep"),
            patch("superpower_workflow.integrations.ci_fix.time.monotonic", side_effect=[0, 0, 700]),
        ):
            mock_run.return_value = CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(pending), stderr=""
            )
            result = wait_for_ci(".", timeout_seconds=600, poll_interval_seconds=30)
        assert result.status == "timeout"

    def test_handles_empty_run_list(self):
        with patch("superpower_workflow.integrations.ci_fix.subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(
                args=[], returncode=0, stdout="[]", stderr=""
            )
            result = wait_for_ci(".", timeout_seconds=5, poll_interval_seconds=1)
        assert result.status == "timeout"


class TestGetFailureLogs:
    def test_returns_log_lines(self):
        logs = "step 1: OK\nstep 2: FAIL\nError: module not found\n" * 10
        with patch("superpower_workflow.integrations.ci_fix.subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(
                args=[], returncode=0, stdout=logs, stderr=""
            )
            result = get_failure_logs("101", ".")
        assert "FAIL" in result
        assert "Error" in result

    def test_truncates_to_max_lines(self):
        logs = "\n".join(f"line {i}" for i in range(500))
        with patch("superpower_workflow.integrations.ci_fix.subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(
                args=[], returncode=0, stdout=logs, stderr=""
            )
            result = get_failure_logs("101", ".", max_lines=200)
        assert result.count("\n") <= 200

    def test_returns_empty_on_failure(self):
        with patch("superpower_workflow.integrations.ci_fix.subprocess.run") as mock_run:
            mock_run.return_value = CompletedProcess(
                args=[], returncode=1, stdout="", stderr="not found"
            )
            result = get_failure_logs("999", ".")
        assert result == ""
```

- [ ] **Step 2: Run tests -- expect FAIL**

```bash
cd superpower-workflow && python -m pytest tests/test_ci_fix.py -x -q 2>&1 | head -20
```

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/integrations/ci_fix.py
from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass


@dataclass
class CIResult:
    status: str  # "passed", "failed", "timeout"
    run_id: str = ""
    conclusion: str = ""


def wait_for_ci(
    cwd: str,
    timeout_seconds: int = 600,
    poll_interval_seconds: int = 30,
) -> CIResult:
    deadline = time.monotonic() + timeout_seconds
    while True:
        result = subprocess.run(
            ["gh", "run", "list", "--limit", "1", "--json", "status,conclusion,databaseId"],
            capture_output=True, text=True, cwd=cwd, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            runs = json.loads(result.stdout)
            if runs:
                run = runs[0]
                run_id = str(run.get("databaseId", ""))
                status = run.get("status", "")
                conclusion = run.get("conclusion", "")
                if status == "completed":
                    if conclusion == "success":
                        return CIResult(status="passed", run_id=run_id, conclusion=conclusion)
                    return CIResult(status="failed", run_id=run_id, conclusion=conclusion)
        if time.monotonic() >= deadline:
            return CIResult(status="timeout")
        time.sleep(poll_interval_seconds)


def get_failure_logs(run_id: str, cwd: str, max_lines: int = 200) -> str:
    result = subprocess.run(
        ["gh", "run", "view", run_id, "--log-failed"],
        capture_output=True, text=True, cwd=cwd, timeout=60,
    )
    if result.returncode != 0:
        return ""
    lines = result.stdout.strip().split("\n")
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests -- expect PASS**

```bash
cd superpower-workflow && python -m pytest tests/test_ci_fix.py -x -q
```

- [ ] **Step 5: Lint + format**

```bash
cd superpower-workflow && python -m ruff check src/superpower_workflow/integrations/ci_fix.py tests/test_ci_fix.py && python -m ruff format --check src/superpower_workflow/integrations/ci_fix.py tests/test_ci_fix.py
```

- [ ] **Step 6: Commit**

```bash
cd superpower-workflow && git add src/superpower_workflow/integrations/ci_fix.py tests/test_ci_fix.py && git commit -m "feat: add CI status polling and failure log retrieval

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: CI fix loop

**Files:**
- Edit: `src/superpower_workflow/integrations/ci_fix.py`
- Edit: `tests/test_ci_fix.py`

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_ci_fix.py
from superpower_workflow.integrations.ci_fix import ci_fix_loop
from superpower_workflow.runner import ClaudeResult


class TestCiFixLoop:
    def _ci_config(self, **overrides):
        cfg = {
            "enabled": True,
            "max_fix_attempts": 3,
            "wait_timeout_seconds": 600,
            "poll_interval_seconds": 1,
        }
        cfg.update(overrides)
        return cfg

    def test_returns_true_when_ci_passes_first_try(self):
        def mock_wait(cwd, **kw):
            return CIResult(status="passed", run_id="100")

        with patch("superpower_workflow.integrations.ci_fix.wait_for_ci", side_effect=mock_wait):
            success, cost = ci_fix_loop(
                cwd=".",
                ci_config=self._ci_config(),
                run_claude_fn=lambda *a, **kw: ClaudeResult(),
                model="opus",
                system_prompt="",
            )
        assert success is True
        assert cost == 0.0

    def test_fixes_then_passes(self):
        wait_results = [
            CIResult(status="failed", run_id="101"),
            CIResult(status="passed", run_id="102"),
        ]
        call_count = [0]

        def mock_wait(cwd, **kw):
            idx = min(call_count[0], len(wait_results) - 1)
            call_count[0] += 1
            return wait_results[idx]

        def mock_claude(*a, **kw):
            return ClaudeResult(cost_usd=2.0)

        with (
            patch("superpower_workflow.integrations.ci_fix.wait_for_ci", side_effect=mock_wait),
            patch("superpower_workflow.integrations.ci_fix.get_failure_logs", return_value="error log"),
            patch("superpower_workflow.integrations.ci_fix.subprocess.run") as mock_sub,
        ):
            mock_sub.return_value = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            success, cost = ci_fix_loop(
                cwd=".",
                ci_config=self._ci_config(),
                run_claude_fn=mock_claude,
                model="opus",
                system_prompt="",
            )
        assert success is True
        assert cost == 2.0

    def test_all_attempts_fail(self):
        def mock_wait(cwd, **kw):
            return CIResult(status="failed", run_id="200")

        def mock_claude(*a, **kw):
            return ClaudeResult(cost_usd=1.0)

        with (
            patch("superpower_workflow.integrations.ci_fix.wait_for_ci", side_effect=mock_wait),
            patch("superpower_workflow.integrations.ci_fix.get_failure_logs", return_value="err"),
            patch("superpower_workflow.integrations.ci_fix.subprocess.run") as mock_sub,
        ):
            mock_sub.return_value = CompletedProcess(args=[], returncode=0, stdout="", stderr="")
            success, cost = ci_fix_loop(
                cwd=".",
                ci_config=self._ci_config(max_fix_attempts=2),
                run_claude_fn=mock_claude,
                model="opus",
                system_prompt="",
            )
        assert success is False
        assert cost == 2.0

    def test_timeout_on_initial_wait(self):
        def mock_wait(cwd, **kw):
            return CIResult(status="timeout")

        with patch("superpower_workflow.integrations.ci_fix.wait_for_ci", side_effect=mock_wait):
            success, cost = ci_fix_loop(
                cwd=".",
                ci_config=self._ci_config(),
                run_claude_fn=lambda *a, **kw: ClaudeResult(),
                model="opus",
                system_prompt="",
            )
        assert success is False
        assert cost == 0.0
```

- [ ] **Step 2: Run tests -- expect FAIL**

```bash
cd superpower-workflow && python -m pytest tests/test_ci_fix.py::TestCiFixLoop -x -q 2>&1 | head -20
```

- [ ] **Step 3: Implement** (append to ci_fix.py)

```python
# append to src/superpower_workflow/integrations/ci_fix.py
from typing import Any, Callable


def ci_fix_loop(
    cwd: str,
    ci_config: dict[str, Any],
    run_claude_fn: Callable,
    model: str = "opus",
    system_prompt: str = "",
    fallback_model: str | None = None,
) -> tuple[bool, float]:
    timeout = ci_config.get("wait_timeout_seconds", 600)
    poll = ci_config.get("poll_interval_seconds", 30)
    max_attempts = ci_config.get("max_fix_attempts", 3)
    fix_model = ci_config.get("model", model)
    total_cost = 0.0

    result = wait_for_ci(cwd, timeout_seconds=timeout, poll_interval_seconds=poll)
    if result.status == "passed":
        return True, 0.0
    if result.status == "timeout":
        return False, 0.0

    for attempt in range(max_attempts):
        logs = get_failure_logs(result.run_id, cwd)
        prompt = (
            f"CI failed. Logs:\n{logs}\n"
            f"Fix the issue. Commit the fix."
        )
        r = run_claude_fn(
            prompt,
            model=fix_model,
            effort="high",
            budget=10.0,
            cwd=cwd,
            system_prompt=system_prompt,
            fallback_model=fallback_model,
        )
        total_cost += r.cost_usd
        push = subprocess.run(["git", "push"], capture_output=True, cwd=cwd, timeout=60)
        if push.returncode != 0:
            continue

        result = wait_for_ci(cwd, timeout_seconds=timeout, poll_interval_seconds=poll)
        if result.status == "passed":
            return True, total_cost

    return False, total_cost
```

- [ ] **Step 4: Run tests -- expect PASS**

```bash
cd superpower-workflow && python -m pytest tests/test_ci_fix.py -x -q
```

- [ ] **Step 5: Lint + format**

```bash
cd superpower-workflow && python -m ruff check src/superpower_workflow/integrations/ci_fix.py tests/test_ci_fix.py && python -m ruff format --check src/superpower_workflow/integrations/ci_fix.py tests/test_ci_fix.py
```

- [ ] **Step 6: Commit**

```bash
cd superpower-workflow && git add src/superpower_workflow/integrations/ci_fix.py tests/test_ci_fix.py && git commit -m "feat: add CI fix loop with max attempts and cost tracking

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: State -- new step values for CI fix

**Files:**
- Edit: `src/superpower_workflow/state.py`
- Edit: `tests/test_state.py`

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_state.py
def test_ci_wait_step_roundtrips(tmp_path):
    from superpower_workflow.state import WorkflowState, load_state, save_state

    state = WorkflowState(current_step="ci_wait")
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    save_state(claude_dir, state)
    loaded = load_state(claude_dir)
    assert loaded.current_step == "ci_wait"


def test_ci_fix_step_roundtrips(tmp_path):
    from superpower_workflow.state import WorkflowState, load_state, save_state

    state = WorkflowState(current_step="ci_fix")
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    save_state(claude_dir, state)
    loaded = load_state(claude_dir)
    assert loaded.current_step == "ci_fix"


def test_ci_fix_failed_step_roundtrips(tmp_path):
    from superpower_workflow.state import WorkflowState, load_state, save_state

    state = WorkflowState(current_step="ci_fix_failed")
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    save_state(claude_dir, state)
    loaded = load_state(claude_dir)
    assert loaded.current_step == "ci_fix_failed"


def test_ci_step_values_documented():
    """Verify CI step values are in VALID_STEPS constant."""
    from superpower_workflow.state import VALID_STEPS

    assert "ci_wait" in VALID_STEPS
    assert "ci_fix" in VALID_STEPS
    assert "ci_fix_failed" in VALID_STEPS
```

- [ ] **Step 2: Run tests -- expect FAIL** (VALID_STEPS doesn't exist yet)

```bash
cd superpower-workflow && python -m pytest tests/test_state.py -x -q 2>&1 | head -20
```

- [ ] **Step 3: Implement** (add VALID_STEPS to state.py)

Add after the `LOCK_FILE` constant in `state.py`:

```python
VALID_STEPS = frozenset({
    "plan", "implement", "review", "push",
    "quality_check_b", "quality_check_c",
    "ci_wait", "ci_fix", "ci_fix_failed",
})
```

- [ ] **Step 4: Run tests -- expect PASS**

```bash
cd superpower-workflow && python -m pytest tests/test_state.py -x -q
```

- [ ] **Step 5: Lint + format**

```bash
cd superpower-workflow && python -m ruff check src/superpower_workflow/state.py tests/test_state.py && python -m ruff format --check src/superpower_workflow/state.py tests/test_state.py
```

- [ ] **Step 6: Commit**

```bash
cd superpower-workflow && git add src/superpower_workflow/state.py tests/test_state.py && git commit -m "feat: add CI fix step values to workflow state

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: Config -- integrations section + template + init

**Files:**
- Edit: `templates/workflow.json`
- Edit: `src/superpower_workflow/cli.py`
- Edit: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_cli.py

def test_init_config_has_integrations_section(tmp_path):
    _cmd_init(tmp_path)
    config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    assert "integrations" in config
    assert "github" in config["integrations"]
    assert "slack" in config["integrations"]
    assert "ci" in config["integrations"]


def test_init_integrations_github_defaults(tmp_path):
    _cmd_init(tmp_path)
    config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    gh = config["integrations"]["github"]
    assert gh["default_repo"] == ""
    assert gh["auto_pr"] is False
    assert gh["issue_label_map"] == {"bug": "fix", "feature": "feature", "refactor": "refactor"}


def test_init_integrations_ci_defaults(tmp_path):
    _cmd_init(tmp_path)
    config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    ci = config["integrations"]["ci"]
    assert ci["enabled"] is False
    assert ci["max_fix_attempts"] == 3
    assert ci["wait_timeout_seconds"] == 600
    assert ci["poll_interval_seconds"] == 30


def test_init_integrations_slack_defaults(tmp_path):
    _cmd_init(tmp_path)
    config = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    slack = config["integrations"]["slack"]
    assert slack["webhook_url_env"] == ""
    assert "milestone_start" in slack["events"]
    assert "milestone_complete" in slack["events"]
    assert "milestone_failed" in slack["events"]
```

- [ ] **Step 2: Run tests -- expect FAIL**

```bash
cd superpower-workflow && python -m pytest tests/test_cli.py::test_init_config_has_integrations_section -x -q 2>&1 | head -20
```

- [ ] **Step 3: Implement**

Update `_cmd_init` in `cli.py` to add integrations section to `default_config`:

```python
        "integrations": {
            "github": {
                "default_repo": "",
                "auto_pr": False,
                "issue_label_map": {"bug": "fix", "feature": "feature", "refactor": "refactor"},
            },
            "slack": {
                "webhook_url_env": "",
                "events": ["milestone_start", "milestone_complete", "milestone_failed", "ci_fix"],
            },
            "ci": {
                "enabled": False,
                "max_fix_attempts": 3,
                "wait_timeout_seconds": 600,
                "poll_interval_seconds": 30,
            },
            "tracker": {},
        },
```

Update `templates/workflow.json` to add the same section (before `"notification_webhook"`).

- [ ] **Step 4: Run tests -- expect PASS**

```bash
cd superpower-workflow && python -m pytest tests/test_cli.py -x -q
```

- [ ] **Step 5: Lint + format**

```bash
cd superpower-workflow && python -m ruff check src/superpower_workflow/cli.py tests/test_cli.py && python -m ruff format --check src/superpower_workflow/cli.py tests/test_cli.py
```

- [ ] **Step 6: Commit**

```bash
cd superpower-workflow && git add src/superpower_workflow/cli.py templates/workflow.json tests/test_cli.py && git commit -m "feat: add integrations config section to workflow.json template

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: CLI -- --from-issue + --from-ticket flags

**Files:**
- Edit: `src/superpower_workflow/cli.py`
- Edit: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_cli.py

def test_parser_run_from_issue_flag():
    args = build_parser().parse_args(["run", "--from-issue", "42"])
    assert args.from_issue == "42"


def test_parser_run_from_issue_full_ref():
    args = build_parser().parse_args(["run", "--from-issue", "owner/repo#42"])
    assert args.from_issue == "owner/repo#42"


def test_parser_run_from_ticket_flag():
    args = build_parser().parse_args(["run", "--from-ticket", "LIN-42"])
    assert args.from_ticket == "LIN-42"


def test_parser_run_from_issue_default_none():
    args = build_parser().parse_args(["run"])
    assert args.from_issue is None


def test_parser_run_from_ticket_default_none():
    args = build_parser().parse_args(["run"])
    assert args.from_ticket is None
```

- [ ] **Step 2: Run tests -- expect FAIL**

```bash
cd superpower-workflow && python -m pytest tests/test_cli.py::test_parser_run_from_issue_flag -x -q 2>&1 | head -20
```

- [ ] **Step 3: Implement**

Add to `build_parser()` in `cli.py`, inside the `run_p` section:

```python
    run_p.add_argument("--from-issue", dest="from_issue", help="GitHub issue number or owner/repo#N")
    run_p.add_argument("--from-ticket", dest="from_ticket", help="Tracker ticket ID (e.g. LIN-42, PROJ-123)")
```

**Note:** The `main()` function's `run` handler will be updated in Task 13 (when the orchestrator gains the `from_issue`/`from_ticket` params) to pass these through:

```python
        orch.run(
            ...
            from_issue=getattr(args, "from_issue", None),
            from_ticket=getattr(args, "from_ticket", None),
        )
```

- [ ] **Step 4: Run tests -- expect PASS**

```bash
cd superpower-workflow && python -m pytest tests/test_cli.py -x -q
```

- [ ] **Step 5: Lint + format**

```bash
cd superpower-workflow && python -m ruff check src/superpower_workflow/cli.py tests/test_cli.py && python -m ruff format --check src/superpower_workflow/cli.py tests/test_cli.py
```

- [ ] **Step 6: Commit**

```bash
cd superpower-workflow && git add src/superpower_workflow/cli.py tests/test_cli.py && git commit -m "feat: add --from-issue and --from-ticket CLI flags to sw run

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: Orchestrator -- notification hooks at milestone lifecycle

**Files:**
- Edit: `src/superpower_workflow/orchestrator.py`
- Edit: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_orchestrator.py

def test_orchestrator_sends_notification_on_milestone_start(tmp_path):
    _config(tmp_path)
    cfg = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    cfg["integrations"] = {
        "slack": {"webhook_url_env": "SLACK_URL", "events": ["milestone_start"]},
        "github": {"default_repo": "", "auto_pr": False, "issue_label_map": {}},
        "ci": {"enabled": False},
        "tracker": {},
    }
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(cfg))

    notifications = []

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.send_notification") as mock_notify,
    ):
        mock_notify.side_effect = lambda *a, **kw: notifications.append(a)
        orch = Orchestrator(tmp_path)
        orch.run()

    events = [n[1] for n in notifications]
    assert "milestone_start" in events


def test_orchestrator_sends_notification_on_milestone_complete(tmp_path):
    _config(tmp_path)
    cfg = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    cfg["integrations"] = {
        "slack": {"webhook_url_env": "SLACK_URL", "events": ["milestone_complete"]},
        "github": {"default_repo": "", "auto_pr": False, "issue_label_map": {}},
        "ci": {"enabled": False},
        "tracker": {},
    }
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(cfg))

    notifications = []

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.send_notification") as mock_notify,
    ):
        mock_notify.side_effect = lambda *a, **kw: notifications.append(a)
        orch = Orchestrator(tmp_path)
        orch.run()

    events = [n[1] for n in notifications]
    assert "milestone_complete" in events


def test_orchestrator_sends_notification_on_milestone_failed(tmp_path):
    _config(tmp_path)
    cfg = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    cfg["integrations"] = {
        "slack": {"webhook_url_env": "SLACK_URL", "events": ["milestone_failed"]},
        "github": {"default_repo": "", "auto_pr": False, "issue_label_map": {}},
        "ci": {"enabled": False},
        "tracker": {},
    }
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(cfg))

    fail_count = [0]

    def failing_claude(*a, **kw):
        fail_count[0] += 1
        return ClaudeResult(is_error=True, text="fail")

    notifications = []

    with (
        patch("superpower_workflow.orchestrator.run_claude", side_effect=failing_claude),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.send_notification") as mock_notify,
        patch("superpower_workflow.orchestrator.time.sleep"),
    ):
        mock_notify.side_effect = lambda *a, **kw: notifications.append(a)
        orch = Orchestrator(tmp_path)
        orch.run()

    events = [n[1] for n in notifications]
    assert "milestone_failed" in events
```

- [ ] **Step 2: Run tests -- expect FAIL**

```bash
cd superpower-workflow && python -m pytest tests/test_orchestrator.py::test_orchestrator_sends_notification_on_milestone_start -x -q 2>&1 | head -20
```

- [ ] **Step 3: Implement**

Add import at top of `orchestrator.py`:

```python
from superpower_workflow.integrations.notifier import send_notification
```

In `Orchestrator.__init__`, read integrations config:

```python
        self._integrations = self.config.get("integrations", {})
        self._slack_config = self._integrations.get("slack", {})
```

Add `_notify` helper method:

```python
    def _notify(self, event: str, payload: dict) -> None:
        if self._slack_config:
            send_notification(self._slack_config, event, payload)
```

In the milestone loop, add notifications at lifecycle points:

After `MilestoneStarted` emit:
```python
                self._notify("milestone_start", {"milestone": name})
```

After `MilestoneCompleted` emit:
```python
                        self._notify("milestone_complete", {
                            "milestone": name,
                            "cost_usd": round(cost, 2),
                            "test_count": 0,
                        })
```

After `MilestoneFailed` emit:
```python
                            self._notify("milestone_failed", {
                                "milestone": name,
                                "phase": e.phase,
                                "reason": str(e),
                            })
```

- [ ] **Step 4: Run tests -- expect PASS**

```bash
cd superpower-workflow && python -m pytest tests/test_orchestrator.py -x -q
```

- [ ] **Step 5: Lint + format**

```bash
cd superpower-workflow && python -m ruff check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py && python -m ruff format --check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
```

- [ ] **Step 6: Commit**

```bash
cd superpower-workflow && git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py && git commit -m "feat: add Slack notification hooks at milestone lifecycle events

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 11: Orchestrator -- Phase E CI self-correction

**Files:**
- Edit: `src/superpower_workflow/orchestrator.py`
- Edit: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_orchestrator.py

def test_orchestrator_runs_phase_e_when_ci_enabled(tmp_path):
    _config(tmp_path)
    cfg = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    cfg["integrations"] = {
        "github": {"default_repo": "", "auto_pr": False, "issue_label_map": {}},
        "slack": {},
        "ci": {"enabled": True, "max_fix_attempts": 3, "wait_timeout_seconds": 5, "poll_interval_seconds": 1},
        "tracker": {},
    }
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(cfg))

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.ci_fix_loop") as mock_ci,
        patch("superpower_workflow.orchestrator.send_notification"),
    ):
        mock_ci.return_value = (True, 0.5)
        orch = Orchestrator(tmp_path)
        orch.run()

    mock_ci.assert_called_once()
    call_kw = mock_ci.call_args
    assert call_kw[1]["ci_config"]["enabled"] is True


def test_orchestrator_skips_phase_e_when_ci_disabled(tmp_path):
    _config(tmp_path)
    cfg = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    cfg["integrations"] = {
        "github": {"default_repo": "", "auto_pr": False, "issue_label_map": {}},
        "slack": {},
        "ci": {"enabled": False},
        "tracker": {},
    }
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(cfg))

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.ci_fix_loop") as mock_ci,
        patch("superpower_workflow.orchestrator.send_notification"),
    ):
        orch = Orchestrator(tmp_path)
        orch.run()

    mock_ci.assert_not_called()


def test_orchestrator_phase_e_cost_added(tmp_path):
    _config(tmp_path)
    cfg = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    cfg["integrations"] = {
        "github": {"default_repo": "", "auto_pr": False, "issue_label_map": {}},
        "slack": {},
        "ci": {"enabled": True, "max_fix_attempts": 2, "wait_timeout_seconds": 5, "poll_interval_seconds": 1},
        "tracker": {},
    }
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(cfg))

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result(cost=1.0)),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.ci_fix_loop") as mock_ci,
        patch("superpower_workflow.orchestrator.send_notification"),
    ):
        mock_ci.return_value = (True, 3.0)
        orch = Orchestrator(tmp_path)
        orch.run()

    state = load_state(tmp_path / ".claude")
    assert state.total_cost_usd >= 7.0  # 4 phases * 1.0 + 3.0 CI fix


def test_orchestrator_phase_e_failure_does_not_fail_milestone(tmp_path):
    _config(tmp_path)
    cfg = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    cfg["integrations"] = {
        "github": {"default_repo": "", "auto_pr": False, "issue_label_map": {}},
        "slack": {},
        "ci": {"enabled": True, "max_fix_attempts": 1, "wait_timeout_seconds": 5, "poll_interval_seconds": 1},
        "tracker": {},
    }
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(cfg))

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.ci_fix_loop") as mock_ci,
        patch("superpower_workflow.orchestrator.send_notification"),
    ):
        mock_ci.return_value = (False, 2.0)
        orch = Orchestrator(tmp_path)
        orch.run()

    state = load_state(tmp_path / ".claude")
    assert "m1" in state.completed  # milestone still completes
```

- [ ] **Step 2: Run tests -- expect FAIL**

```bash
cd superpower-workflow && python -m pytest tests/test_orchestrator.py::test_orchestrator_runs_phase_e_when_ci_enabled -x -q 2>&1 | head -20
```

- [ ] **Step 3: Implement**

Add import at top of `orchestrator.py`:

```python
from superpower_workflow.integrations.ci_fix import ci_fix_loop
```

In `_run_milestone`, after Phase D and SBOM/signing, add Phase E:

```python
        # Phase E: CI Self-Correction
        ci_config = self._integrations.get("ci", {})
        if ci_config.get("enabled", False):
            self.state.current_step = "ci_wait"
            save_state(self.claude_dir, self.state)
            logger.log("PHASE_E_START")
            self._telemetry.emit(PhaseStarted(milestone=name, phase="ci_fix"))

            self.state.current_step = "ci_fix"
            save_state(self.claude_dir, self.state)

            ci_success, ci_cost = ci_fix_loop(
                cwd=self.cwd,
                ci_config=ci_config,
                run_claude_fn=run_claude,
                model=self.config["model"],
                system_prompt=self.sys_prompt,
                fallback_model=self.config.get("fallback_model"),
            )
            cost += ci_cost

            if ci_success:
                logger.log("PHASE_E_COMPLETE", status="passed", cost=round(ci_cost, 2))
            else:
                self.state.current_step = "ci_fix_failed"
                save_state(self.claude_dir, self.state)
                logger.log("PHASE_E_COMPLETE", status="failed", cost=round(ci_cost, 2))
                self._notify("ci_fix", {
                    "milestone": name,
                    "attempt": ci_config.get("max_fix_attempts", 3),
                    "max_attempts": ci_config.get("max_fix_attempts", 3),
                    "status": "all_failed",
                })

            self._telemetry.emit(
                PhaseCompleted(
                    milestone=name,
                    phase="ci_fix",
                    cost_usd=round(ci_cost, 2),
                    duration_ms=0,
                    session_id="",
                )
            )
            self._audit.append(
                "PHASE_COMPLETE",
                run_id=self.state.run_id,
                milestone=name,
                data={"phase": "ci_fix", "cost": round(ci_cost, 2), "success": ci_success},
            )
```

- [ ] **Step 4: Run tests -- expect PASS**

```bash
cd superpower-workflow && python -m pytest tests/test_orchestrator.py -x -q
```

- [ ] **Step 5: Lint + format**

```bash
cd superpower-workflow && python -m ruff check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py && python -m ruff format --check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
```

- [ ] **Step 6: Commit**

```bash
cd superpower-workflow && git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py && git commit -m "feat: add Phase E CI self-correction to orchestrator

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 12: Orchestrator -- PR auto-creation after milestone

**Files:**
- Edit: `src/superpower_workflow/orchestrator.py`
- Edit: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_orchestrator.py

def test_orchestrator_creates_pr_when_enabled(tmp_path):
    _config(tmp_path)
    cfg = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    cfg["integrations"] = {
        "github": {"default_repo": "owner/repo", "auto_pr": True, "issue_label_map": {}},
        "slack": {},
        "ci": {"enabled": False},
        "tracker": {},
    }
    cfg["git_strategy"] = "branch"
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(cfg))

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.send_notification"),
        patch("superpower_workflow.orchestrator.create_pr") as mock_pr,
    ):
        mock_pr.return_value = "https://github.com/owner/repo/pull/1"
        orch = Orchestrator(tmp_path)
        orch.run()

    mock_pr.assert_called_once()
    call_kw = mock_pr.call_args
    assert "m1" in call_kw[1]["title"] or "m1" in call_kw[0][0]


def test_orchestrator_skips_pr_when_disabled(tmp_path):
    _config(tmp_path)
    cfg = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    cfg["integrations"] = {
        "github": {"default_repo": "", "auto_pr": False, "issue_label_map": {}},
        "slack": {},
        "ci": {"enabled": False},
        "tracker": {},
    }
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(cfg))

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.send_notification"),
        patch("superpower_workflow.orchestrator.create_pr") as mock_pr,
    ):
        orch = Orchestrator(tmp_path)
        orch.run()

    mock_pr.assert_not_called()


def test_orchestrator_pr_on_main_strategy(tmp_path):
    """When git_strategy=main, PR creation is skipped (no separate branch)."""
    _config(tmp_path)
    cfg = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    cfg["integrations"] = {
        "github": {"default_repo": "owner/repo", "auto_pr": True, "issue_label_map": {}},
        "slack": {},
        "ci": {"enabled": False},
        "tracker": {},
    }
    cfg["git_strategy"] = "main"
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(cfg))

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.send_notification"),
        patch("superpower_workflow.orchestrator.create_pr") as mock_pr,
    ):
        orch = Orchestrator(tmp_path)
        orch.run()

    mock_pr.assert_not_called()
```

- [ ] **Step 2: Run tests -- expect FAIL**

```bash
cd superpower-workflow && python -m pytest tests/test_orchestrator.py::test_orchestrator_creates_pr_when_enabled -x -q 2>&1 | head -20
```

- [ ] **Step 3: Implement**

Add import at top of `orchestrator.py`:

```python
from superpower_workflow.integrations.github import create_pr, render_pr_body
```

In `_run_milestone`, after Phase E (or after Phase D if CI disabled), add PR creation:

```python
        # PR Auto-Creation
        gh_config = self._integrations.get("github", {})
        if gh_config.get("auto_pr", False) and self.config.get("git_strategy") != "main":
            branch = f"milestone/{name}"
            base = "main"
            changes = ""
            plan_sha = self.state.plan_commit_sha or ""
            if plan_sha:
                log_result = subprocess.run(
                    ["git", "log", "--oneline", f"{plan_sha}..HEAD"],
                    capture_output=True, text=True, cwd=self.cwd, timeout=10,
                )
                changes = log_result.stdout.strip() if log_result.returncode == 0 else ""
            body = render_pr_body(
                milestone=name,
                description=ms.get("description", ""),
                changes=changes,
                cost_usd=cost,
            )
            pr_url = create_pr(
                title=name,
                body=body,
                branch=branch,
                base=base,
                cwd=self.cwd,
                repo=gh_config.get("default_repo", ""),
            )
            if pr_url:
                logger.log("PR_CREATED", milestone=name, url=pr_url)
                self._audit.append(
                    "PR_CREATED",
                    run_id=self.state.run_id,
                    milestone=name,
                    data={"url": pr_url},
                )
```

- [ ] **Step 4: Run tests -- expect PASS**

```bash
cd superpower-workflow && python -m pytest tests/test_orchestrator.py -x -q
```

- [ ] **Step 5: Lint + format**

```bash
cd superpower-workflow && python -m ruff check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py && python -m ruff format --check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
```

- [ ] **Step 6: Commit**

```bash
cd superpower-workflow && git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py && git commit -m "feat: add PR auto-creation after milestone completion

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 13: Orchestrator -- issue/ticket ingestion flow

**Files:**
- Edit: `src/superpower_workflow/orchestrator.py`
- Edit: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing tests**

```python
# append to tests/test_orchestrator.py
# NOTE: also add MagicMock to the existing unittest.mock import at top of file:
# from unittest.mock import MagicMock, patch

from unittest.mock import MagicMock

def test_orchestrator_from_issue_creates_milestone(tmp_path):
    _config(tmp_path, milestones=[])
    cfg = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    cfg["integrations"] = {
        "github": {"default_repo": "owner/repo", "auto_pr": False, "issue_label_map": {"bug": "fix"}},
        "slack": {},
        "ci": {"enabled": False},
        "tracker": {},
    }
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(cfg))

    issue_data = {
        "title": "Fix login",
        "body": "Login is broken",
        "labels": [{"name": "bug"}],
        "assignees": [],
    }

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.send_notification"),
        patch("superpower_workflow.orchestrator.fetch_issue", return_value=issue_data),
    ):
        orch = Orchestrator(tmp_path)
        orch.run(from_issue="42")

    state = load_state(tmp_path / ".claude")
    assert "fix-login" in state.completed


def test_orchestrator_from_ticket_creates_milestone(tmp_path):
    _config(tmp_path, milestones=[])
    cfg = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    cfg["integrations"] = {
        "github": {"default_repo": "", "auto_pr": False, "issue_label_map": {}},
        "slack": {},
        "ci": {"enabled": False},
        "tracker": {"type": "linear", "api_url": "https://api.linear.app/graphql", "token_env": "T"},
    }
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(cfg))

    ticket_data = {
        "title": "Add dark mode",
        "description": "Dark mode for settings page",
        "priority": "High",
    }

    mock_adapter = MagicMock()
    mock_adapter.fetch_ticket.return_value = ticket_data
    mock_adapter.ticket_to_milestone.return_value = {
        "name": "add-dark-mode",
        "description": "Add dark mode",
        "spec_sections": "Dark mode for settings page",
        "depends_on": [],
    }

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.send_notification"),
        patch("superpower_workflow.orchestrator.create_tracker", return_value=mock_adapter),
    ):
        orch = Orchestrator(tmp_path)
        orch.run(from_ticket="LIN-42")

    state = load_state(tmp_path / ".claude")
    assert "add-dark-mode" in state.completed


def test_orchestrator_updates_tracker_on_milestone_complete(tmp_path):
    _config(tmp_path, milestones=[])
    cfg = json.loads((tmp_path / ".claude" / "workflow.json").read_text())
    cfg["integrations"] = {
        "github": {"default_repo": "", "auto_pr": False, "issue_label_map": {}},
        "slack": {},
        "ci": {"enabled": False},
        "tracker": {"type": "linear", "api_url": "https://api.linear.app/graphql", "token_env": "T"},
    }
    (tmp_path / ".claude" / "workflow.json").write_text(json.dumps(cfg))

    ticket_data = {"title": "Fix bug", "description": "Details", "priority": "High"}
    mock_adapter = MagicMock()
    mock_adapter.fetch_ticket.return_value = ticket_data
    mock_adapter.ticket_to_milestone.return_value = {
        "name": "fix-bug", "description": "Fix bug",
        "spec_sections": "Details", "depends_on": [],
    }

    with (
        patch("superpower_workflow.orchestrator.run_claude", return_value=_ok_result()),
        patch("superpower_workflow.orchestrator.subprocess.run", side_effect=_smart_subprocess),
        patch("superpower_workflow.orchestrator.send_notification"),
        patch("superpower_workflow.orchestrator.create_tracker", return_value=mock_adapter),
    ):
        orch = Orchestrator(tmp_path)
        orch.run(from_ticket="LIN-99")

    mock_adapter.update_status.assert_called_once()
    call_args = mock_adapter.update_status.call_args
    assert "LIN-99" in call_args[0] or call_args[1].get("ticket_id") == "LIN-99"
```

- [ ] **Step 2: Run tests -- expect FAIL**

```bash
cd superpower-workflow && python -m pytest tests/test_orchestrator.py::test_orchestrator_from_issue_creates_milestone -x -q 2>&1 | head -20
```

- [ ] **Step 3: Implement**

Add imports at top of `orchestrator.py`:

```python
from superpower_workflow.integrations.github import fetch_issue, issue_to_milestone
from superpower_workflow.integrations.tracker import create_tracker
```

Update `Orchestrator.run` signature:

```python
    def run(
        self,
        dry_run: bool = False,
        milestone_filter: str | None = None,
        from_ms: str | None = None,
        to_ms: str | None = None,
        phase_prefix: str | None = None,
        from_issue: str | None = None,
        from_ticket: str | None = None,
    ) -> None:
```

Store the ticket reference for later status update:

```python
        self._from_ticket = from_ticket
        self._tracker_adapter = None
```

Add ingestion logic at the top of `run()`, before `milestones = self._filter_milestones(...)`:

```python
        if from_issue:
            gh_config = self._integrations.get("github", {})
            issue_data = fetch_issue(
                from_issue,
                default_repo=gh_config.get("default_repo", ""),
                cwd=self.cwd,
            )
            ms = issue_to_milestone(issue_data, gh_config.get("issue_label_map"))
            self.config.setdefault("milestones", []).append(ms)

        if from_ticket:
            self._tracker_adapter = create_tracker(self.config)
            if self._tracker_adapter:
                ticket_data = self._tracker_adapter.fetch_ticket(from_ticket)
                ms = self._tracker_adapter.ticket_to_milestone(ticket_data)
                self.config.setdefault("milestones", []).append(ms)
```

In the milestone completion block (after `self.state.completed.append(name)`), add tracker status update:

```python
                        if self._from_ticket and self._tracker_adapter:
                            try:
                                self._tracker_adapter.update_status(
                                    self._from_ticket, "Done", comment=f"Milestone {name} completed"
                                )
                            except (OSError, ValueError):
                                logger.log("TRACKER_UPDATE_FAILED", ticket=self._from_ticket)
```

- [ ] **Step 4: Run tests -- expect PASS**

```bash
cd superpower-workflow && python -m pytest tests/test_orchestrator.py -x -q
```

- [ ] **Step 5: Lint + format**

```bash
cd superpower-workflow && python -m ruff check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py && python -m ruff format --check src/superpower_workflow/orchestrator.py tests/test_orchestrator.py
```

- [ ] **Step 6: Commit**

```bash
cd superpower-workflow && git add src/superpower_workflow/orchestrator.py tests/test_orchestrator.py && git commit -m "feat: add issue/ticket ingestion to orchestrator run flow

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 14: Integration package exports + gitignore

**Files:**
- Edit: `src/superpower_workflow/integrations/__init__.py`
- New: `tests/test_integrations_exports.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_integrations_exports.py
from __future__ import annotations


class TestIntegrationsExports:
    def test_notifier_exports(self):
        from superpower_workflow.integrations.notifier import format_message, send_notification

        assert callable(format_message)
        assert callable(send_notification)

    def test_github_exports(self):
        from superpower_workflow.integrations.github import (
            create_pr,
            fetch_issue,
            issue_to_milestone,
            parse_issue_ref,
            render_pr_body,
        )

        assert callable(create_pr)
        assert callable(fetch_issue)
        assert callable(issue_to_milestone)
        assert callable(parse_issue_ref)
        assert callable(render_pr_body)

    def test_tracker_exports(self):
        from superpower_workflow.integrations.tracker import (
            JiraAdapter,
            LinearAdapter,
            create_tracker,
        )

        assert callable(create_tracker)
        assert LinearAdapter is not None
        assert JiraAdapter is not None

    def test_ci_fix_exports(self):
        from superpower_workflow.integrations.ci_fix import (
            CIResult,
            ci_fix_loop,
            get_failure_logs,
            wait_for_ci,
        )

        assert callable(ci_fix_loop)
        assert callable(get_failure_logs)
        assert callable(wait_for_ci)
        assert CIResult is not None

    def test_package_all(self):
        import superpower_workflow.integrations as pkg

        assert hasattr(pkg, "__all__")
        expected = [
            "CIResult",
            "JiraAdapter",
            "LinearAdapter",
            "ci_fix_loop",
            "create_pr",
            "create_tracker",
            "fetch_issue",
            "format_message",
            "get_failure_logs",
            "issue_to_milestone",
            "parse_issue_ref",
            "render_pr_body",
            "send_notification",
            "wait_for_ci",
        ]
        for name in expected:
            assert name in pkg.__all__, f"Missing from __all__: {name}"
```

- [ ] **Step 2: Run tests -- expect FAIL**

```bash
cd superpower-workflow && python -m pytest tests/test_integrations_exports.py -x -q 2>&1 | head -20
```

- [ ] **Step 3: Implement**

```python
# src/superpower_workflow/integrations/__init__.py
from __future__ import annotations

from superpower_workflow.integrations.ci_fix import (
    CIResult,
    ci_fix_loop,
    get_failure_logs,
    wait_for_ci,
)
from superpower_workflow.integrations.github import (
    create_pr,
    fetch_issue,
    issue_to_milestone,
    parse_issue_ref,
    render_pr_body,
)
from superpower_workflow.integrations.notifier import format_message, send_notification
from superpower_workflow.integrations.tracker import (
    JiraAdapter,
    LinearAdapter,
    create_tracker,
)

__all__ = [
    "CIResult",
    "JiraAdapter",
    "LinearAdapter",
    "ci_fix_loop",
    "create_pr",
    "create_tracker",
    "fetch_issue",
    "format_message",
    "get_failure_logs",
    "issue_to_milestone",
    "parse_issue_ref",
    "render_pr_body",
    "send_notification",
    "wait_for_ci",
]
```

- [ ] **Step 4: Run tests -- expect PASS**

```bash
cd superpower-workflow && python -m pytest tests/test_integrations_exports.py -x -q
```

- [ ] **Step 5: Lint + format**

```bash
cd superpower-workflow && python -m ruff check src/superpower_workflow/integrations/ tests/test_integrations_exports.py && python -m ruff format --check src/superpower_workflow/integrations/ tests/test_integrations_exports.py
```

- [ ] **Step 6: Commit**

```bash
cd superpower-workflow && git add src/superpower_workflow/integrations/__init__.py tests/test_integrations_exports.py && git commit -m "feat: add integrations package __all__ exports

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 15: Full test suite + self-review

- [ ] **Step 1: Run all tests**

```bash
cd superpower-workflow && python -m pytest -q
```

- [ ] **Step 2: Lint + format**

```bash
cd superpower-workflow && python -m ruff check . && python -m ruff format --check .
```

- [ ] **Step 3: Spec coverage checklist**

| Spec section | Covered by |
|---|---|
| 2. GitHub Issue Ingestion | Task 2: parse_issue_ref, fetch_issue, issue_to_milestone |
| 3. Linear/Jira Tracker | Task 4: LinearAdapter, JiraAdapter, create_tracker |
| 4. CI Self-Correction | Tasks 5-6: wait_for_ci, get_failure_logs, ci_fix_loop |
| 5. Slack Notifications | Task 1: format_message, send_notification |
| 6. PR Auto-Creation | Task 3: render_pr_body, create_pr |
| 7. Files Changed | All files from spec table created |
| CLI: --from-issue | Task 9: CLI flag + Task 13: orchestrator ingestion |
| CLI: --from-ticket | Task 9: CLI flag + Task 13: orchestrator ingestion |
| Config: integrations section | Task 8: workflow.json template + init |
| State: ci_wait/ci_fix/ci_fix_failed | Task 7: VALID_STEPS |
| Orchestrator: Phase E | Task 11: CI fix after Phase D |
| Orchestrator: Notifications | Task 10: milestone lifecycle hooks |
| Orchestrator: PR creation | Task 12: after milestone completion |

- [ ] **Step 4: Placeholder scan** -- verify no TODO, FIXME, or placeholder text in source files

```bash
cd superpower-workflow && grep -r "TODO\|FIXME\|PLACEHOLDER\|CHANGEME" src/superpower_workflow/integrations/ || echo "No placeholders found"
```

- [ ] **Step 5: Type consistency** -- verify all new modules use `from __future__ import annotations`

```bash
cd superpower-workflow && head -1 src/superpower_workflow/integrations/*.py
```

- [ ] **Step 6: Final commit** (if any fixes needed)

```bash
cd superpower-workflow && git add -A && git commit -m "chore: sp5 self-review fixes

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Summary

| # | Task | Tests | Module |
|---|---|---|---|
| 1 | Notifier: format + send | ~8 | notifier.py |
| 2 | GitHub issue ingestion | ~8 | github.py |
| 3 | GitHub PR creation | ~6 | github.py |
| 4 | Tracker: Linear + Jira | ~10 | tracker.py |
| 5 | CI wait + logs | ~7 | ci_fix.py |
| 6 | CI fix loop | ~4 | ci_fix.py |
| 7 | State: CI steps | ~4 | state.py |
| 8 | Config: integrations | ~4 | cli.py + template |
| 9 | CLI: --from-issue/ticket | ~5 | cli.py |
| 10 | Orch: notifications | ~3 | orchestrator.py |
| 11 | Orch: Phase E | ~4 | orchestrator.py |
| 12 | Orch: PR creation | ~3 | orchestrator.py |
| 13 | Orch: issue/ticket ingestion | ~2 | orchestrator.py |
| 14 | Package exports | ~5 | __init__.py |
| 15 | Self-review | 0 | (verification only) |
| **Total** | | **~73** | |
