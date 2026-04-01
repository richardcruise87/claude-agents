#!/usr/bin/env python3
"""
Octavia Code Review Agent

Monitors OpenDev for new Octavia changes, downloads them to local devstack,
runs tests, analyzes code, and prepares review documents.
"""
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from claude_agent_sdk import query, ClaudeAgentOptions

# Add current directory to path to import config
sys.path.insert(0, str(Path(__file__).parent))
from config import load_config

# Load configuration from config.json or environment variables
CONFIG = load_config()


def load_reviewed_changes():
    """Load the set of already reviewed change IDs."""
    reviewed_file = Path(CONFIG["reviewed_changes_file"])
    if reviewed_file.exists():
        with open(reviewed_file, 'r') as f:
            return set(json.load(f))
    return set()


def save_reviewed_change(change_id, patchset=None):
    """
    Mark a change as reviewed.

    Args:
        change_id: The Gerrit change ID (e.g., "openstack%2Foctavia~919846")
        patchset: Optional patchset number. If provided, creates a patchset-aware ID.
    """
    reviewed = load_reviewed_changes()

    # Create patchset-aware ID if patchset is provided
    if patchset is not None:
        review_id = f"{change_id}~ps{patchset}"
    else:
        review_id = change_id

    reviewed.add(review_id)
    with open(CONFIG["reviewed_changes_file"], 'w') as f:
        json.dump(list(reviewed), f, indent=2)


async def fetch_pending_changes(repo_name):
    """
    Fetch pending changes for a specific repo from OpenDev.
    Returns a list of changes that need review.
    """
    print(f"\n🔍 Fetching pending changes for {repo_name}...")

    gerrit_query_url = (
        f"{CONFIG['gerrit_base_url']}/changes/"
        f"?q=project:{repo_name}+status:open+-age:180d"  # Only changes from last 180 days
        "&o=CURRENT_REVISION&o=CURRENT_COMMIT&o=DETAILED_ACCOUNTS"
        "&n=50"  # Limit to 50 most recent changes
    )

    try:
        # Use httpx for async HTTP requests (more reliable than nested agent calls)
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(gerrit_query_url)
            response.raise_for_status()

            # Gerrit prepends ")]}'" for security - strip it
            text = response.text
            if text.startswith(")]}"):
                text = text[4:]  # Remove ")]}'"

            print(f"✓ Fetched changes from Gerrit API")
            return text

    except ImportError:
        # Fallback to urllib if httpx not available
        print("⚠️  httpx not available, using urllib...")
        import urllib.request
        import ssl

        # Create SSL context that doesn't verify (for development)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        try:
            with urllib.request.urlopen(gerrit_query_url, context=ctx, timeout=30) as response:
                text = response.read().decode('utf-8')

                # Strip Gerrit security prefix
                if text.startswith(")]}"):
                    text = text[4:]

                print(f"✓ Fetched changes from Gerrit API")
                return text
        except Exception as e:
            print(f"❌ Error fetching from Gerrit: {e}")
            return None

    except Exception as e:
        print(f"❌ Error fetching from Gerrit: {e}")
        return None


async def review_change(repo_name, change_number, change_id, revision_ref, patchset=None):
    """
    Review a single change by calling the review_single_change.py script.

    This avoids nested agent calls by delegating to a separate process.

    Args:
        repo_name: Repository name (e.g., "openstack/octavia")
        change_number: Change number (e.g., "919846")
        change_id: Gerrit change ID (e.g., "openstack%2Foctavia~919846")
        revision_ref: Git ref for the revision (e.g., "refs/changes/46/919846/2")
        patchset: Patchset number (e.g., 2) for tracking purposes
    """
    print(f"\n{'='*80}")
    print(f"🤖 Starting review for {repo_name} - Change #{change_number}")
    if patchset:
        print(f"📌 Patchset: {patchset}")
    print(f"{'='*80}\n")

    # Get the script path
    script_dir = Path(__file__).parent
    review_script = script_dir / "review_single_change.py"

    if not review_script.exists():
        print(f"❌ Error: review_single_change.py not found at {review_script}")
        print(f"⚠️  Will retry on next pass")
        return None

    try:
        # Call review_single_change.py as a subprocess
        # This runs in its own process with its own agent context
        import subprocess

        print(f"📋 Calling review script for change #{change_number}...")

        # Build command with patchset if available
        cmd = [sys.executable, str(review_script), str(change_number)]
        if patchset:
            cmd.append(str(patchset))

        result = subprocess.run(
            cmd,
            cwd=str(script_dir),
            capture_output=True,
            text=True,
            timeout=1800  # 30 minute timeout for reviews
        )

        # Print the output from the review script
        if result.stdout:
            print(result.stdout)

        if result.stderr:
            print(result.stderr, file=sys.stderr)

        # Find the review file that was created
        output_dir = Path(CONFIG["reviews_output_dir"])
        if patchset:
            pattern = f"review_{repo_name.replace('/', '_')}_{change_number}_ps{patchset}_*.md"
        else:
            pattern = f"review_{repo_name.replace('/', '_')}_{change_number}_*.md"
        review_files = list(output_dir.glob(pattern))

        if review_files:
            # Review file exists - mark as complete
            review_file = max(review_files, key=lambda p: p.stat().st_mtime)
            print(f"\n✅ Review Complete!")
            print(f"📄 Review saved to: {review_file}")
            save_reviewed_change(change_id, patchset)
            return review_file
        else:
            # No review file found - don't mark as complete so it retries
            print(f"\n❌ Review file not found - will retry on next pass")
            print(f"   Expected pattern: {pattern} in {output_dir}")
            if result.returncode != 0:
                print(f"   Exit code: {result.returncode}")
            return None

    except subprocess.TimeoutExpired:
        print(f"\n❌ Review timed out after 30 minutes")
        print(f"⚠️  Will retry on next pass")
        return None
    except Exception as e:
        print(f"\n❌ Error during review: {e}")
        print(f"⚠️  Will retry on next pass")
        import traceback
        traceback.print_exc()
        return None


