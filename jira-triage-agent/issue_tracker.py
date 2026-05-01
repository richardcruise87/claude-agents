"""
JIRA issue tracking — thin wrapper around agents_lib tracking primitives.

Prevents re-processing issues that haven't changed since the last run,
and sequences repeated triages/plans when issues are updated.
"""

from pathlib import Path
from typing import Optional
from agents_lib import (
    load_tracking_file,
    should_process_item,
    record_processed_item,
    create_output_filename,
)


def load_issue_history(tracking_file: Path) -> dict:
    """Load tracking history for all JIRA issues."""
    return load_tracking_file(tracking_file)


def should_process_issue(
    issue_key: str,
    issue_updated: str,
    history: dict,
) -> tuple[bool, int]:
    """Return (should_process, sequence) for a JIRA issue.

    Re-processes when the issue has been updated since the last run.
    Sequence increments with each processing.
    """
    return should_process_item(issue_key, issue_updated, history, id_prefix="jira_")


def record_processed_issue(
    tracking_file: Path,
    issue_key: str,
    issue_updated: str,
    sequence: int,
    extra_data: Optional[dict] = None,
) -> None:
    """Record that a JIRA issue has been processed."""
    record_processed_item(
        tracking_file,
        issue_key,
        issue_updated,
        sequence,
        id_prefix="jira_",
        extra_data=extra_data,
    )


def create_output_file_path(
    output_dir: Path,
    issue_key: str,
    summary: str,
    sequence: int,
    prefix: str = "jira",
) -> Path:
    """Generate a timestamped output filename for a JIRA issue.

    Format: jira_{key}_{summary-slug}_{timestamp}_{sequence}.md
    Example: jira_PROJ-123_fix-login-timeout_20260501_143022_1.md
    """
    return create_output_filename(
        output_dir,
        issue_key.replace("-", "_"),
        summary,
        sequence,
        prefix=prefix,
    )
