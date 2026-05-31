"""v1.3.1 HIGH #10: statusline is marked experimental until ODQ-5 verifies
the Claude Code statusline API contract.

If/when the statusline ships as production, drop the `__experimental__`
flag — but only after verifying the live API and updating the module docstring.
"""

from __future__ import annotations

import superpower_workflow.statusline as statusline


class TestStatuslineExperimentalMarker:
    def test_module_has_experimental_flag(self):
        assert hasattr(statusline, "__experimental__")
        assert statusline.__experimental__ is True

    def test_module_docstring_marks_experimental(self):
        doc = statusline.__doc__ or ""
        # Must explicitly warn callers it's experimental.
        assert "EXPERIMENTAL" in doc.upper()

    def test_docstring_mentions_deferral_or_odq5(self):
        """Docstring should explain the deferred wiring + reference ODQ-5
        so a future reader knows what verification is required to promote.
        """
        doc = (statusline.__doc__ or "").upper()
        assert "DEFERRED" in doc or "ODQ-5" in doc