async def monitor_and_review(repo_name, max_reviews=5):
    """
    Monitor a repository and review new changes.

    Args:
        repo_name: Repository to monitor (e.g., "openstack/octavia")
        max_reviews: Maximum number of changes to review in one run
    """
    print(f"\n{'#'*80}")
    print(f"# Octavia Code Review Agent - Monitoring {repo_name}")
    print(f"{'#'*80}")

    # Get already reviewed changes
    reviewed = load_reviewed_changes()

    # Fetch pending changes
    changes_info = await fetch_pending_changes(repo_name)

    if not changes_info or "no changes" in str(changes_info).lower():
        print(f"\n✓ No new changes found for {repo_name}")
        return

    # Parse the Gerrit JSON response directly
    print(f"\n📋 Parsing changes...")

    try:
        import json
        # Gerrit response contains ")]}'" prefix - extract the JSON part
        response_text = str(changes_info)

        # Try to find JSON in the response
        json_start = response_text.find('[')
        if json_start == -1:
            json_start = response_text.find('{')

        if json_start != -1:
            json_text = response_text[json_start:]
            changes_list = json.loads(json_text)

            # Handle both single object and array responses
            if isinstance(changes_list, dict):
                changes_list = [changes_list]

            print(f"✓ Found {len(changes_list)} change(s)")
            print(f"📅 Cutoff date: {CONFIG['cutoff_date']} (ignoring changes created before this date)")

            # Filter changes first, then sort by date (newest first), then take max_reviews
            filtered_changes = []
            skipped_old = 0
            skipped_reviewed = 0

            for change in changes_list:
                # Extract basic info for filtering
                change_id = change.get('id') or change.get('change_id')
                change_number = str(change.get('_number', ''))

                if not all([change_id, change_number]):
                    continue

                # Check cutoff date - skip changes created before cutoff
                change_created = change.get('created', '')
                if change_created:
                    change_created_date = change_created.split(' ')[0]  # Get YYYY-MM-DD part
                    if change_created_date < CONFIG['cutoff_date']:
                        skipped_old += 1
                        continue

                # Get patchset for review tracking
                current_revision = change.get('current_revision')
                revisions = change.get('revisions', {})
                patchset = None
                if current_revision and current_revision in revisions:
                    patchset = revisions[current_revision].get('_number')

                # Check if this specific patchset has been reviewed
                if patchset:
                    patchset_review_id = f"{change_id}~ps{patchset}"
                    if patchset_review_id in reviewed:
                        skipped_reviewed += 1
                        continue
                else:
                    if change_id in reviewed:
                        skipped_reviewed += 1
                        continue

                # This change is eligible for review
                filtered_changes.append(change)

            # Sort by created date (newest first)
            filtered_changes.sort(key=lambda c: c.get('created', ''), reverse=True)

            print(f"✓ Filtered to {len(filtered_changes)} reviewable change(s)")
            if skipped_old > 0:
                print(f"⏭️  Skipped {skipped_old} changes created before cutoff date")
            if skipped_reviewed > 0:
                print(f"⏭️  Skipped {skipped_reviewed} already reviewed changes")

            # Review up to max_reviews of the newest changes
            reviewed_count = 0
            for change in filtered_changes[:max_reviews]:
                # Extract change info from Gerrit JSON structure
                change_id = change.get('id') or change.get('change_id')
                change_number = str(change.get('_number', ''))

                # Get current revision info
                current_revision = change.get('current_revision')
                revisions = change.get('revisions', {})

                # Extract patchset number
                patchset = None
                revision_ref = None
                if current_revision and current_revision in revisions:
                    revision_ref = revisions[current_revision].get('ref')
                    patchset = revisions[current_revision].get('_number')

                subject = change.get('subject', 'No subject')
                change_created = change.get('created', '')
                change_created_date = change_created.split(' ')[0] if change_created else 'unknown'

                print(f"\n📌 Reviewing change #{change_number} PS{patchset if patchset else '?'}: {subject}")
                print(f"   Created: {change_created_date}")

                # If we don't have the ref, construct it
                if not revision_ref and change_number:
                    last_two = str(change_number)[-2:].zfill(2)
                    # Get patchset number from current revision if available
                    if not patchset:
                        patchset = 1
                    revision_ref = f"refs/changes/{last_two}/{change_number}/{patchset}"

                # Review this change with patchset tracking
                await review_change(repo_name, change_number, change_id, revision_ref, patchset)
                reviewed_count += 1

            print(f"\n✅ Completed {reviewed_count} reviews for {repo_name}")
            if len(filtered_changes) > max_reviews:
                print(f"📋 {len(filtered_changes) - max_reviews} more reviewable changes remain (will process on next run)")

    except json.JSONDecodeError as e:
        print(f"⚠️  Could not parse JSON: {e}")
        print(f"Response excerpt: {str(changes_info)[:500]}...")
    except Exception as e:
        print(f"⚠️  Error processing changes: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """Main entry point for the review agent."""
    # Create output directory
    Path(CONFIG["reviews_output_dir"]).mkdir(exist_ok=True, parents=True)

    print("🚀 Octavia Code Review Agent Starting...")
    print(f"📁 Output directory: {CONFIG['reviews_output_dir']}")
    print(f"🏠 DevStack path: {CONFIG['devstack_path']}")
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
