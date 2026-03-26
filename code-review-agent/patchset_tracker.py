#!/usr/bin/env python3
"""
Patchset tracking and review history management.

Handles:
- Finding previous reviews for a change
- Renaming old reviews with patchset numbers
- Managing review history across patchsets
"""
import json
import re
from pathlib import Path
from typing import Optional, Dict, List, Tuple


def extract_patchset_number(change_number: str, gerrit_api_url: str) -> Optional[int]:
    """
    Extract the current patchset number from Gerrit API response.

    This should be called by fetching from:
    {gerrit_api_url}/changes/{change_number}?o=CURRENT_REVISION

    Returns the patchset number or None if not found.
    """
    # This will be handled by the agent fetching the API
    # We'll extract it from the response
    return None


def find_previous_reviews(
    output_dir: Path,
    repo_name: str,
    change_number: str
) -> List[Path]:
    """
    Find all previous review files for this change.

    Returns a list of review files sorted by modification time (oldest first).
    """
    # Pattern: review_{repo}_{change_number}_*.md
    # But NOT files ending with -latest.md (those are already marked)
    pattern = f"review_{repo_name.replace('/', '_')}_{change_number}_*.md"

    all_reviews = list(output_dir.glob(pattern))

    # Filter out -latest files to find the actual old reviews
    old_reviews = [r for r in all_reviews if not r.stem.endswith('-latest')]

    # Sort by modification time
    old_reviews.sort(key=lambda p: p.stat().st_mtime)

    return old_reviews


def get_latest_review(
    output_dir: Path,
    repo_name: str,
    change_number: str
) -> Optional[Path]:
    """
    Get the most recent review file for this change.

    Returns the path to the latest review or None if no previous review exists.
    """
    # First check for -latest files
    latest_pattern = f"review_{repo_name.replace('/', '_')}_{change_number}_*-latest.md"
    latest_files = list(output_dir.glob(latest_pattern))

    if latest_files:
        # Return the most recent -latest file
        latest_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return latest_files[0]

    # Otherwise get the most recent regular review
    reviews = find_previous_reviews(output_dir, repo_name, change_number)
    return reviews[-1] if reviews else None


def rename_review_with_patchset(
    review_file: Path,
    patchset_number: int
) -> Path:
    """
    Rename a review file to include the patchset number.

    Changes:
    - review_repo_123_timestamp.md -> review_repo_123_ps1_timestamp.md
    - review_repo_123_timestamp-latest.md -> review_repo_123_ps1_timestamp.md

    Returns the new path.
    """
    # Remove -latest suffix if present
    stem = review_file.stem
    if stem.endswith('-latest'):
        stem = stem[:-7]  # Remove '-latest'

    # Insert patchset number before timestamp
    # Pattern: review_{repo}_{change}_{timestamp}
    # Result: review_{repo}_{change}_ps{num}_{timestamp}

    parts = stem.split('_')
    if len(parts) >= 3:
        # Insert ps{num} before the timestamp (last part)
        parts.insert(-1, f'ps{patchset_number}')
        new_stem = '_'.join(parts)
        new_path = review_file.parent / f"{new_stem}.md"

        # Rename the file
        review_file.rename(new_path)
        return new_path

    # Fallback: just add ps number before extension
    new_path = review_file.parent / f"{stem}_ps{patchset_number}.md"
    review_file.rename(new_path)
    return new_path


def load_previous_review(review_file: Path) -> str:
    """
    Load the content of a previous review.

    Returns the review content as a string.
    """
    try:
        with open(review_file, 'r') as f:
            return f.read()
    except Exception as e:
        return f"Error loading previous review: {e}"


def extract_patchset_from_review(review_content: str) -> Optional[int]:
    """
    Extract patchset number from a review file if it contains one.

    Looks for patterns like:
    - **Patchset**: 1
    - Patchset #1
    - PS 1
    """
    patterns = [
        r'\*\*Patchset\*\*:\s*(\d+)',
        r'Patchset\s+#?(\d+)',
        r'PS\s+(\d+)',
        r'_ps(\d+)_',  # From filename
    ]

    for pattern in patterns:
        match = re.search(pattern, review_content)
        if match:
            return int(match.group(1))

    return None


def create_review_filename(
    output_dir: Path,
    repo_name: str,
    change_number: str,
    patchset_number: Optional[int],
    timestamp: str
) -> Path:
    """
    Create a review filename with proper formatting.

    Format: review_{repo}_{change}_ps{patchset}_{timestamp}-latest.md
    """
    repo_slug = repo_name.replace('/', '_')

    if patchset_number:
        filename = f"review_{repo_slug}_{change_number}_ps{patchset_number}_{timestamp}-latest.md"
    else:
        filename = f"review_{repo_slug}_{change_number}_{timestamp}-latest.md"

    return output_dir / filename


def prepare_review_context(
    output_dir: Path,
    repo_name: str,
    change_number: str,
    current_patchset: Optional[int]
) -> Tuple[Optional[str], Optional[int], Optional[Path]]:
    """
    Prepare context for a new review.

    Returns:
    - previous_review_content: Content of the previous review (or None)
    - previous_patchset: Previous patchset number (or None)
    - new_review_file: Path where the new review should be saved

    Side effects:
    - Renames the previous review file to include patchset number
    """
    # Find the most recent review
    latest_review = get_latest_review(output_dir, repo_name, change_number)

    previous_review_content = None
    previous_patchset = None

    if latest_review:
        # Load the previous review
        previous_review_content = load_previous_review(latest_review)

        # Try to extract previous patchset number
        previous_patchset = extract_patchset_from_review(previous_review_content)

        # If we don't have a patchset number from the review, assume PS 1
        if previous_patchset is None:
            previous_patchset = 1

        # If we know the current patchset, we can rename the old review
        if current_patchset and current_patchset > previous_patchset:
            print(f"📝 Found previous review from PS {previous_patchset}")
            print(f"   Renaming to preserve history...")
            renamed_path = rename_review_with_patchset(latest_review, previous_patchset)
            print(f"   ✓ Renamed to: {renamed_path.name}")

    return previous_review_content, previous_patchset, latest_review


if __name__ == "__main__":
    # Test the module
    import sys
    from datetime import datetime

    if len(sys.argv) < 3:
        print("Usage: python patchset_tracker.py <output_dir> <repo_name> <change_number>")
        sys.exit(1)

    output_dir = Path(sys.argv[1])
    repo_name = sys.argv[2] if len(sys.argv) > 2 else "openstack/octavia"
    change_number = sys.argv[3] if len(sys.argv) > 3 else "919846"

    print(f"Checking for previous reviews...")
    print(f"  Output dir: {output_dir}")
    print(f"  Repository: {repo_name}")
    print(f"  Change: {change_number}")
    print()

    previous_reviews = find_previous_reviews(output_dir, repo_name, change_number)
    print(f"Found {len(previous_reviews)} previous review(s):")
    for review in previous_reviews:
        print(f"  - {review.name}")
    print()

    latest = get_latest_review(output_dir, repo_name, change_number)
    if latest:
        print(f"Latest review: {latest.name}")

        content = load_previous_review(latest)
        ps_num = extract_patchset_from_review(content)
        if ps_num:
            print(f"  Patchset: {ps_num}")
    else:
        print("No previous reviews found")
