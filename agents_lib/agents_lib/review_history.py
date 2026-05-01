"""
Forge-agnostic review history tracking for the code-review agent.

Replaces the Gerrit-specific patchset_tracker.py logic with an
implementation that works for Gerrit (patchset-based), GitHub (PR with
HEAD SHA tracking), and GitLab (MR with HEAD SHA tracking).

Tracking key format:
  Gerrit: "{repo}:{change_number}:ps{patchset}"
  GitHub: "{repo}:{pr_number}:{head_sha[:8]}"
  GitLab: "{repo}:{mr_iid}:{head_sha[:8]}"

Filename format:
  Gerrit (backward-compat): review_{repo}_{change}_ps{patchset}_{ts}.md
  GitHub/GitLab:            review_{repo}_{change}_r{seq}_{ts}.md
"""

import json
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

from .forge_client import ChangeInfo
from .utils import slugify


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class ReviewRecord:
    """Stored metadata for a completed review."""
    change_id: str
    repo_name: str
    forge_type: str
    head_sha: str               # SHA at time of review
    patchset: Optional[int]     # Gerrit only; None for GitHub/GitLab
    sequence: int               # 1, 2, 3 … regardless of forge
    review_file: str            # absolute path to saved review markdown
    reviewed_at: str            # ISO timestamp


# ---------------------------------------------------------------------------
# Tracking-key helpers
# ---------------------------------------------------------------------------

def _tracking_key(change: ChangeInfo) -> str:
    repo_slug = change.repo_name.replace("/", "_")
    if change.forge_type == "gerrit":
        ps = change.patchset or 1
        return f"{repo_slug}:{change.change_id}:ps{ps}"
    sha_short = change.head_sha[:8] if change.head_sha else "unknown"
    return f"{repo_slug}:{change.change_id}:{sha_short}"


def _base_key(change: ChangeInfo) -> str:
    """Key prefix for all reviews of the same change, across all patchsets/SHAs."""
    repo_slug = change.repo_name.replace("/", "_")
    return f"{repo_slug}:{change.change_id}:"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load_review_history(tracking_file: Path) -> dict[str, ReviewRecord]:
    """Load all review records from the tracking JSON file."""
    tracking_file = Path(tracking_file)
    if not tracking_file.exists():
        return {}
    with open(tracking_file, encoding="utf-8") as f:
        raw = json.load(f)
    return {k: ReviewRecord(**v) for k, v in raw.items()}


def _save_review_history(tracking_file: Path, history: dict[str, ReviewRecord]) -> None:
    tracking_file = Path(tracking_file)
    tracking_file.parent.mkdir(parents=True, exist_ok=True)
    with open(tracking_file, "w", encoding="utf-8") as f:
        json.dump({k: asdict(v) for k, v in history.items()}, f, indent=2)


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def should_review_change(
    change: ChangeInfo,
    history: dict[str, ReviewRecord],
) -> tuple[bool, int]:
    """Determine whether a change should be (re-)reviewed.

    Returns:
        (should_review, next_sequence_number)

    Rules:
        Never reviewed before → (True, 1)
        Gerrit: patchset increased → (True, prev_seq + 1)
        GitHub/GitLab: HEAD SHA changed → (True, prev_seq + 1)
        Otherwise: (False, prev_seq)
    """
    key = _tracking_key(change)
    if key in history:
        # Already reviewed at this exact patchset/SHA
        return False, history[key].sequence

    # Find any previous review for this change (any patchset/SHA)
    base = _base_key(change)
    prior = [r for k, r in history.items() if k.startswith(base)]
    if not prior:
        return True, 1

    prior.sort(key=lambda r: r.sequence)
    latest = prior[-1]
    return True, latest.sequence + 1


def record_review(
    tracking_file: Path,
    change: ChangeInfo,
    sequence: int,
    review_file: Path,
) -> None:
    """Persist a completed review record."""
    history = load_review_history(tracking_file)
    key = _tracking_key(change)
    history[key] = ReviewRecord(
        change_id=change.change_id,
        repo_name=change.repo_name,
        forge_type=change.forge_type,
        head_sha=change.head_sha,
        patchset=change.patchset,
        sequence=sequence,
        review_file=str(review_file),
        reviewed_at=datetime.now().isoformat(),
    )
    _save_review_history(tracking_file, history)


# ---------------------------------------------------------------------------
# Filename generation
# ---------------------------------------------------------------------------

def create_review_filename(
    output_dir: Path,
    change: ChangeInfo,
    sequence: int,
    timestamp: Optional[str] = None,
) -> Path:
    """Generate a review output filename.

    Gerrit  (backward-compat): review_{repo}_{change}_ps{patchset}_{ts}.md
    GitHub:                    review_{repo}_{pr}_r{seq}_{ts}.md
    GitLab:                    review_{repo}_{mr}_r{seq}_{ts}.md
    """
    ts = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    repo_slug = change.repo_name.replace("/", "_")

    if change.forge_type == "gerrit":
        ps = change.patchset or 1
        name = f"review_{repo_slug}_{change.change_id}_ps{ps}_{ts}.md"
    else:
        name = f"review_{repo_slug}_{change.change_id}_r{sequence}_{ts}.md"

    return Path(output_dir) / name


# ---------------------------------------------------------------------------
# Previous-review discovery
# ---------------------------------------------------------------------------

def find_previous_reviews(
    output_dir: Path,
    change: ChangeInfo,
) -> list[Path]:
    """Find all saved review files for this change, oldest first."""
    repo_slug = change.repo_name.replace("/", "_")
    pattern = f"review_{repo_slug}_{change.change_id}_*.md"
    reviews = list(Path(output_dir).glob(pattern))
    reviews.sort(key=lambda p: p.stat().st_mtime)
    return reviews


def load_previous_review_context(
    output_dir: Path,
    change: ChangeInfo,
    history: dict[str, ReviewRecord],
) -> tuple[Optional[str], Optional[ReviewRecord]]:
    """Load the most recent prior review content and its record.

    Returns:
        (review_content_str, ReviewRecord) or (None, None) if no prior review.
    """
    # Find prior records for this change
    base = _base_key(change)
    prior = [r for k, r in history.items() if k.startswith(base)]
    if not prior:
        return None, None

    prior.sort(key=lambda r: r.sequence)
    latest = prior[-1]

    review_path = Path(latest.review_file)
    if not review_path.exists():
        # File moved or deleted — try finding by glob
        candidates = find_previous_reviews(output_dir, change)
        if not candidates:
            return None, latest
        review_path = candidates[-1]

    content = review_path.read_text(encoding="utf-8")
    return content[:3000], latest  # Truncate for prompt context
