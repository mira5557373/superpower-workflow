from __future__ import annotations

import json
from io import BytesIO
from unittest.mock import patch

import pytest

from superpower_workflow.integrations.tracker import (
    JiraAdapter,
    LinearAdapter,
    create_tracker,
)


class TestLinearAdapter:
    def _make_adapter(self) -> LinearAdapter:
        return LinearAdapter(
            {
                "type": "linear",
                "api_url": "https://api.linear.app/graphql",
                "token_env": "LINEAR_API_TOKEN",
                "project_id": "proj-1",
            }
        )

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
        with (
            patch.dict("os.environ", {}, clear=True),
            pytest.raises(ValueError, match="token"),
        ):
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
        lookup_resp = BytesIO(b'{"data":{"workflowStates":{"nodes":[{"id":"state-done"}]}}}')
        mutation_resp = BytesIO(b'{"data":{"issueUpdate":{"success":true}}}')
        with (
            patch.dict("os.environ", {"LINEAR_API_TOKEN": "tok-123"}),
            patch("superpower_workflow.integrations.tracker.urllib.request.urlopen") as mock_url,
        ):
            mock_url.side_effect = [lookup_resp, mutation_resp]
            result = adapter.update_status("abc-123", "Done", comment="PR merged")
        assert result is True


class TestJiraAdapter:
    def _make_adapter(self) -> JiraAdapter:
        return JiraAdapter(
            {
                "type": "jira",
                "api_url": "https://mycompany.atlassian.net",
                "token_env": "JIRA_API_TOKEN",
                "user_env": "JIRA_USER_EMAIL",
            }
        )

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
        ticket = {
            "title": "Update API docs",
            "description": "Details",
            "priority": "Medium",
        }
        ms = adapter.ticket_to_milestone(ticket)
        assert ms["name"] == "update-api-docs"
        assert ms["depends_on"] == []

    def test_update_status(self):
        adapter = self._make_adapter()
        with (
            patch.dict("os.environ", {"JIRA_API_TOKEN": "tok-j", "JIRA_USER_EMAIL": "a@b.com"}),
            patch("superpower_workflow.integrations.tracker.urllib.request.urlopen") as mock_url,
        ):
            mock_url.return_value = BytesIO(b"{}")
            result = adapter.update_status("PROJ-123", "Done")
        assert result is True


class TestCreateTracker:
    def test_creates_linear_adapter(self):
        config = {
            "integrations": {
                "tracker": {
                    "type": "linear",
                    "api_url": "https://api.linear.app/graphql",
                    "token_env": "T",
                }
            }
        }
        adapter = create_tracker(config)
        assert isinstance(adapter, LinearAdapter)

    def test_creates_jira_adapter(self):
        config = {
            "integrations": {
                "tracker": {
                    "type": "jira",
                    "api_url": "https://jira.example.com",
                    "token_env": "T",
                }
            }
        }
        adapter = create_tracker(config)
        assert isinstance(adapter, JiraAdapter)

    def test_returns_none_for_unknown(self):
        config = {"integrations": {"tracker": {"type": "unknown"}}}
        assert create_tracker(config) is None

    def test_returns_none_when_no_tracker(self):
        assert create_tracker({}) is None
        assert create_tracker({"integrations": {}}) is None
