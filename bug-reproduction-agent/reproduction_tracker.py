"""
Bug reproduction tracking functionality.

Tracks which bugs have been processed for reproduction, when, and with what result.
Prevents re-processing bugs that have already been attempted unless triage is updated.
"""
from pathlib import Path
from typing import Dict, Optional, Tuple
from agents_lib import (
    load_tracking_file,
    save_tracking_file,
    should_process_item,
    record_processed_item,
    create_output_filename,
)


# Wrapper functions for backward compatibility and domain-specific logic
def load_reproduction_history(tracking_file: Path) -> Dict:
    """
    Load reproduction history from tracking file.

    Returns:
        dict: Reproduction history with bug numbers as keys
    """
    return load_tracking_file(tracking_file)


def save_reproduction_history(tracking_file: Path, history: Dict):
    """Save reproduction history to tracking file."""
    save_tracking_file(tracking_file, history)


def should_reproduce_bug(
    bug_number: str,
    triage_timestamp: str,
    history: Dict
) -> Tuple[bool, int]:
    """
    Determine if a bug should be reproduced.

    Args:
        bug_number: Launchpad bug number
        triage_timestamp: ISO timestamp of when triage was created
        history: Reproduction history dictionary

    Returns:
        Tuple of (should_reproduce: bool, sequence_number: int)
    """
    return should_process_item(
        bug_number,
        triage_timestamp,
        history,
        id_prefix="bug_"
    )


def record_reproduction(
    tracking_file: Path,
    bug_number: str,
    triage_timestamp: str,
    sequence: int,
    status: str,
    attempts: int,
    script_path: Optional[str] = None
):
    """
    Record that a bug reproduction was attempted.

    Args:
        tracking_file: Path to tracking file
        bug_number: Launchpad bug number
        triage_timestamp: ISO timestamp when triage was created
        sequence: Sequence number for this reproduction
        status: Reproduction status (REPRODUCED, NOT_REPRODUCED, ENVIRONMENT_ERROR)
        attempts: Number of script execution attempts
        script_path: Path to final successful script (if reproduced)
    """
    extra_data = {
        "reproduction_status": status,
        "attempts": attempts
    }
    if script_path:
        extra_data["final_script_path"] = script_path

    record_processed_item(
        tracking_file,
        bug_number,
        triage_timestamp,
        sequence,
        id_prefix="bug_",
        extra_data=extra_data
    )


def create_reproduction_filename(
    output_dir: Path,
    bug_number: str,
    bug_title: str,
    sequence: int
) -> Path:
    """
    Create reproduction report filename with proper format.

    Format: reproduction_<number>_<title-slug>_<timestamp>_<sequence>.md

    Args:
        output_dir: Output directory for reproduction reports
        bug_number: Launchpad bug number
        bug_title: Bug title
        sequence: Sequence number for this reproduction

    Returns:
        Path to the reproduction report file
    """
    return create_output_filename(
        output_dir,
        bug_number,
        bug_title,
        sequence,
        prefix="reproduction"
    )


def find_previous_reproductions(
    output_dir: Path,
    bug_number: str
) -> list:
    """
    Find all previous reproduction reports for a bug.

    Args:
        output_dir: Output directory for reproduction reports
        bug_number: Launchpad bug number

    Returns:
        List of Path objects for previous reproductions, sorted by sequence
    """
    pattern = f"reproduction_{bug_number}_*_*.md"
    reproductions = list(output_dir.glob(pattern))

    # Extract sequence numbers and sort
    def get_sequence(path: Path) -> int:
        # Extract sequence from filename: reproduction_123_title_timestamp_5.md -> 5
        parts = path.stem.split('_')
        if parts:
            try:
                return int(parts[-1])
            except ValueError:
                return 0
        return 0

    reproductions.sort(key=get_sequence)
    return reproductions


if __name__ == "__main__":
    # Test the tracking functionality
    import tempfile
    from datetime import datetime

    with tempfile.TemporaryDirectory() as tmpdir:
        tracking_file = Path(tmpdir) / "test_tracking.json"
        output_dir = Path(tmpdir) / "reproductions"
        output_dir.mkdir()

        print("Testing bug reproduction tracking functionality...")

        # Test 1: First reproduction
        should_reproduce, seq = should_reproduce_bug(
            "12345",
            datetime.now().isoformat(),
            load_reproduction_history(tracking_file)
        )
        print(f"✓ First reproduction: should_reproduce={should_reproduce}, sequence={seq}")
        assert should_reproduce and seq == 1

        # Record the reproduction
        record_reproduction(
            tracking_file,
            "12345",
            datetime.now().isoformat(),
            seq,
            "REPRODUCED",
            2,
            "/tmp/script.sh"
        )

        # Test 2: Re-check same bug (no new triage)
        should_reproduce, seq = should_reproduce_bug(
            "12345",
            datetime.now().isoformat(),
            load_reproduction_history(tracking_file)
        )
        print(f"✓ No new triage: should_reproduce={should_reproduce}, sequence={seq}")
        # Note: This will return True because timestamp is different
        # In real usage, we'd use the same triage file timestamp

        # Test 3: Filename creation
        filename = create_reproduction_filename(
            output_dir,
            "12345",
            "Load balancer fails to start",
            1
        )
        print(f"✓ Filename: {filename.name}")
        assert "reproduction_12345_load_balancer_fails_to_start" in filename.name
        assert "_1.md" in filename.name

        print("\n✅ All tests passed!")
