"""
Backport tracking functionality.

Tracks which upstream changes have been backported to which branches,
preventing duplicate backport attempts and recording outcomes.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Optional


def load_backport_tracking(tracking_file: Path) -> dict:
    """Load backport tracking data from a JSON file."""
    tracking_file = Path(tracking_file).expanduser()
    if not tracking_file.exists():
        return {}
    try:
        return json.loads(tracking_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_backport_tracking(tracking_file: Path, data: dict) -> None:
    """Save backport tracking data to a JSON file."""
    tracking_file = Path(tracking_file).expanduser()
    tracking_file.parent.mkdir(parents=True, exist_ok=True)
    tracking_file.write_text(
        json.dumps(data, indent=2), encoding="utf-8"
    )


def _tracking_key(change_id: str, branch: str) -> str:
    return f"{change_id}:{branch}"


def is_already_processed(
    tracking_file: Path,
    change_id: str,
    branch: str,
) -> bool:
    """Return True if this change has already been backported or skipped for this branch."""
    data = load_backport_tracking(tracking_file)
    return _tracking_key(change_id, branch) in data


def record_backport(
    tracking_file: Path,
    change_id: str,
    branch: str,
    status: str,
    backport_change_url: Optional[str] = None,
    commit_sha: Optional[str] = None,
) -> None:
    """
    Record the outcome of a backport attempt.

    Args:
        tracking_file:       Path to the tracking JSON file.
        change_id:           Original upstream Gerrit change number.
        branch:              Target stable branch.
        status:              BACKPORTED | CONFLICT | FETCH_FAILED | PUSH_FAILED | SKIPPED.
        backport_change_url: URL of the created backport change (BACKPORTED only).
        commit_sha:          Upstream commit SHA that was cherry-picked.
    """
    data = load_backport_tracking(tracking_file)
    entry: dict = {
        "status": status,
        "processed_at": datetime.now().isoformat(),
    }
    if backport_change_url:
        entry["backport_change_url"] = backport_change_url
    if commit_sha:
        entry["upstream_commit_sha"] = commit_sha
    data[_tracking_key(change_id, branch)] = entry
    save_backport_tracking(tracking_file, data)


def get_backport_record(
    tracking_file: Path,
    change_id: str,
    branch: str,
) -> Optional[dict]:
    """Return the tracking record for this change+branch pair, or None."""
    data = load_backport_tracking(tracking_file)
    return data.get(_tracking_key(change_id, branch))


def list_backport_records(
    tracking_file: Path,
    change_id: Optional[str] = None,
) -> list[dict]:
    """Return all tracking records, optionally filtered by change_id."""
    data = load_backport_tracking(tracking_file)
    results = []
    for key, record in data.items():
        cid, branch = key.split(":", 1) if ":" in key else (key, "")
        if change_id and cid != change_id:
            continue
        results.append({"change_id": cid, "branch": branch, **record})
    return results
