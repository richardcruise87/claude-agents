#!/usr/bin/env python3
"""
Review a specific Octavia change from OpenDev.

Usage:
    python review_single_change.py <change_number> [patchset]
    python review_single_change.py 912345
    python review_single_change.py 912345 2
    python review_single_change.py https://review.opendev.org/c/openstack/octavia/+/912345
    python review_single_change.py https://review.opendev.org/c/openstack/octavia/+/912345 3
"""
import asyncio
import sys
import re
import argparse
from datetime import datetime
from pathlib import Path
# Add current directory to path to import config
sys.path.insert(0, str(Path(__file__).parent))
from config import load_config
from prompts import get_code_review_prompt
from review_parser import extract_forge_comment, extract_line_comments, determine_vote
from agents_lib import (
    check_repo_on_main_branch,
    checkout_main_branch,
    create_model_client,
    format_usage_info,
    create_forge_client,
    load_review_history,
    load_previous_review_context,
    record_review,
    create_review_filename,
)

# Load configuration
CONFIG = load_config()
DEVSTACK_PATH = CONFIG["devstack_path"]
REVIEWS_OUTPUT_DIR = CONFIG["reviews_output_dir"]
GERRIT_BASE_URL = CONFIG["gerrit_base_url"]  # kept for backward compat with prompts
REPO_BASE_PATH = CONFIG.get("repo_base_path", DEVSTACK_PATH)


def _find_full_review_content(summary_content: str) -> str:
    """Try to load the full review from a path embedded in the summary text.

    The AI sometimes writes the full review to a path like
    '/opt/stack/octavia/review-985404-ps1.md' and references it in the summary.
    Returns the full content, or falls back to the summary content.
    """
    import re as _re
    m = _re.search(r'saved to\s+[`\']?(/[^\s`\']+\.md)[`\']?', summary_content, _re.IGNORECASE)
    if m:
        full_path = Path(m.group(1))
        if full_path.exists():
            return full_path.read_text()
    return summary_content


def _post_forge_feedback(change_info, review_content: str, config: dict, forge) -> None:
    """Parse the review and post a summary comment (and optional vote) to the forge.

    Uses the summary file for the forge comment and vote (compact, well-structured),
    and the full review file (if referenced in the summary) for line comments.

    Errors are logged but never re-raised — a failed post must not prevent the
    review from being recorded locally.
    """
    model_name = config.get("model", "claude-sonnet-4-6")
    try:
        comment = extract_forge_comment(review_content, model_name)
        full_content = _find_full_review_content(review_content)
        line_comments = extract_line_comments(full_content)
        vote = determine_vote(review_content, config) if config.get("feedback_voting") else None

        vote_label = config.get("feedback_vote_label", "Code-Review")
        print(f"\n📤 Posting feedback to {change_info.forge_type}...")
        if vote is not None:
            sign = "+" if vote > 0 else ""
            print(f"   Vote ({vote_label}): {sign}{vote}")
        if line_comments:
            print(f"   Inline comments: {len(line_comments)}")

        ok = forge.post_feedback(change_info, comment, vote, line_comments)
        if ok:
            print("   ✅ Feedback posted successfully")
        else:
            print("   ⚠️  Feedback post returned failure (see warnings above)")
    except Exception as exc:
        print(f"   ⚠️  Could not post forge feedback: {exc}")


