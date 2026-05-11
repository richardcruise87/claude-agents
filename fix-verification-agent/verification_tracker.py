"""
Fix verification tracking functionality.

Tracks which fix proposals have been verified, when, and their result.
"""
from pathlib import Path
from typing import Dict, Tuple

from agents_lib import (
    load_tracking_file,
    should_process_item,
    record_processed_item,
    create_output_filename,
)


def load_verification_history(tracking_file: Path) -> Dict:
    """Load verification history from tracking file."""
    return load_tracking_file(tracking_file)


def should_verify_proposal(
    bug_number: str,
    proposal_timestamp: str,
    history: Dict,
) -> Tuple[bool, int]:
    """
    Determine if a fix proposal should be verified.

    Args:
        bug_number:          Launchpad bug number.
        proposal_timestamp:  ISO timestamp from the fix proposal file.
        history:             Verification history dictionary.

    Returns:
        (should_verify, sequence_number)
    """
    return should_process_item(
        bug_number,
        proposal_timestamp,
        history,
        id_prefix="verify_",
    )


def record_verification(
    tracking_file: Path,
    bug_number: str,
    proposal_timestamp: str,
    sequence: int,
    verification_file: Path,
    status: str,
    patch_source: str = "",
    attempts: int = 1,
) -> None:
    """
    Record that a fix verification was completed.

    Args:
        tracking_file:       Path to the tracking JSON file.
        bug_number:          Launchpad bug number.
        proposal_timestamp:  ISO timestamp of the fix proposal.
        sequence:            Sequence number (1 = first, 2+ = re-verification).
        verification_file:   Path to the written verification report.
        status:              RESOLVED | NOT_RESOLVED | ENVIRONMENTAL_ERROR.
        patch_source:        Description of where the patch came from.
        attempts:            Number of execution attempts made.
    """
    record_processed_item(
        tracking_file,
        bug_number,
        proposal_timestamp,
        sequence,
        id_prefix="verify_",
        extra_data={
            "verification_file": str(verification_file),
            "status": status,
            "patch_source": patch_source,
            "attempts": attempts,
        },
    )


def create_verification_filename(
    output_dir: Path,
    bug_number: str,
    bug_title: str,
    sequence: int,
) -> Path:
    """
    Create a verification report filename.

    Format: verification_{bug_number}_{title_slug}_{timestamp}_{sequence}.md
    """
    return create_output_filename(
        output_dir,
        bug_number,
        bug_title,
        sequence,
        prefix="verification",
    )
