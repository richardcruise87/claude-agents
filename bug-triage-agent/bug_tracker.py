"""
Bug triage tracking functionality.

Tracks which bugs have been triaged, when, and with what sequence number.
Prevents re-triaging bugs that haven't been updated since last review.
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


# Wrapper functions for backward compatibility
def load_triage_history(tracking_file: Path) -> Dict:
    """
    Load triage history from tracking file.

    Returns:
        dict: Triage history with bug numbers as keys
    """
    return load_tracking_file(tracking_file)


def save_triage_history(tracking_file: Path, history: Dict):
    """Save triage history to tracking file."""
    save_tracking_file(tracking_file, history)


def should_triage_bug(
    bug_number: str,
    bug_last_updated: str,
    history: Dict
) -> Tuple[bool, int]:
    """
    Determine if a bug should be triaged.

    Args:
        bug_number: Launchpad bug number
        bug_last_updated: ISO timestamp of when bug was last updated on Launchpad
        history: Triage history dictionary

    Returns:
        Tuple of (should_triage: bool, sequence_number: int)
    """
    return should_process_item(bug_number, bug_last_updated, history, id_prefix="bug_")


def record_triage(
    tracking_file: Path,
    bug_number: str,
    bug_last_updated: str,
    sequence: int
):
    """
    Record that a bug was triaged.

    Args:
        tracking_file: Path to tracking file
        bug_number: Launchpad bug number
        bug_last_updated: ISO timestamp when bug was last updated
        sequence: Sequence number for this triage
    """
    record_processed_item(
        tracking_file,
        bug_number,
        bug_last_updated,
        sequence,
        id_prefix="bug_"
    )


def create_triage_filename(
    output_dir: Path,
    bug_number: str,
    bug_title: str,
    sequence: int
) -> Path:
    """
    Create triage filename with proper format.

    Format: bug_<number>_<title-slug>_<timestamp>_<sequence>.md

    Args:
        output_dir: Output directory for triages
        bug_number: Launchpad bug number
        bug_title: Bug title
        sequence: Sequence number for this triage

    Returns:
        Path to the triage file
    """
    return create_output_filename(
        output_dir,
        bug_number,
        bug_title,
        sequence,
        prefix="bug"
    )


def find_previous_triages(
    output_dir: Path,
    bug_number: str
) -> list:
    """
    Find all previous triage files for a bug.

    Args:
        output_dir: Output directory for triages
        bug_number: Launchpad bug number

    Returns:
        List of Path objects for previous triages, sorted by sequence
    """
    pattern = f"bug_{bug_number}_*_*.md"
    triages = list(output_dir.glob(pattern))

    # Extract sequence numbers and sort
    def get_sequence(path: Path) -> int:
        # Extract sequence from filename: bug_123_title_timestamp_5.md -> 5
        parts = path.stem.split('_')
        if parts:
            try:
                return int(parts[-1])
            except ValueError:
                return 0
        return 0

    triages.sort(key=get_sequence)
    return triages


def get_previous_triage_summary(triage_file: Path) -> Optional[str]:
    """
    Get summary from a previous triage file.

    Reads the first 2000 characters to get context.

    Args:
        triage_file: Path to previous triage file

    Returns:
        First 2000 chars of the triage, or None if file doesn't exist
    """
    if not triage_file.exists():
        return None

    with open(triage_file, 'r', encoding='utf-8') as f:
        content = f.read(2000)
        return content


if __name__ == "__main__":
    # Test the tracking functionality
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        tracking_file = Path(tmpdir) / "test_tracking.json"
        output_dir = Path(tmpdir) / "triages"
        output_dir.mkdir()

        print("Testing bug tracking functionality...")

        # Test 1: First triage
        should_triage, seq = should_triage_bug(
            "12345",
            "2026-03-30T10:00:00",
            load_triage_history(tracking_file)
        )
        print(f"✓ First triage: should_triage={should_triage}, sequence={seq}")
        assert should_triage and seq == 1

        # Record the triage
        record_triage(tracking_file, "12345", "2026-03-30T10:00:00", seq)

        # Test 2: Re-check same bug (no update)
        should_triage, seq = should_triage_bug(
            "12345",
            "2026-03-30T10:00:00",
            load_triage_history(tracking_file)
        )
        print(f"✓ No update: should_triage={should_triage}, sequence={seq}")
        assert not should_triage and seq == 1

        # Test 3: Bug updated
        should_triage, seq = should_triage_bug(
            "12345",
            "2026-03-30T11:00:00",
            load_triage_history(tracking_file)
        )
        print(f"✓ Bug updated: should_triage={should_triage}, sequence={seq}")
        assert should_triage and seq == 2

        # Test 4: Filename creation
        filename = create_triage_filename(
            output_dir,
            "12345",
            "Load balancer fails to start",
            2
        )
        print(f"✓ Filename: {filename.name}")
        assert "bug_12345_load_balancer_fails_to_start" in filename.name
        assert "_2.md" in filename.name

        # Test 5: Slugify
        slug = slugify("This is a test! With special chars: @#$%")
        print(f"✓ Slugify: '{slug}'")
        assert slug == "this_is_a_test_with_special_chars"

        print("\n✅ All tests passed!")
