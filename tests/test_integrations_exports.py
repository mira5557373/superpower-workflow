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
