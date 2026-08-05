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
from typing import NamedTuple, Optional
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
    get_branch_name,
    checkout_ref,
    get_commit_info,
    get_changed_files,
    expand_remote_branches,
    format_commit_info,
    format_changed_files,
    run_command_list,
    format_command_results,
    AuditRule,
    audit_report_file,
    build_audit_prompt,
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
    ChangeInfo,
    ModelClient,
    HelpOnErrorParser,
    add_change_args,
    add_post_args,
    add_summary_args,
    resolve_change_target,
    generate_summary,
    print_summary,
    needs_summary,
)

# Load configuration
CONFIG = load_config()
DEVSTACK_PATH = CONFIG["devstack_path"]
REVIEWS_OUTPUT_DIR = CONFIG["reviews_output_dir"]
GERRIT_BASE_URL = CONFIG["gerrit_base_url"]  # kept for backward compat with prompts
REPO_BASE_PATH = CONFIG.get("repo_base_path", DEVSTACK_PATH)


class _SafeDict(dict):
    """dict subclass for format_map() that leaves unknown {KEYS} unchanged."""
    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


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


def _build_bug_context(bug_refs: list, triage_dir: str) -> str:
    """Pre-fetch bug context for commit bug references.

    For each bug number found in the commit message, checks for a local
    triage report and returns a formatted summary.  Does not call the
    Launchpad API — the AI can do that via Bash if needed.
    """
    if not bug_refs:
        return "_No bug references found in the commit message._"

    parts = []
    triage_path = Path(triage_dir)
    for bug_num in bug_refs:
        parts.append(f"### Bug #{bug_num}")
        # Find the latest local triage report for this bug
        pattern = f"bug_{bug_num}_*.md"
        reports = sorted(triage_path.glob(pattern), reverse=True) if triage_path.exists() else []
        if reports:
            latest = reports[0]
            parts.append(f"**Local triage report**: `{latest.name}`")
            # Include the first 1500 chars as a summary
            text = latest.read_text(encoding="utf-8", errors="replace")
            excerpt = text[:1500]
            suffix = "\n...(truncated)" if len(text) > 1500 else ""
            parts.append(f"```\n{excerpt}{suffix}\n```")
        else:
            parts.append(
                f"_No local triage report found. If needed, the AI can query "
                f"https://api.launchpad.net/1.0/bugs/{bug_num} for basic info._"
            )

    return "\n\n".join(parts)


def _build_expanded_branches(repo_path: Path, config: dict) -> str:
    """Resolve configured backport branch patterns to real branch names."""
    patterns = config.get("backport_branches", [])
    if not patterns:
        return "_No backport branches configured._"

    lines = []
    for pattern in patterns:
        if "*" in pattern:
            real = expand_remote_branches(repo_path, pattern)
            if real:
                for b in real:
                    lines.append(f"- `{b}` (from pattern `{pattern}`)")
            else:
                lines.append(f"- _(no branches matching `{pattern}` found on remote)_")
        else:
            lines.append(f"- `{pattern}`")

    return "\n".join(lines) if lines else "_No backport branches resolved._"


# Audit rules for the code review report format
_CODE_REVIEW_AUDIT_RULES = [
    AuditRule.must_start_with("# Code Review:"),
    AuditRule.must_contain("## Final Verdict"),
    AuditRule.must_contain_one_of(
        ["✅ **Approve**", "🔄 **Request Changes**", "💬 **Needs Discussion**"],
        "Must contain exactly one verdict: ✅ Approve / 🔄 Request Changes / 💬 Needs Discussion",
    ),
    AuditRule.must_contain("## Backport Recommendation"),
    AuditRule.must_contain("END OF REPORT"),
]


class _ReviewPrefetch(NamedTuple):
    """Pre-fetched deterministic data gathered before the AI runs."""
    commit_info_text: str
    changed_files_text: str
    test_results_text: str
    bug_context_text: str
    expanded_backport_branches_text: str
    original_branch: str


