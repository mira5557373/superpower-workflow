"""Context generator for prompt summarization of completed milestones."""

from __future__ import annotations

DETAIL_COUNT = 3
MAX_WORDS = 200


def build_context_summary(completed: list[str]) -> str:
    """Generate a context summary from completed milestones.

    Last 3 milestones are detailed, older ones are summarized.
    Output is capped at 200 words.

    Args:
        completed: List of completed milestone names.

    Returns:
        A context summary string.
    """
    if not completed:
        return "No prior milestones."

    parts = []

    if len(completed) > DETAIL_COUNT:
        older = completed[:-DETAIL_COUNT]
        parts.append(f"{', '.join(older)} complete.")

    recent = completed[-DETAIL_COUNT:]
    parts.append("Recent: " + ", ".join(recent) + ".")

    summary = " ".join(parts)
    words = summary.split()

    if len(words) > MAX_WORDS:
        summary = " ".join(words[:MAX_WORDS])

    return summary
