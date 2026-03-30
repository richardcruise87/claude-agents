"""
Bug triage tracking functionality.

Tracks which bugs have been triaged, when, and with what sequence number.
Prevents re-triaging bugs that haven't been updated since last review.
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Tuple
import re


def slugify(text: str, max_length: int = 50) -> str:
    """
    Convert text to a filesystem-safe slug.

    Args:
        text: Text to slugify
        max_length: Maximum length of slug

    Returns:
        Slugified text suitable for filenames
    """
    # Remove special characters, keep alphanumeric and spaces
    slug = re.sub(r'[^\w\s-]', '', text.lower())
    # Replace spaces with underscores
    slug = re.sub(r'[\s]+', '_', slug)
    # Remove consecutive underscores
    slug = re.sub(r'_+', '_', slug)
    # Trim to max length
    slug = slug[:max_length].strip('_')
    return slug


def load_triage_history(tracking_file: Path) -> Dict:
    """
    Load triage history from tracking file.

    Returns:
        dict: Triage history with bug numbers as keys
              Each entry contains: {
                  "last_triaged": "ISO timestamp",
                  "last_updated": "ISO timestamp from Launchpad",
                  "sequence": int
              }
    """
    if tracking_file.exists():
        with open(tracking_file, 'r') as f:
            return json.load(f)
    return {}


def save_triage_history(tracking_file: Path, history: Dict):
    """Save triage history to tracking file."""
    tracking_file.parent.mkdir(parents=True, exist_ok=True)
    with open(tracking_file, 'w') as f:
        json.dump(history, f, indent=2)


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
    bug_key = f"bug_{bug_number}"

    if bug_key not in history:
        # Never triaged before
        return (True, 1)

    last_triage = history[bug_key]
    last_updated_tracked = last_triage.get('last_updated', '')

    # Compare timestamps
    # If bug has been updated since last triage, re-triage with incremented sequence
    if bug_last_updated > last_updated_tracked:
        next_sequence = last_triage.get('sequence', 0) + 1
        return (True, next_sequence)

    # Bug hasn't been updated since last triage
    return (False, last_triage.get('sequence', 1))


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
    history = load_triage_history(tracking_file)
    bug_key = f"bug_{bug_number}"

    history[bug_key] = {
        "last_triaged": datetime.now().isoformat(),
        "last_updated": bug_last_updated,
        "sequence": sequence
    }

    save_triage_history(tracking_file, history)


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
    title_slug = slugify(bug_title)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"bug_{bug_number}_{title_slug}_{timestamp}_{sequence}.md"
    return output_dir / filename


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