def _checkout_patchset_with_retry(
    repo_path: Path,
    patchset_ref: str,
    head_sha: str,
    change_id: str,
    repo_name: str,
    max_retries: int = 3,
) -> bool:
    """Fetch and checkout a Gerrit patchset SHA with retry.  Returns True on success."""
    fetch_url = f"{GERRIT_BASE_URL}/{repo_name}"
    for attempt in range(1, max_retries + 1):
        print(f"🔄 Fetching patchset (attempt {attempt}/{max_retries})...")
        ok, msg = git_fetch_and_checkout_patchset(repo_path, fetch_url, patchset_ref, head_sha)
        if ok:
            print(f"   ✅ {msg}")
            return True
        print(f"   ❌ {msg}")
        if attempt < max_retries:
            delay = 5 * attempt
            print(f"   ⏳ Retrying in {delay}s...")
            time.sleep(delay)
    print(f"\n❌ Pre-flight checkout failed after {max_retries} attempts.")
    print(f"   Change: #{change_id}  Expected SHA: {head_sha}")
    print("   Aborting — review not recorded to avoid reviewing the wrong change.")
    return False


def _prefetch_review_data(
    repo_path: Path, config: dict, change: ChangeInfo, bp: _BackportSections
) -> _ReviewPrefetch:
    """Run all deterministic Python pre-flight data gathering before the AI runs."""
    original_branch = get_branch_name(repo_path) or "master"

    print("📊 Collecting git information...")
    commit_info = get_commit_info(repo_path)
    changed_files = get_changed_files(repo_path, max_diff_lines=config.get("max_diff_lines", 300))
    commit_info_text = format_commit_info(commit_info)
    changed_files_text = format_changed_files(changed_files, config.get("max_diff_lines", 300))
    if commit_info.get("error"):
        print(f"   ⚠️  git commit info: {commit_info['error']}")
    else:
        print(f"   ✅ Commit: {commit_info['short_sha']} — {commit_info['subject'][:60]}")
    if changed_files.get("error"):
        print(f"   ⚠️  git changed files: {changed_files['error']}")
    else:
        print(f"   ✅ {len(changed_files['names'])} file(s) changed")

    test_commands = config.get("test_commands", [])
    test_results_text = "_No test commands configured._"
    if test_commands and change.forge_type == "gerrit":
        print(f"\n🧪 Running {len(test_commands)} test command(s)...")
        test_results_text = format_command_results(run_command_list(test_commands, cwd=repo_path))
    else:
        print("   ℹ️  Skipping tests (not configured or non-Gerrit change)")

    bug_context_text = _build_bug_context(commit_info.get("bug_refs", []), bp.triage_dir)
    expanded_branches = _build_expanded_branches(repo_path, config)

    return _ReviewPrefetch(
        commit_info_text=commit_info_text,
        changed_files_text=changed_files_text,
        test_results_text=test_results_text,
        bug_context_text=bug_context_text,
        expanded_backport_branches_text=expanded_branches,
        original_branch=original_branch,
    )


def _load_report_template(
    change: ChangeInfo,
    current_patchset: Optional[int],
    previous_patchset: Optional[int],
    test_results_text: str,
    config: dict,
) -> str:
    """Pre-fill the review report template with known metadata."""
    template_path = Path(__file__).parent / "report_template.md"
    if not template_path.exists():
        return f"[Write the full review report here for change #{change.change_id}]"
    previous_label = f"Patchset {previous_patchset}" if previous_patchset else "First Review"
    return template_path.read_text(encoding="utf-8").format_map(
        _SafeDict(
            REPO_NAME=change.repo_name,
            CHANGE_NUMBER=str(change.change_id),
            PATCHSET=str(current_patchset or "unknown"),
            GERRIT_URL=change.forge_url,
            TIMESTAMP=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            MODEL_NAME=config.get("model", "claude-sonnet-4-6"),
            PREVIOUS_REVIEW=previous_label,
            TEST_RESULTS=test_results_text,
        )
    )