async def review_specific_change(change_url_or_number, requested_patchset=None):
    """Review a specific change by URL, change/PR/MR number, or forge URL.

    Args:
        change_url_or_number: Change number, PR/MR number, or full forge URL.
        requested_patchset:   Gerrit patchset to review (None = latest).
                              Silently ignored for GitHub/GitLab.
    """
    forge = create_forge_client(CONFIG)

    # Resolve the change via the forge client (replaces both old WebFetch AI calls)
    print(f"🔍 Resolving change: {change_url_or_number}")
    try:
        if re.match(r'^https?://', change_url_or_number):
            change = forge.get_change_from_url(change_url_or_number)
        else:
            # Bare number — require repo in config for GitHub/GitLab
            repos = CONFIG.get("octavia_repos", [])
            repo_hint = repos[0] if repos else None
            change = forge.get_change(change_url_or_number.strip(), repo_hint)
    except Exception as e:
        print(f"❌ Could not fetch change details: {e}")
        return

    # For Gerrit: honour requested_patchset by re-fetching with that patchset
    current_patchset = change.patchset
    patchset_ref = change.git_fetch_ref
    if change.forge_type == "gerrit" and requested_patchset:
        current_patchset = int(requested_patchset)
        last2 = str(change.change_id)[-2:].zfill(2)
        patchset_ref = f"refs/changes/{last2}/{change.change_id}/{current_patchset}"

    # For GitHub/GitLab: silently ignore patchset
    if change.forge_type != "gerrit" and requested_patchset:
        print(f"ℹ️  Patchset argument ignored for {change.forge_type} (no patchset concept)")

    repo_name = change.repo_name

    print(f"\n{'='*80}")
    print("📋 Change Details:")
    print(f"  Forge:      {change.forge_type}")
    print(f"  Repository: {repo_name}")
    print(f"  ID:         #{change.change_id}")
    print(f"  Title:      {change.title[:70]}")
    print(f"  Branch:     {change.branch}")
    if current_patchset:
        print(f"  Patchset:   {current_patchset}")
    print(f"  Fetch ref:  {patchset_ref}")
    print(f"  URL:        {change.forge_url}")
    print(f"{'='*80}\n")

    output_dir = Path(REVIEWS_OUTPUT_DIR)
    output_dir.mkdir(exist_ok=True, parents=True)

    # Load review history and get previous context
    tracking_file = Path(CONFIG["reviewed_changes_file"])
    history = load_review_history(tracking_file)
    previous_review_content, previous_record = load_previous_review_context(
        output_dir, change, history
    )
    previous_patchset = previous_record.patchset if previous_record else None
    previous_sequence = previous_record.sequence if previous_record else 0
    sequence = previous_sequence + 1

    # Create the review filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    review_file = create_review_filename(output_dir, change, sequence, timestamp)

    print(f"📄 Review will be saved to: {review_file.name}\n")

    # Local repo path (configurable, defaults to DevStack)
    repo_path = Path(REPO_BASE_PATH) / repo_name.split('/')[-1]

    if not repo_path.exists():
        print(f"❌ Repository not found at: {repo_path}")
        print("   Set forge.repo_base_path in config.json to the directory containing the clone.")
        return

    # Pre-flight checks
    print("🔍 Running pre-flight checks...\n")

    # Check repository is on main/master branch
    devstack_config = CONFIG.get("devstack", {})
    if devstack_config.get("verify_main_branch", True):
        print("📋 Checking repository branch...")
        branch_check = check_repo_on_main_branch(repo_path)
        if not branch_check.on_main:
            print(f"   ⚠️  {branch_check.error}")
            print(f"   Current branch: {branch_check.current_branch}")
            print("   Attempting to checkout main/master...")
            success, message = checkout_main_branch(repo_path)
            if success:
                print(f"   ✅ {message}")
            else:
                print(f"   ❌ {message}")
                print("   Review will proceed but may have issues")
        else:
            print(f"   ✅ On {branch_check.current_branch} branch")

    print("\n" + "="*80 + "\n")

    # Build the prompt with previous review context if available
    previous_review_section = ""
    if previous_review_content and previous_patchset:
        previous_review_section = """

## IMPORTANT: Previous Review Context

This change has been reviewed before. You previously reviewed **Patchset {previous_patchset}**.

**Previous Review Summary** (for context):
```
{previous_review_content[:3000]}
... (truncated for brevity)
```

**Your Task for This Review:**
- Focus on what changed between PS {previous_patchset} and PS {current_patchset or 'current'}
- Note if previous issues were addressed
- Identify new issues introduced in this patchset
- Comment on whether the change is moving in the right direction
- Include a "Changes Since Previous Review" section

"""
    elif previous_review_content:
        previous_review_section = """

## IMPORTANT: Previous Review Context

This change has been reviewed before.

**Previous Review Summary** (for context):
```
{previous_review_content[:3000]}
... (truncated for brevity)
```

**Your Task for This Review:**
- Note if previous issues were addressed
- Identify any new issues
- Include a "Changes Since Previous Review" section if you can determine what changed

"""

    # Note if reviewing a specific (potentially not latest) patchset
    specific_patchset_note = ""
    if change.forge_type == "gerrit" and requested_patchset:
        specific_patchset_note = (
            f"\n**NOTE**: You are reviewing a SPECIFIC patchset (PS {requested_patchset}), "
            "which may not be the latest version of this change.\n"
        )

    # Build and format the prompt (forge-aware)
    _provider = CONFIG.get("model_provider", "anthropic")
    prompt = get_code_review_prompt(
        repo_name=repo_name,
        change_number=change.change_id,
        current_patchset=current_patchset,
        gerrit_base_url=GERRIT_BASE_URL,        # kept for Gerrit prompt compat
        repo_path=repo_path,
        patchset_ref=patchset_ref,
        specific_patchset_note=specific_patchset_note,
        previous_review_section=previous_review_section,
        previous_patchset=previous_patchset,
        provider=_provider,
        save_path=str(review_file),
        forge_type=change.forge_type,
        forge_url=change.forge_url,
        sequence=sequence,
        head_sha=change.head_sha,
    )

    # Prompt loaded from prompts/code_review_prompt.txt
    # This keeps the code clean and makes the prompt easier to maintain and edit.

    print("🤖 Starting comprehensive code review...\n")

    _client = create_model_client(CONFIG)
    review_result = None
    usage_info = None
    try:
        _result = await _client.query(
            prompt=prompt,
            tools=["Bash", "Read", "Write", "Grep", "Glob"],
            on_progress=lambda text: print(f"  {text}"),
        )
        review_result = _result.text
        usage_info = format_usage_info(
            usage_data=_result.usage,
            cost_usd=_result.cost_usd,
            model=_result.model,
            duration_ms=_result.duration_ms,
        )

        print(f"\n{'='*80}")
        print("✅ Review Complete!")
        print(f"{'='*80}")
        print(f"\n📄 Review Document: {review_file}")
        print(f"\nSummary:\n{(review_result or '')[:500]}...")

        # Append usage info to review if available
        if review_result and usage_info:
            review_result = review_result + "\n\n---\n\n" + usage_info

        # Ensure the review file was created
        if not review_file.exists() and review_result:
            print("\n⚠️  Review file not found - saving result now...")
            review_file.write_text(review_result)
            print(f"✓ Saved review to: {review_file}")
        elif not review_file.exists():
            print("\n❌ WARNING: Review file was not created and no result received!")
            return
        else:
            # If file exists but we have usage info, append it
            if usage_info:
                existing_content = review_file.read_text()
                # Only append if not already present
                if "## Token Usage & Cost" not in existing_content:
                    review_file.write_text(existing_content + "\n\n---\n\n" + usage_info)
            print(f"\n✓ Review file confirmed at: {review_file}")

        # Record in forge-agnostic tracking
        if review_file.exists():
            record_review(tracking_file, change, sequence, review_file)

            # Optionally post feedback back to the forge
            if CONFIG.get("feedback_enabled"):
                final_content = review_file.read_text()
                _post_forge_feedback(change, final_content, CONFIG, forge)

    except Exception as e:
        print(f"\n❌ Error during review: {e}")
        import traceback
        traceback.print_exc()


