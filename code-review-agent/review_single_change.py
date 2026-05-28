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
import dataclasses
import sys
import re
import argparse
import time
from datetime import datetime
from pathlib import Path
from typing import NamedTuple
# Add current directory to path to import config
sys.path.insert(0, str(Path(__file__).parent))
from config import load_config
from prompts import get_code_review_prompt
from forge_feedback import extract_forge_comment, extract_line_comments, determine_vote
from agents_lib import (
    check_repo_on_main_branch,
    checkout_main_branch,
    git_stash_save,
    git_stash_pop,
    git_fetch_and_checkout_patchset,
    create_model_client,
    format_usage_info,
    create_forge_client,
    load_context_section,
    load_review_history,
    load_previous_review_context,
    record_review,
    create_review_filename,
    determine_backport_vote,
    find_latest_report,
)

# Load configuration
CONFIG = load_config()
DEVSTACK_PATH = CONFIG["devstack_path"]
REVIEWS_OUTPUT_DIR = CONFIG["reviews_output_dir"]
GERRIT_BASE_URL = CONFIG["gerrit_base_url"]  # kept for backward compat with prompts
REPO_BASE_PATH = CONFIG.get("repo_base_path", DEVSTACK_PATH)


def _find_full_review_content(summary_content: str) -> str:
    """Return the full review if the AI wrote it to a path referenced in the summary.

    When the AI writes the detailed review to its working directory (e.g.
    /opt/stack/octavia/) it mentions that path in its text response.  This
    function detects that path, reads the full file, and returns it so the
    tracking-directory file can contain the complete report rather than just
    the brief summary text.

    Returns the full content when found, otherwise returns an empty string
    (letting the caller fall back to the summary text).
    """
    m = re.search(r'saved to\s+[`\']?(/[^\s`\']+\.md)[`\']?', summary_content, re.IGNORECASE)
    if m:
        full_path = Path(m.group(1))
        if full_path.exists():
            return full_path.read_text(encoding="utf-8")
    return ""


def _post_forge_feedback(change_info, review_content: str, config: dict, forge) -> bool:
    """Parse the review and post a summary comment (and optional vote) to the forge.

    review_content is the full consolidated report (already resolved by the caller),
    so no secondary file lookup is needed.

    Returns True on success, False on any failure. Errors are logged but never
    re-raised — a failed post must not prevent the review from being recorded locally.
    """
    model_name = config.get("model", "claude-sonnet-4-6")
    try:
        comment = extract_forge_comment(review_content, model_name)
        line_comments = extract_line_comments(review_content)
        vote = determine_vote(review_content, config) if config.get("feedback_voting") else None

        vote_label = config.get("feedback_vote_label", "Code-Review")
        print(f"\n📤 Posting feedback to {change_info.forge_type}...")
        if vote is not None:
            sign = "+" if vote > 0 else ""
            print(f"   Vote ({vote_label}): {sign}{vote}")
        if line_comments:
            print(f"   Inline comments: {len(line_comments)}")

        # Backport-Candidate vote (disabled by default, separate from Code-Review)
        extra_labels = None
        if config.get("feedback_backport_voting"):
            bp_vote = determine_backport_vote(review_content)
            if bp_vote is not None:
                bp_label = config.get("feedback_backport_vote_label", "Backport-Candidate")
                bp_score = config.get("feedback_backport_recommend_score", 1)
                bp_actual_score = bp_score if bp_vote else 0
                extra_labels = {bp_label: bp_actual_score}
                sign = "+" if bp_actual_score > 0 else ""
                print(f"   Vote ({bp_label}): {sign}{bp_actual_score}")

        ok = forge.post_feedback(change_info, comment, vote, line_comments,
                                 extra_labels=extra_labels)
        if ok:
            print("   ✅ Feedback posted successfully")
        else:
            print("   ⚠️  Feedback post returned failure (see warnings above)")
        return ok
    except Exception as exc:
        print(f"   ⚠️  Could not post forge feedback: {exc}")
        return False