async def _audit_and_fix_report(
    client: ModelClient, review_file: Path, max_retries: int = 2
) -> None:
    """Validate report format; ask the AI to fix issues if needed."""
    for attempt in range(max_retries + 1):
        passed, errors = audit_report_file(review_file, _CODE_REVIEW_AUDIT_RULES)
        if passed:
            print("   ✅ Report format validated")
            return
        print(f"\n   ⚠️  Report format issues (attempt {attempt + 1}/{max_retries + 1}):")
        for err in errors:
            print(f"      - {err}")
        if attempt < max_retries:
            fix_prompt = (
                f"Read the review at {review_file} and fix these format problems, "
                f"then rewrite the entire file.\n\n"
                + build_audit_prompt(errors, str(review_file))
            )
            await client.query(
                prompt=fix_prompt,
                tools=["Read", "Write"],
                on_progress=lambda text: print(f"  {text}"),
            )
        else:
            print("   ⚠️  Report still invalid after retries — proceeding with best effort")


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
            repo_hint = next(iter(CONFIG.get("octavia_repos", [])), None)
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
    sequence = (previous_record.sequence if previous_record else 0) + 1

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
    if change.forge_type == "gerrit" and change.head_sha and patchset_ref:
        if not _checkout_patchset_with_retry(
            repo_path, patchset_ref, change.head_sha, change.change_id, repo_name
        ):
            if _stash_saved:
                git_stash_pop(repo_path)
            return
        print()

    # Pre-fetch all deterministic data (git info, test results, bug context, branches)
    _bp = _build_backport_sections(CONFIG)
    prefetch = _prefetch_review_data(repo_path, CONFIG, change, _bp)

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

    report_template = _load_report_template(
        change, current_patchset, previous_patchset, prefetch.test_results_text, CONFIG
    )

    # Build and format the prompt (forge-aware)
    prompt = get_code_review_prompt(
        repo_name=repo_name,
        change_number=change.change_id,
        current_patchset=current_patchset,
        gerrit_base_url=GERRIT_BASE_URL,
        repo_path=repo_path,
        patchset_ref=patchset_ref,
        specific_patchset_note=specific_patchset_note,
        previous_review_section=previous_review_section,
        previous_patchset=previous_patchset,
        provider=CONFIG.get("model_provider", "anthropic"),
        save_path=str(review_file),
        forge_type=change.forge_type,
        forge_url=change.forge_url,
        sequence=sequence,
        head_sha=change.head_sha,
        backport_branches_section=_bp.branches_section,
        backport_rules_section=_bp.rules_section,
        triage_reports_dir=_bp.triage_dir,
        commit_info_text=prefetch.commit_info_text,
        changed_files_text=prefetch.changed_files_text,
        test_results_text=prefetch.test_results_text,
        bug_context_text=prefetch.bug_context_text,
        expanded_backport_branches_text=prefetch.expanded_backport_branches_text,
        report_template=report_template,
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

        # Audit loop: validate report format; ask AI to fix if needed
        await _audit_and_fix_report(_client, review_file)

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
        # Restore repo to the branch it was on before the review checkout.
        # Python handles this so the prompt no longer needs a "return to branch" step.
        if change.forge_type == "gerrit" and change.head_sha:
            _ok, _msg = checkout_ref(repo_path, prefetch.original_branch)
            if _ok:
                print(f"   🔀 Restored branch: {prefetch.original_branch}")
            else:
                print(f"   ⚠️  Could not restore branch '{prefetch.original_branch}': {_msg}")
        if _stash_saved:
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


def cli_main():  # pylint: disable=too-many-branches,too-many-statements
    """Main entry point for command-line usage."""
    global REVIEWS_OUTPUT_DIR  # pylint: disable=global-statement
    parser = HelpOnErrorParser(
        description='Review an OpenStack Octavia change from OpenDev',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Review latest patchset of a change
  %(prog)s --change 919846

  # Review a specific patchset
  %(prog)s --change 919846 --patchset 3

  # Review by forge URL (Gerrit/GitHub)
  %(prog)s --url https://review.opendev.org/c/openstack/octavia/+/919846

  # Save review to a custom directory
  %(prog)s --change 919846 --output-dir /tmp/reviews

  # Re-post an already-completed review to the forge (no re-review)
  %(prog)s --change 919846 --post-only
  %(prog)s --change 919846 --patchset 5 --post-only

  # Run the review but do not post results to the forge
  %(prog)s --change 919846 --no-post

  # Print a short summary of the review after running
  %(prog)s --change 919846 --print-summary

  # Post only the summary to the forge (not the full review)
  %(prog)s --change 919846 --post-summary
        """,
    )
    add_change_args(parser, CONFIG)
    add_post_args(parser)
    add_summary_args(parser)
    args = parser.parse_args()

    change_ref, patchset, output_dir, _skip = resolve_change_target(args, CONFIG)
    _summary_prompt = Path(__file__).parent / "prompts" / "code_review_summary_prompt.txt"

    if not change_ref and not args.post_only:
        parser.error("--change or --url is required")

    if args.no_post:
        CONFIG["feedback_enabled"] = False
        print("📵 Forge posting disabled (--no-post)\n")

    if args.post_summary:
        CONFIG["feedback_enabled"] = False

    if args.post_only:
        if not change_ref:
            parser.error("--post-only requires --change or --url")
        output_dir_path = Path(REVIEWS_OUTPUT_DIR)
        ps_glob = f"ps{patchset}_" if patchset else "ps*_"
        cid = re.search(r'(\d+)', change_ref or "")
        pattern = f"review_*_{cid.group(1)}_{ps_glob}*.md" if cid else "review_*.md"
        review_file = find_latest_report(output_dir_path, pattern)
        if needs_summary(args, CONFIG) and review_file:
            summary = generate_summary(review_file, _summary_prompt, CONFIG)
            if summary:
                print_summary(summary, review_file)
        if not args.post_summary:
            ok = _post_only(change_ref, patchset)
            sys.exit(0 if ok else 1)
        elif review_file:
            forge = create_forge_client(CONFIG)
            _rchg = re.match(r'^https?://', change_ref)
            change = forge.get_change_from_url(change_ref) if _rchg \
                else forge.get_change(change_ref.strip(), next(iter(CONFIG.get("octavia_repos", [])), None))
            summary = generate_summary(review_file, _summary_prompt, CONFIG)
            if summary:
                model_name = CONFIG.get("model", "claude-sonnet-4-6")
                comment = (
                    f"*Code review summary by {model_name}*\n\n{summary}\n\n"
                    "---\n*This summary was generated by an AI and may contain errors.*"
                )
                forge.post_feedback(change, comment, vote=None, line_comments=[])
        return

    if args.output_dir:
        REVIEWS_OUTPUT_DIR = str(output_dir)

    if patchset:
        print(f"📌 Reviewing patchset {patchset}\n")

    asyncio.run(review_specific_change(change_ref, patchset))

    if needs_summary(args, CONFIG):
        output_dir_path = Path(REVIEWS_OUTPUT_DIR)
        ps_glob = f"ps{patchset}_" if patchset else "ps*_"
        cid = re.search(r'(\d+)', change_ref or "")
        pattern = f"review_*_{cid.group(1)}_{ps_glob}*.md" if cid else "review_*.md"
        review_file = find_latest_report(output_dir_path, pattern)
        summary = generate_summary(review_file, _summary_prompt, CONFIG) if review_file else None
        if summary:
            print_summary(summary, review_file)
            if args.post_summary and review_file:
                forge = create_forge_client(CONFIG)
                _rchg = re.match(r'^https?://', change_ref)
                _repo_hint = next(iter(CONFIG.get("octavia_repos", [])), None)
                change = forge.get_change_from_url(change_ref) if _rchg \
                    else forge.get_change(change_ref.strip(), _repo_hint)
                model_name = CONFIG.get("model", "claude-sonnet-4-6")
                comment = (
                    f"*Code review summary by {model_name}*\n\n{summary}\n\n"
                    "---\n*This summary was generated by an AI and may contain errors.*"
                )
                forge.post_feedback(change, comment, vote=None, line_comments=[])
        else:
            print("ℹ️  No output file produced — summary not available.")


if __name__ == "__main__":
    cli_main()
