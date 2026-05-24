"""Context generator for prompt summarization of completed milestones."""

from __future__ import annotations

import subprocess
from pathlib import Path

MAX_WORDS = 400


def _count_test_files(project_root: Path) -> int:
    """Count test files in the project.

    Args:
        project_root: Path to the project root directory.

    Returns:
        Number of test files found.
    """
    tests_dir = project_root / "tests"
    if not tests_dir.exists():
        return 0
    try:
        return len(list(tests_dir.rglob("test_*.py")))
    except OSError:
        return 0


def _get_milestone_files(project_root: Path, names: list[str]) -> str:
    """Get files changed for milestones using git diff.

    Args:
        project_root: Path to the project root directory.
        names: List of milestone names.

    Returns:
        Compact string of files per milestone.
    """
    if not names:
        return ""

    files_by_milestone = {}
    for name in names:
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", f"pre-impl/{name}^..pre-impl/{name}"],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                files = result.stdout.strip().split("\n")
                files_by_milestone[name] = files
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    if not files_by_milestone:
        return ""

    parts = []
    for name, files in files_by_milestone.items():
        normalized_files = [f.replace("\\", "/") for f in files]
        parts.append(f"{name}: {', '.join(normalized_files)}")

    return " ".join(parts)


def _get_exports(project_root: Path, milestone_name: str) -> str:
    """Get key exports from milestone's __init__.py or class definitions.

    Args:
        project_root: Path to the project root directory.
        milestone_name: Name of the milestone.

    Returns:
        Comma-separated list of export names.
    """
    try:
        # Try to find milestone directory
        src_dir = project_root / "src"
        if not src_dir.exists():
            return ""

        # Look for __init__.py in any subdirectory containing milestone name
        for init_file in src_dir.rglob("__init__.py"):
            try:
                content = init_file.read_text(encoding="utf-8")
                # Extract imports
                imports = []
                for line in content.split("\n"):
                    if "from" in line and "import" in line:
                        parts = line.split("import")
                        if len(parts) >= 2:
                            names = parts[1].strip()
                            imports.extend([n.strip() for n in names.split(",")])
                if imports:
                    return ", ".join(imports[:5])
            except (OSError, UnicodeDecodeError):
                continue

        # Fallback: scan for class definitions
        for py_file in src_dir.rglob("*.py"):
            try:
                content = py_file.read_text(encoding="utf-8")
                classes = []
                for line in content.split("\n"):
                    if line.strip().startswith("class "):
                        class_name = line.split("class ")[1].split("(")[0].split(":")[0].strip()
                        classes.append(class_name)
                if classes:
                    return ", ".join(classes[:5])
            except (OSError, UnicodeDecodeError):
                continue
    except OSError:
        pass

    return ""


def _compact_paths(paths: list[str]) -> str:
    """Group file paths by directory.

    Args:
        paths: List of file paths.

    Returns:
        Compacted string representation.
    """
    if not paths:
        return ""

    paths = [p.replace("\\", "/") for p in paths]

    # Group by directory
    by_dir = {}
    for path in paths:
        if "/" in path:
            dir_part = path.rsplit("/", 1)[0]
            if dir_part not in by_dir:
                by_dir[dir_part] = []
            by_dir[dir_part].append(path.rsplit("/", 1)[1])
        else:
            if "." not in by_dir:
                by_dir["."] = []
            by_dir["."].append(path)

    # Format compactly
    parts = []
    for dir_name in sorted(by_dir.keys()):
        files = by_dir[dir_name]
        if dir_name == ".":
            parts.append(", ".join(files))
        else:
            parts.append(f"{dir_name}/{{{','.join(files)}}}")

    return ", ".join(parts)


def build_context_summary(
    completed: list[str],
    project_root: Path,
    current_milestone: dict | None = None,
    milestones: list[dict] | None = None,
) -> str:
    """Generate a context summary from completed milestones.

    Includes dependency info, files, and exports. Output is capped at 400 words.

    Args:
        completed: List of completed milestone names.
        project_root: Path to the project root directory.
        current_milestone: Current milestone dict with 'name', 'depends_on' keys.
        milestones: List of all milestone dicts.

    Returns:
        A context summary string.
    """
    if not completed:
        return "No prior milestones."

    # Start with summary of completed
    test_count = _count_test_files(project_root)
    parts = [
        f"Completed ({len(completed)} milestones{f', {test_count} test files' if test_count else ''}):"
    ]

    # Older milestones (first N-3)
    if len(completed) > 3:
        older = completed[:-3]
        parts.append(f"  {', '.join(older)} complete.")

    # Recent milestones with details
    recent = completed[-3:]
    for name in recent:
        exports = _get_exports(project_root, name)
        if exports:
            parts.append(f"  {name}: {exports}")
        else:
            parts.append(f"  {name}")

    # Add dependency info if provided
    if current_milestone and "depends_on" in current_milestone:
        deps = current_milestone.get("depends_on", [])
        if deps:
            parts.append("")
            parts.append(
                f"For {current_milestone.get('name', 'current')} (depends on {', '.join(deps)}):"
            )
            parts.append(f"  {', '.join(deps)}")

    # Add CLAUDE.md pointer
    parts.append("")
    parts.append("See CLAUDE.md for full conventions.")

    summary = "\n".join(parts)
    words = summary.split()

    if len(words) > MAX_WORDS:
        # Truncate older milestones first
        words = words[:MAX_WORDS]
        summary = " ".join(words)

    return summary
