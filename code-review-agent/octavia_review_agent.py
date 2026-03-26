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


def save_reviewed_change(change_id):
    """Mark a change as reviewed."""
    reviewed = load_reviewed_changes()
    reviewed.add(change_id)
    with open(CONFIG["reviewed_changes_file"], 'w') as f:
        json.dump(list(reviewed), f)


async def fetch_pending_changes(repo_name):
    """
    Fetch pending changes for a specific repo from OpenDev.
    Returns a list of changes that need review.
    """
    print(f"\n🔍 Fetching pending changes for {repo_name}...")

    gerrit_query_url = (
        f"{CONFIG['gerrit_base_url']}/changes/"
        f"?q=project:{repo_name}+status:open"
        "&o=CURRENT_REVISION&o=CURRENT_COMMIT&o=DETAILED_ACCOUNTS"
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


async def review_change(repo_name, change_number, change_id, revision_ref):
    """
    Main agent workflow to review a single change.

    Steps:
    1. Fetch the change to local devstack
    2. Run unit tests
    3. Run functional tests
    4. Analyze code changes
    5. Prepare testing strategy
    6. Generate code review
    7. Save to document
    """
    print(f"\n{'='*80}")
    print(f"🤖 Starting review for {repo_name} - Change #{change_number}")
    print(f"{'='*80}\n")

    # Create output directory
    output_dir = Path(CONFIG["reviews_output_dir"])
    output_dir.mkdir(exist_ok=True, parents=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    review_file = output_dir / f"review_{repo_name.replace('/', '_')}_{change_number}_{timestamp}.md"

    repo_path = Path(CONFIG["devstack_path"]) / repo_name.split('/')[-1]

    prompt = f"""
You are performing a comprehensive code review for an OpenStack Octavia change.

**Change Information:**
- Repository: {repo_name}
- Change Number: {change_number}
- Change ID: {change_id}
- Gerrit URL: {CONFIG['gerrit_base_url']}/c/{repo_name}/+/{change_number}

**Your Task:**
Perform a complete code review following these steps:

## Step 1: Fetch the Change
Navigate to: {repo_path}
Fetch the change using:
```
git fetch {CONFIG['gerrit_base_url']}/{repo_name} {revision_ref}
git checkout FETCH_HEAD
```

## Step 2: Analyze the Changes
- Run `git diff HEAD~1` to see what changed
- Read the modified files to understand the changes
- Identify the purpose and scope of the change
- Check the commit message for clarity and completeness

## Step 3: Run Unit Tests
- Navigate to the repository directory
- Run the unit tests: `tox -e py3` or appropriate test command
- Capture the output
- Note any failures or warnings

## Step 4: Run Functional Tests (if applicable)
- Run functional tests: `tox -e functional` or similar
- Capture the output
- Note any failures or issues

## Step 5: Code Quality Analysis
Analyze the code for:
- **Code Style**: PEP 8 compliance, naming conventions
- **Error Handling**: Proper exception handling, edge cases
- **Security**: No SQL injection, XSS, or other vulnerabilities
- **Performance**: No obvious inefficiencies or bottlenecks
- **Testing**: Are new tests included? Do they cover the changes?
- **Documentation**: Are docstrings updated? Is the commit message clear?
- **Backwards Compatibility**: Are there breaking changes?
- **Dependencies**: Are new dependencies necessary and appropriate?

## Step 6: Prepare Testing Strategy
Document:
- What tests were run
- What additional tests should be run (if any)
- Recommended manual testing steps
- Any test scenarios that might be missing

## Step 7: Generate Review Document
Create a comprehensive review document with:

### Change Summary
- Brief description of what the change does
- Files modified/added/deleted

### Test Results
- Unit test results (pass/fail, output)
- Functional test results (pass/fail, output)
- Any test failures or errors

### Code Analysis
- Overall code quality assessment
- Specific issues found (with file:line references)
- Positive aspects worth noting

### Testing Strategy
- Tests that were executed
- Additional testing recommendations
- Manual test scenarios

### Recommendations
- Required changes (blocking issues)
- Suggested improvements (nice-to-haves)
- Questions for the author
- Overall verdict: Approve / Request Changes / Needs Discussion

### Review Comments
Provide specific, actionable comments in this format:
```
File: path/to/file.py:123
Severity: [Critical|Major|Minor|Nit]
Comment: [Detailed comment with reasoning]
Suggestion: [Specific code suggestion if applicable]
```

**IMPORTANT:**
- Be constructive and professional
- Provide specific examples and line numbers
- Suggest solutions, not just problems
- Note what's done well, not just issues
- Do NOT post this review - save it to: {review_file}

After completing the analysis, save the complete review document to {review_file}.
Also return to the original git branch when done.
"""

    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                allowed_tools=["Bash", "Read", "Write", "Grep", "Glob"],
            ),
        ):
            # Stream progress updates
            if hasattr(message, 'text'):
                print(f"  {message.text}")
            elif hasattr(message, 'result'):
                print(f"\n✅ Review Complete!")
                print(f"📄 Review saved to: {review_file}")
                print(f"\nSummary: {message.result}")

                # Mark as reviewed
                save_reviewed_change(change_id)
                return review_file

    except Exception as e:
        print(f"\n❌ Error during review: {e}")
        # Still mark as reviewed to avoid retry loops
        save_reviewed_change(change_id)
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

            reviewed_count = 0
            for change in changes_list[:max_reviews]:
                # Extract change info from Gerrit JSON structure
                change_id = change.get('id') or change.get('change_id')
                change_number = str(change.get('_number', ''))

                # Get current revision info
                current_revision = change.get('current_revision')
                revisions = change.get('revisions', {})

                revision_ref = None
                if current_revision and current_revision in revisions:
                    revision_ref = revisions[current_revision].get('ref')

                subject = change.get('subject', 'No subject')

                if not all([change_id, change_number]):
                    print(f"⚠️  Skipping incomplete change: {subject}")
                    continue

                if change_id in reviewed:
                    print(f"⏭️  Skipping already reviewed: #{change_number} - {subject}")
                    continue

                print(f"\n📌 Reviewing change #{change_number}: {subject}")

                # If we don't have the ref, construct it
                if not revision_ref and change_number:
                    last_two = str(change_number)[-2:].zfill(2)
                    # Get patchset number from current revision if available
                    patchset = 1
                    if current_revision and current_revision in revisions:
                        patchset = revisions[current_revision].get('_number', 1)
                    revision_ref = f"refs/changes/{last_two}/{change_number}/{patchset}"

                # Review this change
                await review_change(repo_name, change_number, change_id, revision_ref)
                reviewed_count += 1

            print(f"\n✅ Completed {reviewed_count} reviews for {repo_name}")

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


if __name__ == "__main__":
    asyncio.run(main())
