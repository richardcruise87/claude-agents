#!/usr/bin/env python3
"""
Octavia Code Review Agent

Monitors OpenDev for new Octavia changes, downloads them to local devstack,
runs tests, analyzes code, and prepares review documents.
"""
import asyncio
import json
import sys
from pathlib import Path

# Add current directory to path to import config
sys.path.insert(0, str(Path(__file__).parent))
from config import load_config
from agents_lib import (
    notify_report,
    load_notifications_config,
    create_forge_client,
    should_review_change,
    record_review,
    create_review_filename,
    load_review_history,
    load_previous_review_context,
)

# Load configuration from config.json or environment variables
CONFIG = load_config()


def matches_wildcard(text, pattern):
    """
    Check if text matches a wildcard pattern.

    Args:
        text: String to check
        pattern: Pattern with * wildcards

    Returns:
        True if matches, False otherwise

    Examples:
        matches_wildcard("master", "master") -> True
        matches_wildcard("stable/2024.1", "stable/*") -> True
        matches_wildcard("feature/foo", "*") -> True
        matches_wildcard("master", "stable/*") -> False
    """
    import re
    # Escape special regex chars except *
    escaped = re.escape(pattern).replace(r'\*', '.*')
    # Match full string
    regex = f'^{escaped}$'
    return bool(re.match(regex, text))


def should_review_branch(branch_name, exclude_list, include_list):
    """
    Determine if a branch should be reviewed based on include/exclude lists.

    Processing order:
    1. Apply exclude list first (default: allow all)
    2. Apply include list second (override excludes)

    Args:
        branch_name: Name of the branch (e.g., "master", "stable/2024.1")
        exclude_list: List of patterns to exclude (wildcards supported)
        include_list: List of patterns to include (wildcards supported)

    Returns:
        True if branch should be reviewed, False otherwise

    Examples:
        # Exclude all except master
        should_review_branch("master", ["*"], ["master"]) -> True
        should_review_branch("feature/x", ["*"], ["master"]) -> False

        # Exclude stable branches
        should_review_branch("stable/2024.1", ["stable/*"], []) -> False
        should_review_branch("master", ["stable/*"], []) -> True

        # Include only master and main
        should_review_branch("master", [], ["master", "main"]) -> True
        should_review_branch("feature/x", [], ["master", "main"]) -> False
    """
    # Start with allowed by default
    allowed = True

    # Apply exclude list first
    if exclude_list:
        for pattern in exclude_list:
            if matches_wildcard(branch_name, pattern):
                allowed = False
                break

    # Apply include list second (overrides excludes)
    if include_list:
        # If include list is specified, default to not allowed unless matched
        if not exclude_list:  # Only if we didn't apply excludes
            allowed = False

        for pattern in include_list:
            if matches_wildcard(branch_name, pattern):
                allowed = True
                break

    return allowed


def _get_forge():
    """Return a cached ForgeClient instance for the current config."""
    return create_forge_client(CONFIG)


def _tracking_file():
    return Path(CONFIG["reviewed_changes_file"])


async def review_change(change, sequence):
    """Review a single change by calling the review_single_change.py script.

    Args:
        change:   ChangeInfo for the change to review.
        sequence: Sequence number for this review (1 = first, 2 = re-review, …).
    """
    from agents_lib import ChangeInfo as _CI  # noqa: F401 (type hint only)
    forge_label = "PS" if change.forge_type == "gerrit" else "r"
    ps_display = f"PS{change.patchset}" if change.patchset else f"r{sequence}"

    print(f"\n{'='*80}")
    print(f"🤖 Starting review for {change.repo_name} - #{change.change_id} {ps_display}")
    print(f"{'='*80}\n")

    script_dir = Path(__file__).parent
    review_script = script_dir / "review_single_change.py"

    if not review_script.exists():
        print(f"❌ Error: review_single_change.py not found at {review_script}")
        print("⚠️  Will retry on next pass")
        return None

    try:
        import subprocess

        print(f"📋 Calling review script for #{change.change_id}...")

        # Pass change ID; patchset only meaningful for Gerrit
        cmd = [sys.executable, str(review_script), change.change_id]
        if change.patchset:
            cmd.append(str(change.patchset))

        result = subprocess.run(
            cmd,
            cwd=str(script_dir),
            capture_output=True,
            text=True,
            timeout=1800,
            check=False,
        )

        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)

        # Find the review file created during this run
        output_dir = Path(CONFIG["reviews_output_dir"])
        repo_slug = change.repo_name.replace("/", "_")
        if change.forge_type == "gerrit" and change.patchset:
            pattern = f"review_{repo_slug}_{change.change_id}_ps{change.patchset}_*.md"
        else:
            pattern = f"review_{repo_slug}_{change.change_id}_r{sequence}_*.md"
        review_files = list(output_dir.glob(pattern))

        if review_files:
            review_file = max(review_files, key=lambda p: p.stat().st_mtime)
            print("\n✅ Review Complete!")
            print(f"📄 Review saved to: {review_file}")

            # Record in forge-agnostic tracking file
            record_review(_tracking_file(), change, sequence, review_file)

            forge_label_text = "MR" if change.forge_type == "gitlab" else (
                "PS" if change.forge_type == "gerrit" else "PR"
            )
            notify_report(
                report_path=review_file,
                subject=f"Code Review: {change.repo_name} #{change.change_id} {forge_label_text}{sequence}",
                summary=f"Review complete for {change.repo_name} #{change.change_id}",
                agent_config=CONFIG,
                notifications_config=load_notifications_config(),
            )
            return review_file

        print("\n❌ Review file not found - will retry on next pass")
        print(f"   Expected pattern: {pattern} in {output_dir}")
        if result.returncode != 0:
            print(f"   Exit code: {result.returncode}")
        return None

    except subprocess.TimeoutExpired:
        print("\n❌ Review timed out after 30 minutes")
        print("⚠️  Will retry on next pass")
        return None
    except Exception as e:
        print(f"\n❌ Error during review: {e}")
        print("⚠️  Will retry on next pass")
        import traceback
        traceback.print_exc()
        return None