def main():
    parser = argparse.ArgumentParser(
        description='Review an OpenStack Octavia change from OpenDev',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Review latest patchset
  %(prog)s 919846

  # Review specific patchset
  %(prog)s 919846 2
  %(prog)s 919846 --patchset 3

  # Review using URL
  %(prog)s https://review.opendev.org/c/openstack/octavia/+/919846

  # Review specific patchset using URL
  %(prog)s https://review.opendev.org/c/openstack/octavia/+/919846 2
        """
    )

    parser.add_argument(
        'change',
        help='Change number or Gerrit URL (e.g., 919846 or https://review.opendev.org/c/openstack/octavia/+/919846)'
    )

    parser.add_argument(
        'patchset',
        nargs='?',
        type=int,
        default=None,
        help='Specific patchset number to review (e.g., 2). If omitted, reviews the latest patchset.'
    )

    parser.add_argument(
        '--patchset', '-p',
        dest='patchset_flag',
        type=int,
        help='Alternative way to specify patchset number'
    )

    args = parser.parse_args()

    # Determine which patchset to use (positional arg takes precedence)
    patchset = args.patchset if args.patchset else args.patchset_flag

    if patchset:
        print(f"📌 Reviewing patchset {patchset}\n")

    asyncio.run(review_specific_change(args.change, patchset))


def cli_main():
    """Main entry point for command-line usage."""
    main()


if __name__ == "__main__":
    cli_main()