class _BackportSections(NamedTuple):
    branches_section: str
    rules_section: str
    triage_dir: str


def _build_backport_sections(config: dict) -> _BackportSections:
    """Build the backport-related prompt sections from config."""
    branches = config.get("backport_branches", [])
    if branches:
        branches_section = (
            "The following branch patterns are configured as backport targets "
            "(wildcards like `stable/*` are supported — expand each pattern "
            "to real branches before checking):\n"
            + "\n".join(f"- `{b}`" for b in branches)
        )
    else:
        branches_section = "No backport target branches are configured."

    rules_section = ""
    rules_file = config.get("backport_rules_file")
    if rules_file:
        rules_path = Path(str(rules_file)).expanduser()
        if rules_path.exists():
            rules_section = rules_path.read_text(encoding="utf-8")
        else:
            print(f"⚠️  Backport rules file not found: {rules_path}")

    triage_dir = str(
        Path(config.get("triages_output_dir", "~/octavia_bug_triages")).expanduser()
    )
    return _BackportSections(branches_section, rules_section, triage_dir)


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

    # Check repository is on main/master branch; stash local changes first so
    # the checkout can succeed even when the developer has uncommitted edits.
    _stash_saved = False
    devstack_config = CONFIG.get("devstack", {})
    if devstack_config.get("verify_main_branch", True):
        print("📋 Checking repository branch...")
        branch_check = check_repo_on_main_branch(repo_path)
        if not branch_check.on_main:
            print(f"   ⚠️  {branch_check.error}")
            print(f"   Current branch: {branch_check.current_branch}")
            _stash_saved = git_stash_save(repo_path)
            if _stash_saved:
                print("   📦 Stashed local changes")
            print("   Attempting to checkout main/master...")
            success, message = checkout_main_branch(repo_path)
            if success:
                print(f"   ✅ {message}")
            else:
                print(f"   ❌ {message}")
                if _stash_saved:
                    git_stash_pop(repo_path)
                    _stash_saved = False
                print("   Review will proceed but may have issues")
        else:
            print(f"   ✅ On {branch_check.current_branch} branch")

    print("\n" + "="*80 + "\n")

    # Pre-flight patchset checkout with SHA verification and retry.
    # This runs before the AI so that if git fetch fails or FETCH_HEAD is
    # stale the review is aborted rather than silently reviewing the wrong code.
    _MAX_CHECKOUT_RETRIES = 3
    if change.forge_type == "gerrit" and change.head_sha and patchset_ref:
        fetch_url = f"{GERRIT_BASE_URL}/{repo_name}"
        _checkout_ok = False
        for _attempt in range(1, _MAX_CHECKOUT_RETRIES + 1):
            print(f"🔄 Fetching patchset (attempt {_attempt}/{_MAX_CHECKOUT_RETRIES})...")
            _ok, _msg = git_fetch_and_checkout_patchset(
                repo_path, fetch_url, patchset_ref, change.head_sha
            )
            if _ok:
                print(f"   ✅ {_msg}")
                _checkout_ok = True
                break
            print(f"   ❌ {_msg}")
            if _attempt < _MAX_CHECKOUT_RETRIES:
                _delay = 5 * _attempt
                print(f"   ⏳ Retrying in {_delay}s...")
                time.sleep(_delay)

        if not _checkout_ok:
            print(f"\n❌ Pre-flight checkout failed after {_MAX_CHECKOUT_RETRIES} attempts.")
            print(f"   Change: #{change.change_id}  Expected SHA: {change.head_sha}")
            print("   Aborting — review not recorded to avoid reviewing the wrong change.")
            if _stash_saved:
                git_stash_pop(repo_path)
            return

        print()

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

    # Build backport-related prompt sections
    _bp = _build_backport_sections(CONFIG)  # (branches_section, rules_section, triage_dir)

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
        backport_branches_section=_bp.branches_section,
        backport_rules_section=_bp.rules_section,
        triage_reports_dir=_bp.triage_dir,
    )

    # Prepend cross-run context (rules, global learnings, agent learnings)
    _ctx = load_context_section(CONFIG, "code_review")
    if _ctx:
        prompt = _ctx + "\n\n---\n\n" + prompt

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

        # Resolve the canonical report content.
        # The prompt instructs the AI to write the full review directly to
        # save_path (= review_file) via the Write tool.  Reading review_file
        # back is therefore more reliable than parsing a path out of the text
        # response.  Fall back to the text response only when the file is
        # absent or suspiciously short (< 500 chars — indicates a failed write).
        if review_file.exists() and review_file.stat().st_size > 500:
            content_to_save = review_file.read_text(encoding="utf-8")
        else:
            # Legacy fallback: AI may have written to a different path and
            # mentioned it in its text response.
            content_to_save = _find_full_review_content(review_result or "") or review_result

        if not content_to_save:
            print("\n❌ WARNING: No review content received — aborting.")
            return

        # Append usage info once if not already present
        if usage_info and "## Token Usage & Cost" not in content_to_save:
            content_to_save += "\n\n---\n\n" + usage_info
        review_file.write_text(content_to_save, encoding="utf-8")
        print(f"\n✓ Full review saved to: {review_file}")

        # Record in forge-agnostic tracking
        record_review(tracking_file, change, sequence, review_file)

        # Optionally post feedback back to the forge
        if CONFIG.get("feedback_enabled"):
            _post_forge_feedback(change, review_file.read_text(encoding="utf-8"), CONFIG, forge)

    except Exception as e:
        print(f"\n❌ Error during review: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if _stash_saved:
            # Reuse success/message rather than introducing new local names
            success, message = git_stash_pop(repo_path)
            if success:
                print(f"   📦 Restored stashed changes ({repo_path.name})")
            else:
                print(f"   ⚠️  Could not restore stash for {repo_path.name}: {message}")


def _post_only(change_ref: str, patchset: "int | None") -> bool:
    """Resolve a change, find the latest saved review file, and post it to the forge.

    Returns True on success, False on any failure.
    """
    forge = create_forge_client(CONFIG)

    print(f"🔍 Resolving change: {change_ref}")
    try:
        if re.match(r'^https?://', change_ref):
            change = forge.get_change_from_url(change_ref)
        else:
            repos = CONFIG.get("octavia_repos", [])
            repo_hint = repos[0] if repos else None
            change = forge.get_change(change_ref.strip(), repo_hint)
    except Exception as exc:
        print(f"❌ Could not fetch change details: {exc}")
        return False

    if patchset and change.forge_type == "gerrit":
        change = dataclasses.replace(change, patchset=patchset)

    output_dir = Path(REVIEWS_OUTPUT_DIR)
    change_id = str(change.change_id)
    ps_glob = f"ps{patchset}_" if patchset else "ps*_"
    pattern = f"review_*_{change_id}_{ps_glob}*.md"
    review_file = find_latest_report(output_dir, pattern)
    if not review_file:
        print(f"❌ No review file found matching {pattern} in {output_dir}")
        return False

    print(f"📄 Using review file: {review_file.name}")
    review_content = review_file.read_text(encoding="utf-8")

    return _post_forge_feedback(change, review_content, CONFIG, forge)


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

  # Re-post an already-completed review to the forge (no re-review)
  %(prog)s 919846 --post-only
  %(prog)s 919846 5 --post-only
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

    parser.add_argument(
        '--post-only',
        action='store_true',
        help='Skip the review; find the latest saved review file and post it to the forge.'
    )

    args = parser.parse_args()

    # Determine which patchset to use (positional arg takes precedence)
    patchset = args.patchset if args.patchset else args.patchset_flag

    if args.post_only:
        ok = _post_only(args.change, patchset)
        sys.exit(0 if ok else 1)

    if patchset:
        print(f"📌 Reviewing patchset {patchset}\n")

    asyncio.run(review_specific_change(args.change, patchset))


def cli_main():
    """Main entry point for command-line usage."""
    main()


if __name__ == "__main__":
    cli_main()