async def monitor_and_review(repo_name, max_reviews=5):
    """Monitor a repository and review new/updated changes.

    Args:
        repo_name:   Repository to monitor (e.g., "openstack/octavia")
        max_reviews: Maximum number of changes to review in one run
    """
    print(f"\n{'#'*80}")
    print(f"# Code Review Agent - Monitoring {repo_name}")
    print(f"{'#'*80}")

    forge = _get_forge()
    history = load_review_history(_tracking_file())

    # Fetch open changes via forge API
    print(f"\n🔍 Fetching open changes for {repo_name} ({CONFIG['forge_type']})...")
    try:
        open_changes = forge.list_open_changes(
            repo_name,
            since=CONFIG.get("cutoff_date"),
            max_results=50,
        )
    except Exception as e:
        print(f"❌ Error fetching changes: {e}")
        return

    if not open_changes:
        print(f"\n✓ No open changes found for {repo_name}")
        return

    print(f"✓ Found {len(open_changes)} open change(s)")

    exclude_branches = CONFIG.get("filters", {}).get("exclude_branches", [])
    include_branches = CONFIG.get("filters", {}).get("include_branches", ["master", "main"])
    if exclude_branches or include_branches:
        print(f"🌿 Branch filters: exclude={exclude_branches}, include={include_branches}")

    # Filter + sort
    filtered = []
    skipped_branch = skipped_reviewed = 0
    for change in open_changes:
        if change.branch and not should_review_branch(change.branch, exclude_branches, include_branches):
            skipped_branch += 1
            continue
        should, seq = should_review_change(change, history)
        if not should:
            skipped_reviewed += 1
            continue
        filtered.append((change, seq))

    # Newest first
    filtered.sort(key=lambda cs: cs[0].updated_at, reverse=True)

    print(f"✓ Filtered to {len(filtered)} reviewable change(s)")
    if skipped_branch:
        print(f"⏭️  Skipped {skipped_branch} on excluded branches")
    if skipped_reviewed:
        print(f"⏭️  Skipped {skipped_reviewed} already up-to-date reviews")

    reviewed_count = 0
    for change, seq in filtered[:max_reviews]:
        print(f"\n📌 #{change.change_id}: {change.title[:60]}")
        await review_change(change, seq)
        reviewed_count += 1

    print(f"\n✅ Completed {reviewed_count} review(s) for {repo_name}")
    if len(filtered) > max_reviews:
        remaining = len(filtered) - max_reviews
        print(f"📋 {remaining} more reviewable change(s) will be processed on the next run")


async def main():
    """Main entry point for the review agent."""
    # Create output directory
    Path(CONFIG["reviews_output_dir"]).mkdir(exist_ok=True, parents=True)

    print("🚀 Code Review Agent Starting...")
    print(f"📁 Output directory: {CONFIG['reviews_output_dir']}")
    print(f"🏠 Repo base path: {CONFIG.get('repo_base_path', CONFIG['devstack_path'])}")
    print(f"🔧 Forge: {CONFIG['forge_type']} ({CONFIG['forge_base_url']})")
    print(f"🤖 Model: {CONFIG.get('model', 'claude-sonnet-4-6')}")
    print(f"📅 Cutoff date: {CONFIG['cutoff_date']}")

    # Review all configured repos
    for repo in CONFIG["octavia_repos"]:
        try:
            await monitor_and_review(repo, max_reviews=3)
        except Exception as e:
            print(f"❌ Error reviewing {repo}: {e}")
            continue

    print("\n" + "="*80)
    print("✅ Review cycle complete!")
    print(f"📊 Reviews saved to: {CONFIG['reviews_output_dir']}")
    print("="*80)


def cli_main():
    """Main entry point for command-line usage."""
    asyncio.run(main())


if __name__ == "__main__":
    cli_main()
