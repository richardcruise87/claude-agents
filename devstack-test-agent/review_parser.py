"""
Parse code review markdown files to extract change information.

Extracts repository, change number, patchset, and other metadata
needed for DevStack testing.
"""
import re
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


@dataclass
class ReviewInfo:
    """Parsed review information."""
    review_file: Path
    repo_name: str
    change_number: str
    patchset: int
    gerrit_url: str
    review_timestamp: str
    already_tested: bool = False


def parse_review_file(review_file: Path) -> Optional[ReviewInfo]:
    """
    Parse a code review markdown file.

    Args:
        review_file: Path to review markdown file

    Returns:
        ReviewInfo object or None if parsing fails

    Expected filename format:
        review_openstack_octavia_982615_ps1_20260331_133739.md
    """
    if not review_file.exists():
        return None

    # Parse filename for basic info
    # Format: review_{repo}_{change}_{patchset}_{timestamp}.md
    filename = review_file.stem
    parts = filename.split('_')

    if len(parts) < 5 or not parts[0] == 'review':
        return None

    # Extract from filename
    # Example: review_openstack_octavia_982615_ps1_20260331_133739
    try:
        # Find repository (openstack_octavia or openstack_octavia-lib, etc.)
        repo_parts = []
        i = 1
        while i < len(parts):
            # Check if this part looks like a change number
            if parts[i].isdigit() and len(parts[i]) >= 5:
                break
            repo_parts.append(parts[i])
            i += 1

        repo_name = '/'.join(repo_parts)  # openstack/octavia

        # Next part is change number
        change_number = parts[i]

        # Next part is patchset (ps1, ps2, etc.)
        patchset_str = parts[i + 1] if i + 1 < len(parts) else "ps1"
        patchset = int(patchset_str.replace('ps', ''))

        # Timestamp is last 2 parts
        timestamp = '_'.join(parts[-2:])

    except (IndexError, ValueError) as e:
        print(f"⚠️  Could not parse filename: {review_file.name} ({e})")
        return None

    # Read file to extract Gerrit URL and check if already tested
    try:
        content = review_file.read_text()

        # Find Gerrit URL
        gerrit_url_match = re.search(r'\*\*Gerrit URL\*\*:\s*(\S+)', content)
        if gerrit_url_match:
            gerrit_url = gerrit_url_match.group(1)
        else:
            # Construct default Gerrit URL
            gerrit_url = f"https://review.opendev.org/c/{repo_name}/+/{change_number}"

        # Check if DevStack testing section already exists
        already_tested = "### DevStack Integration Tests" in content

        return ReviewInfo(
            review_file=review_file,
            repo_name=repo_name,
            change_number=change_number,
            patchset=patchset,
            gerrit_url=gerrit_url,
            review_timestamp=timestamp,
            already_tested=already_tested
        )

    except Exception as e:
        print(f"⚠️  Error reading review file: {e}")
        return None


def get_review_timestamp(review_file: Path) -> str:
    """
    Extract timestamp from review filename.

    Args:
        review_file: Path to review file

    Returns:
        Timestamp string (YYYYMMDD_HHMMSS)
    """
    parts = review_file.stem.split('_')
    if len(parts) >= 2:
        return '_'.join(parts[-2:])
    return ""


def should_test_review(review_info: ReviewInfo, allowed_repos: list) -> bool:
    """
    Determine if this review should be tested in DevStack.

    Args:
        review_info: Parsed review information
        allowed_repos: List of repository names to test (empty = all)

    Returns:
        True if should test, False otherwise
    """
    # Skip if already tested
    if review_info.already_tested:
        return False

    # Check repository filter
    if allowed_repos and review_info.repo_name not in allowed_repos:
        return False

    # Client libraries and tempest plugins don't need DevStack testing
    skip_repos = [
        "python-octaviaclient",
        "octavia-tempest-plugin",
    ]

    for skip_repo in skip_repos:
        if skip_repo in review_info.repo_name:
            return False

    return True


if __name__ == "__main__":
    # Test the parser
    import sys
    from pathlib import Path

    print("Testing review file parser...")
    print()

    # Test with real review file if provided
    if len(sys.argv) > 1:
        review_file = Path(sys.argv[1])
        print(f"Parsing: {review_file}")
        print()

        info = parse_review_file(review_file)
        if info:
            print("✓ Parsed successfully:")
            print(f"  Repository: {info.repo_name}")
            print(f"  Change: {info.change_number}")
            print(f"  Patchset: {info.patchset}")
            print(f"  Gerrit URL: {info.gerrit_url}")
            print(f"  Timestamp: {info.review_timestamp}")
            print(f"  Already tested: {info.already_tested}")
        else:
            print("✗ Failed to parse")
    else:
        # Test filename parsing
        test_filenames = [
            "review_openstack_octavia_982615_ps1_20260331_133739.md",
            "review_openstack_octavia-lib_942691_ps2_20260326_150116.md",
            "review_openstack_python-octaviaclient_982567_ps1_20260330_120000.md",
        ]

        for filename in test_filenames:
            # Create temp file for testing
            test_file = Path(f"/tmp/{filename}")
            test_file.write_text("""# Code Review: openstack/octavia - Change #982615

**Gerrit URL**: https://review.opendev.org/c/openstack/octavia/+/982615
**Patchset**: 1
**Reviewed**: 2026-03-31 13:37:39

## Change Summary
Test change
""")

            print(f"Testing: {filename}")
            info = parse_review_file(test_file)
            if info:
                print(f"  ✓ Repo: {info.repo_name}, Change: {info.change_number}, PS: {info.patchset}")
            else:
                print("  ✗ Failed to parse")

            test_file.unlink()

        print()
        print("✅ Parser tests complete")
