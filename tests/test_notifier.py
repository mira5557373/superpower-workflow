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
        with (
            patch.dict("os.environ", {"SLACK_WEBHOOK_URL": "https://hooks.example.com/abc"}),
            patch("superpower_workflow.integrations.notifier.urllib.request.urlopen") as mock_url,
        ):
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
        with (
            patch.dict("os.environ", {"SLACK_WEBHOOK_URL": "https://hooks.example.com/abc"}),
            patch("superpower_workflow.integrations.notifier.urllib.request.urlopen") as mock_url,
        ):
            result = send_notification(config, "milestone_complete", {"milestone": "m1"})
        assert result is False
        mock_url.assert_not_called()

    def test_noop_when_url_missing(self):
        config = {"webhook_url_env": "MISSING_VAR", "events": ["milestone_start"]}
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("superpower_workflow.integrations.notifier.urllib.request.urlopen") as mock_url,
        ):
            result = send_notification(config, "milestone_start", {"milestone": "m1"})
        assert result is False
        mock_url.assert_not_called()

    def test_returns_false_on_http_error(self):
        config = {"webhook_url_env": "SLACK_WEBHOOK_URL", "events": ["milestone_start"]}
        with (
            patch.dict("os.environ", {"SLACK_WEBHOOK_URL": "https://hooks.example.com/abc"}),
            patch(
                "superpower_workflow.integrations.notifier.urllib.request.urlopen",
                side_effect=OSError("connection refused"),
            ),
        ):
            result = send_notification(config, "milestone_start", {"milestone": "m1"})
        assert result is False

    def test_empty_config_is_noop(self):
        result = send_notification({}, "milestone_start", {"milestone": "m1"})
        assert result is False

    def test_empty_events_list_skips_all(self):
        config = {"webhook_url_env": "SLACK_WEBHOOK_URL", "events": []}
        with (
            patch.dict("os.environ", {"SLACK_WEBHOOK_URL": "https://hooks.example.com/abc"}),
            patch("superpower_workflow.integrations.notifier.urllib.request.urlopen") as mock_url,
        ):
            result = send_notification(config, "milestone_start", {"milestone": "m1"})
        assert result is False
        mock_url.assert_not_called()

    def test_sends_with_timeout(self):
        config = {"webhook_url_env": "SLACK_WEBHOOK_URL", "events": ["milestone_start"]}
        with (
            patch.dict("os.environ", {"SLACK_WEBHOOK_URL": "https://hooks.example.com/abc"}),
            patch("superpower_workflow.integrations.notifier.urllib.request.urlopen") as mock_url,
        ):
            mock_url.return_value = MagicMock(status=200)
            send_notification(config, "milestone_start", {"milestone": "m1"})
        _, kwargs = mock_url.call_args
        assert kwargs.get("timeout") == 10
