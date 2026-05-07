"""
Fix proposal tracking functionality.

Tracks which bugs have received fix proposals, when, and the current status.
Prevents re-proposing for bugs that already have an open proposal unless
new triage information is available or the developer has requested changes.
"""
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from agents_lib import (
    load_tracking_file,
    save_tracking_file,
    should_process_item,
    record_processed_item,
    create_output_filename,
)


def load_proposal_history(tracking_file: Path) -> Dict:
    """Load proposal history from tracking file."""
    return load_tracking_file(tracking_file)


def save_proposal_history(tracking_file: Path, history: Dict) -> None:
    """Save proposal history to tracking file."""
    save_tracking_file(tracking_file, history)


def should_propose_fix(
    bug_number: str,
    triage_timestamp: str,
    history: Dict,
) -> Tuple[bool, int]:
    """
    Determine if a fix proposal should be generated for this bug.

    Args:
        bug_number:       Launchpad bug number.
        triage_timestamp: ISO timestamp of the triage report being processed.
        history:          Proposal history dictionary (from load_proposal_history).

    Returns:
        (should_propose, sequence_number)
        sequence_number is 1 for the first proposal, incrementing on refinements.
    """
    return should_process_item(
        bug_number,
        triage_timestamp,
        history,
        id_prefix="fix_",
    )


def record_proposal(
    tracking_file: Path,
    bug_number: str,
    triage_timestamp: str,
    sequence: int,
    proposal_file: Path,
    status: str = "proposed",
    gerrit_change_id: Optional[str] = None,
) -> None:
    """
    Record that a fix proposal was generated.

    Args:
        tracking_file:    Path to the tracking JSON file.
        bug_number:       Launchpad bug number.
        triage_timestamp: ISO timestamp of the triage report.
        sequence:         Sequence number for this proposal (1 = first, 2+ = refinement).
        proposal_file:    Path to the written proposal markdown file.
        status:           Proposal status: "proposed" | "accepted" | "rejected" | "human-fix".
        gerrit_change_id: Gerrit change ID if a WIP draft was pushed (optional).
    """
    extra_data: Dict = {
        "proposal_file": str(proposal_file),
        "status": status,
    }
    if gerrit_change_id:
        extra_data["gerrit_change_id"] = gerrit_change_id

    record_processed_item(
        tracking_file,
        bug_number,
        triage_timestamp,
        sequence,
        id_prefix="fix_",
        extra_data=extra_data,
    )


def create_proposal_filename(
    output_dir: Path,
    bug_number: str,
    bug_title: str,
    sequence: int,
) -> Path:
    """
    Create a fix proposal filename.

    Format: fix_proposal_{bug_number}_{title_slug}_{timestamp}_{sequence}.md
    Example: fix_proposal_2146764_tls_cipher_ordering_20260507_143022_1.md
    """
    return create_output_filename(
        output_dir,
        bug_number,
        bug_title,
        sequence,
        prefix="fix_proposal",
    )


def find_previous_proposals(output_dir: Path, bug_number: str) -> List[Path]:
    """
    Find all previous proposal files for a bug, sorted by sequence number.

    Args:
        output_dir: Directory containing proposal files.
        bug_number: Launchpad bug number.

    Returns:
        List of Path objects, sorted oldest-first by sequence number.
    """
    pattern = f"fix_proposal_{bug_number}_*_*.md"
    proposals = [p for p in output_dir.glob(pattern)
                 if not p.stem.endswith("_context")]

    def _seq(path: Path) -> int:
        parts = path.stem.split("_")
        try:
            return int(parts[-1])
        except (ValueError, IndexError):
            return 0

    proposals.sort(key=_seq)
    return proposals


def read_local_feedback(bug_number: str, proposals_dir: Path) -> Optional[str]:
    """
    Check for a local developer feedback file and return its contents.

    The feedback file is deleted after being read so it is only consumed once.

    Expected path: {proposals_dir}/fix_proposal_{bug_number}_feedback.txt

    Args:
        bug_number:    Launchpad bug number.
        proposals_dir: Directory containing proposal files.

    Returns:
        Feedback text, or None if no feedback file exists.
    """
    feedback_file = proposals_dir / f"fix_proposal_{bug_number}_feedback.txt"
    if feedback_file.exists():
        text = feedback_file.read_text(encoding="utf-8").strip()
        feedback_file.unlink()
        return text if text else None
    return None
