#!/usr/bin/env python3
"""
DevStack Test Agent

Watches for new code review files and tests changes in DevStack environment.
Operates asynchronously from code review agent to improve throughput.
"""
import argparse
import asyncio
import subprocess
import sys
from pathlib import Path
from datetime import datetime
# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from agents_lib import (
    load_tracking_file,
    should_process_item,
    record_processed_item,
    find_latest_report,
    check_devstack_health,
    check_repo_on_main_branch,
    checkout_main_branch,
    git_stash_save,
    git_stash_pop,
    devstack_lock,
    get_unique_resource_prefix,
    load_context_section,
    notify_report,
    load_notifications_config,
    create_model_client,
    create_forge_client,
    extract_devstack_forge_comment,
)
from config import load_config
from feedback_parser import has_devstack_feedback, process_feedback
from report_validator import validate_report
from review_parser import parse_review_file, should_test_review


class _SafeDict(dict):
    """dict subclass used with format_map() to leave unknown {KEYS} unchanged.

    When the report template is pre-filled, known variables are substituted
    and any unrecognised keys survive intact so the AI sees them verbatim.
    """
    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


# Load configuration
CONFIG = None


def load_config_module():
    """Load configuration from config.json or config.sample.json."""
    global CONFIG
    CONFIG = load_config()
    return CONFIG


async def test_change_in_devstack(
    review_info,
    config: dict,
    specific_tests: "list[str] | None" = None,
    trigger: str = "new review",
) -> tuple[bool, str]:
    """
    Test a code change in DevStack using AI agent.

    Args:
        review_info:    Parsed review information.
        config:         Configuration dictionary.
        specific_tests: When provided, only these test names are run (user
                        feedback re-run).  None means run the full suite.
        trigger:        Human-readable string describing why this run was
                        started, e.g. "new review", "feedback: full re-run",
                        "feedback: 2 specific test(s)", "manual (CLI)".

    Returns:
        Tuple of (success, test_results_file_path)
    """
    print(f"\n{'='*80}")
    print(f"🧪 Testing Change in DevStack  [{trigger}]")
    print(f"📋 Repository: {review_info.repo_name}")
    print(f"📋 Change:     #{review_info.change_number} PS{review_info.patchset}")
    print(f"📋 Gerrit:     {review_info.gerrit_url}")
    print(f"{'='*80}\n")

    # Acquire DevStack lock
    agent_name = f"devstack-test-{review_info.change_number}"
    lock_timeout = config["devstack"]["lock_timeout"]

    print(f"🔒 Acquiring DevStack lock (timeout: {lock_timeout}s)...")

    try:
        with devstack_lock(agent_name, timeout=lock_timeout):
            print("   ✅ DevStack lock acquired\n")

            # Generate unique resource prefix
            resource_prefix = get_unique_resource_prefix("test")

            # Prepare prompt
            repo_path = Path(config["devstack_path"]) / review_info.repo_name.split('/')[-1]

            # Stash local changes and ensure the repo is on main/master before
            # the AI fetches and applies the patchset.
            stashed = False
            print("📋 Checking repository branch...")
            branch_check = check_repo_on_main_branch(repo_path)
            if not branch_check.on_main:
                print(f"   ⚠️  Not on main branch (on '{branch_check.current_branch}')")
                stashed = git_stash_save(repo_path)
                if stashed:
                    print("   📦 Stashed local changes")
                ok, msg = checkout_main_branch(repo_path)
                print(f"   {'✅' if ok else '⚠️ '} {msg}")
            else:
                print(f"   ✅ On {branch_check.current_branch} branch")

            # Construct patchset ref
            last_two = str(review_info.change_number)[-2:]
            patchset_ref = f"refs/changes/{last_two}/{review_info.change_number}/{review_info.patchset}"

            # Pre-flight: fetch the patchset ref in Python to confirm it is
            # accessible before spending API tokens on the AI agent.
            print(f"📡 Pre-fetching patchset ref {patchset_ref}...")
            _fetch = subprocess.run(  # nosec B603 B607
                ["git", "fetch", review_info.gerrit_url, patchset_ref],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            if _fetch.returncode == 0:
                print("   ✅ Patchset ref fetched successfully")
            else:
                print(f"   ⚠️  git fetch returned {_fetch.returncode}: {_fetch.stderr.strip()}")
                print("   Proceeding — AI agent will re-attempt the fetch")

            # Results file (temp location, will be incorporated into review)
            results_file = Path(
                f"/tmp/devstack_test_{review_info.change_number}_ps{review_info.patchset}.md"  # nosec B108
            )

            # Load and pre-fill the report template with known values.
            # The AI fills in the [instruction] markers; Python fills {UPPERCASE} vars.
            _template_path = Path(__file__).parent / "report_template.md"
            _template_filled = _template_path.read_text(encoding="utf-8").format_map(
                _SafeDict(
                    REPO_NAME=review_info.repo_name,
                    CHANGE_NUMBER=str(review_info.change_number),
                    PATCHSET=str(review_info.patchset),
                    GERRIT_URL=review_info.gerrit_url,
                    TIMESTAMP=datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC"),
                    MODEL_NAME=config.get("model", "claude-sonnet-4-6"),
                    RESOURCE_PREFIX=resource_prefix,
                )
            )

            # Load prompt template via provider-aware loader
            _prompts_dir = Path(__file__).parent / "prompts"
            _provider = config.get("model_provider", "anthropic")
            from agents_lib import load_agent_prompt as _lap
            prompt_template = _lap(
                "devstack_test", provider=_provider,
                prompts_dir=_prompts_dir, save_path=str(results_file),
            )

            # Format prompt
            prompt = prompt_template.format(
                repo_name=review_info.repo_name,
                change_number=review_info.change_number,
                patchset=review_info.patchset,
                gerrit_url=review_info.gerrit_url,
                repo_path=str(repo_path),
                resource_prefix=resource_prefix,
                gerrit_base_url=config["gerrit_base_url"],
                patchset_ref=patchset_ref,
                openrc_file=config["openrc_file"],
                results_file=str(results_file),
                current_timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                report_template=_template_filled,
            )

            # Append specific-tests section when running a user-requested subset
            if specific_tests:
                test_list = "\n".join(f"- `{t}`" for t in specific_tests)
                prompt += (
                    "\n\n## Specific Tests Requested (User Feedback)\n\n"
                    "Run ONLY the following tests — do not run the full suite:\n\n"
                    f"{test_list}\n"
                )

            # Prepend cross-run context
            _ctx = load_context_section(config, "devstack_test")
            if _ctx:
                prompt = _ctx + "\n\n---\n\n" + prompt

            print("🤖 Starting DevStack integration testing...\n")

            # Create the model client before the try-block so it is always in
            # scope for the audit retry calls that come after the main query.
            _client = create_model_client(config)

            # Run test with AI agent; always pop stash on exit
            test_result = None
            try:
                _res = await _client.query(
                    prompt=prompt,
                    tools=["Bash", "Read", "Write", "Grep"],
                    on_progress=lambda text: print(f"  {text}"),
                )
                test_result = _res.text
                print(f"\n{'='*80}")
                print("✅ Testing Complete!")
                print(f"{'='*80}")

                # Check if results file was created
                if not results_file.exists():
                    if test_result:
                        print("\n⚠️  Results file not found - saving manually...")
                        results_file.write_text(test_result, encoding="utf-8")
                        print(f"✓ Saved results to: {results_file}")
                    else:
                        print("\n❌ No test results generated")
                        return (False, "")

                print(f"\n✓ Test results saved to: {results_file}")

                # Audit loop: validate report format; ask AI to fix if needed.
                _MAX_AUDIT_RETRIES = 2
                for _audit_attempt in range(_MAX_AUDIT_RETRIES + 1):
                    _audit_errors = validate_report(results_file)
                    if not _audit_errors:
                        print("   ✅ Report format validated")
                        break
                    print(
                        f"\n   ⚠️  Report format issues "
                        f"(attempt {_audit_attempt + 1}/{_MAX_AUDIT_RETRIES + 1}):"
                    )
                    for _err in _audit_errors:
                        print(f"      - {_err}")
                    if _audit_attempt < _MAX_AUDIT_RETRIES:
                        _error_list = "\n".join(f"- {e}" for e in _audit_errors)
                        _fix_prompt = (
                            f"The report at {results_file} has these format problems:\n"
                            f"{_error_list}\n\n"
                            f"Read the report, fix every issue, and rewrite the entire "
                            f"file to {results_file}. Required sections:\n"
                            f"- '# DevStack Integration Testing' as the first heading\n"
                            f"- '## Summary' section\n"
                            f"- '## Test Results Summary' section with "
                            f"'**Overall Status:**'\n"
                            f"- At least one '### Test N: Name' section\n"
                            f"- 'END OF REPORT' as the final line"
                        )
                        await _client.query(
                            prompt=_fix_prompt,
                            tools=["Read", "Write"],
                            on_progress=lambda text: print(f"  {text}"),
                        )
                    else:
                        print(
                            "   ⚠️  Report still invalid after retries "
                            "— proceeding with best effort"
                        )

                return (True, str(results_file))

            except Exception as e:
                print(f"\n❌ Error during testing: {e}")
                import traceback
                traceback.print_exc()
                return (False, "")

            finally:
                if stashed:
                    pop_ok, pop_msg = git_stash_pop(repo_path)
                    if pop_ok:
                        print(f"   📦 Restored stashed changes ({repo_path.name})")
                    else:
                        print(f"   ⚠️  Could not restore stash for {repo_path.name}: {pop_msg}")

    except RuntimeError as e:
        # Could not acquire lock
        print(f"\n⚠️  {e}")
        print("   DevStack is locked by another agent")
        print("   Will retry on next pass")
        return (False, "")


def _post_devstack_feedback(review_info, test_report: Path, config: dict) -> None:
    """Post DevStack test results as an informational forge comment.

    No vote is cast — the comment is informational only, same as the CI
    Failure Agent. Errors are logged but never re-raised.
    """
    if not config.get("feedback", {}).get("post_to_forge"):
        return
    try:
        forge = create_forge_client(config)
        change_info = forge.get_change(review_info.change_number)
        model_name = config.get("model", "claude-sonnet-4-6")
        comment = extract_devstack_forge_comment(
            test_report.read_text(encoding="utf-8"),
            model_name,
            change_number=review_info.change_number,
            patchset=review_info.patchset,
        )
        print(f"\n📤 Posting DevStack test feedback to {change_info.forge_type}...")
        ok = forge.post_feedback(change_info, comment, vote=None, line_comments=[])
        if ok:
            print("   ✅ Feedback posted successfully")
        else:
            print("   ⚠️  Feedback post returned failure (see warnings above)")
    except Exception as exc:  # pylint: disable=broad-except
        print(f"   ⚠️  Could not post forge feedback: {exc}")


def _post_devstack_failure_feedback(review_info, config: dict) -> None:
    """Post a brief failure notice to the forge when DevStack tests did not pass.

    No vote is cast — informational only.
    """
    if not config.get("feedback", {}).get("post_to_forge"):
        return
    try:
        forge = create_forge_client(config)
        change_info = forge.get_change(review_info.change_number)
        model_name = config.get("model", "claude-sonnet-4-6")
        comment = (
            f"*DevStack integration tests by {model_name}*\n\n"
            f"**Overall Status**: ❌ FAIL\n\n"
            f"DevStack integration tests did not complete successfully for "
            f"{review_info.repo_name} #{review_info.change_number} "
            f"PS{review_info.patchset}. Check the agent logs for details.\n\n"
            "---\n*This report was generated by an AI and may contain errors.*"
        )
        print(f"\n📤 Posting DevStack test failure feedback to {change_info.forge_type}...")
        ok = forge.post_feedback(change_info, comment, vote=None, line_comments=[])
        if ok:
            print("   ✅ Feedback posted successfully")
        else:
            print("   ⚠️  Feedback post returned failure (see warnings above)")
    except Exception as exc:  # pylint: disable=broad-except
        print(f"   ⚠️  Could not post forge feedback: {exc}")


def create_test_report(
    review_file: Path,
    test_results_file: Path,
    output_dir: Path,
) -> "Path | None":
    """
    Create a new testing_report_* file combining the review and test results.

    The original review file is left untouched. The new file contains the full
    review content followed by the DevStack test results.

    Args:
        review_file:      Path to the original review markdown file.
        test_results_file: Path to the temporary test results file.
        output_dir:       Directory in which to write the test report.

    Returns:
        Path to the created test report, or None on failure.
    """
    print("\n📝 Creating test report...")

    try:
        review_content = review_file.read_text(encoding="utf-8")
        # The AI now writes a fully structured report following the template.
        # Use the complete output; no preamble stripping needed.
        test_content = Path(test_results_file).read_text(encoding="utf-8")

        # Derive test report filename from review filename, replacing prefix and timestamp.
        # review_openstack_octavia_932847_ps1_20260402_090051.md
        # → testing_report_openstack_octavia_932847_ps1_20260507_143022.md
        stem_parts = review_file.stem.split('_')
        middle_parts = stem_parts[1:-2]  # strip 'review' prefix and old timestamp
        new_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_stem = 'testing_report_' + '_'.join(middle_parts) + '_' + new_timestamp
        test_report_file = output_dir / f"{new_stem}.md"

        # Combine: code review content + separator + template-based test report.
        # The test_content starts with "# DevStack Integration Testing" (from the
        # template), so extract_devstack_forge_comment() will find it correctly.
        combined = (
            review_content.rstrip() +
            "\n\n---\n\n" +
            test_content
        )
        test_report_file.write_text(combined, encoding="utf-8")
        print(f"   ✅ Created: {test_report_file.name}")

        # Cleanup temp file
        Path(test_results_file).unlink(missing_ok=True)

        return test_report_file

    except Exception as e:
        print(f"   ❌ Error creating test report: {e}")
        return None


async def main():
    """Main entry point - find and test new reviews."""
    print("\n" + "="*80)
    print("DevStack Test Agent")
    print("="*80 + "\n")

    # Load configuration
    config = load_config_module()

    print("Configuration:")
    print(f"  Reviews directory: {config['reviews_directory']}")
    print(f"  DevStack path: {config['devstack_path']}")
    print(f"  Lock timeout: {config['devstack']['lock_timeout']}s")
    print()

    # Load common inputs used by both the health-fail path and the test path.
    tracking_file = Path(config["tracking"]["tested_reviews_file"])
    reviews_dir = Path(config["reviews_directory"])
    allowed_repos = config["filters"]["only_test_repositories"]

    if not reviews_dir.exists():
        print(f"❌ Reviews directory does not exist: {reviews_dir}")
        return

    review_files = sorted(
        reviews_dir.glob("review_*.md"), key=lambda p: p.stat().st_mtime, reverse=True
    )

    if not review_files:
        print(f"No review files found in {reviews_dir}")
        return

    print(f"📋 Found {len(review_files)} review file(s)\n")

    latest_patchset = _compute_latest_patchsets(review_files)

    # Check DevStack health
    print("🏥 Checking DevStack health...")
    health = check_devstack_health(config)
    if not health.all_healthy:
        print("   ❌ DevStack is not healthy!")
        for error in health.errors:
            print(f"      - {error}")
        print("\n⚠️  Cannot run tests - DevStack environment needs attention")
        # Record env failure for the review that would have been tested so it
        # gets an audit trail entry and is automatically retried when healthy.
        tested_reviews = load_tracking_file(tracking_file)
        review_info, review_file, review_id = _find_next_review(
            review_files, tested_reviews, latest_patchset, allowed_repos
        )
        if review_info and review_file and review_id:
            _record_test_result(
                review_info, review_file, tracking_file,
                "environment_error", retry_on_recovery=True,
            )
            print(
                f"   📝 Recorded env failure for "
                f"{review_info.repo_name} #{review_info.change_number} "
                f"(will retry when DevStack is healthy)"
            )
        return

    print("   ✅ DevStack is healthy\n")

    # Process reviews
    tested_reviews = load_tracking_file(tracking_file)
    tested_count = 0

    # Feedback-triggered re-runs take priority over new reviews
    feedback_ran = await _handle_feedback_run(
        tested_reviews, reviews_dir, tracking_file, config
    )
    if feedback_ran:
        tested_count += 1

    if tested_count > 0:
        print("\n" + "="*80)
        print("✅ DevStack test cycle complete!")
        print("="*80)
        return

    review_info, review_file, review_id = _find_next_review(
        review_files, tested_reviews, latest_patchset, allowed_repos
    )

    if review_info and review_file and review_id:
        print(f"▶  Next: {review_info.repo_name} #{review_info.change_number} PS{review_info.patchset}")

        # Verify the change is still open in Gerrit before spending DevStack resources.
        # Changes that are MERGED or ABANDONED are recorded as skipped so they are not
        # re-selected on future cycles.
        _run_test = True
        if config.get("filters", {}).get("skip_merged", True):
            try:
                _forge = create_forge_client(config)
                _ci = _forge.get_change(review_info.change_number, review_info.repo_name)
                if _ci.status and _ci.status.upper() not in ("NEW", "DRAFT"):
                    print(
                        f"⏭️  Change #{review_info.change_number} is {_ci.status} "
                        f"— skipping and recording so it is not re-selected"
                    )
                    _record_test_result(
                        review_info, review_file, tracking_file,
                        f"skipped_{_ci.status.lower()}",
                    )
                    _run_test = False
            except Exception as _status_err:  # pylint: disable=broad-except
                print(f"   ⚠️  Could not verify change status: {_status_err} — proceeding")

        if _run_test:
            success, test_results_file = await test_change_in_devstack(
                review_info, config, trigger="new review"
            )

            if success and test_results_file:
                # Create a new testing_report_* file (review file is not modified)
                test_report = create_test_report(
                    review_file, Path(test_results_file), reviews_dir
                )
                if test_report:
                    _record_test_result(review_info, review_file, tracking_file, "success", test_report)
                    tested_count += 1
                    print(f"\n✅ Test complete for {review_info.repo_name} #{review_info.change_number}")
                    notify_report(
                        report_path=test_report,
                        subject=(
                            f"DevStack Test: {review_info.repo_name} "
                            f"#{review_info.change_number} PS{review_info.patchset}"
                        ),
                        summary="DevStack integration test passed",
                        agent_config=config,
                        notifications_config=load_notifications_config(),
                    )
                    _post_devstack_feedback(review_info, test_report, config)
                else:
                    print(f"\n⚠️  Test succeeded but failed to create test report in {reviews_dir}")
            else:
                print(f"\n⚠️  Test failed or skipped for {review_info.repo_name} #{review_info.change_number}")
                # Post a failure notice — forge users most need to know when tests fail
                _post_devstack_failure_feedback(review_info, config)

    if tested_count == 0:
        if review_info is None:
            print("   No unprocessed reviews found")
            print("\n\u2713 Nothing to test this cycle")
        # else: a review ran but failed — failure logging already handled above

    print("\n" + "="*80)
    print("✅ DevStack test cycle complete!")
    print("="*80)


async def _handle_feedback_run(
    tested_reviews: dict,
    reviews_dir: Path,
    tracking_file: Path,
    config: dict,
) -> bool:
    """Check all tracked changes for user feedback files and run any found.

    Scans ``tested_reviews`` for feedback files.  On the first match, validates
    and runs the requested tests (or the full suite) and records the result.

    Returns True if a feedback-triggered run was performed, False otherwise.
    """
    for review_id, entry in tested_reviews.items():
        # review_id format: {repo_name}~{change_number}~ps{patchset}
        parts = review_id.split('~')
        if len(parts) != 3 or not parts[2].startswith('ps'):
            continue
        change_number = parts[1]
        try:
            patchset = int(parts[2][2:])
        except ValueError:
            continue

        # Check feedback file exists BEFORE consuming it — so a missing review
        # file does not silently discard the feedback.
        if not has_devstack_feedback(change_number, patchset, reviews_dir):
            continue

        # Resolve the review file.  Prefer the tracked path when it still
        # exists; fall back to glob when the path is stale or missing.
        review_file_path = entry.get("review_file")
        if review_file_path and Path(review_file_path).exists():
            review_file_obj = Path(review_file_path)
        else:
            ps_glob = f"ps{patchset}_"
            pattern = f"review_*_{change_number}_{ps_glob}*.md"
            review_file_obj = find_latest_report(reviews_dir, pattern)

        if not review_file_obj or not review_file_obj.exists():
            print(
                f"⚠️  Feedback for #{change_number} ps{patchset}: "
                "review file not found — skipping (feedback preserved)"
            )
            continue

        review_info = parse_review_file(review_file_obj)
        if not review_info:
            print(
                f"⚠️  Feedback for #{change_number} ps{patchset}: "
                "could not parse review — skipping (feedback preserved)"
            )
            continue

        # All prerequisites confirmed — now consume and parse the feedback file.
        result = process_feedback(change_number, patchset, reviews_dir)
        if result is None:
            continue

        rerun_all, valid_tests = result

        if not rerun_all and not valid_tests:
            print(
                f"⚠️  Feedback for #{change_number} ps{patchset}: "
                "no valid test names — all were rejected (check feedback file format)"
            )
            continue

        specific = None if rerun_all else valid_tests
        trigger = "feedback: full re-run" if rerun_all else f"feedback: {len(valid_tests)} specific test(s)"

        success, test_results_file = await test_change_in_devstack(
            review_info, config, specific_tests=specific, trigger=trigger
        )

        if success and test_results_file:
            test_report = create_test_report(
                review_file_obj, Path(test_results_file), reviews_dir
            )
            if test_report:
                _record_test_result(
                    review_info, review_file_obj, tracking_file, "success", test_report
                )
                notify_report(
                    report_path=test_report,
                    subject=(
                        f"DevStack Test (feedback): {review_info.repo_name} "
                        f"#{review_info.change_number} PS{review_info.patchset}"
                    ),
                    summary=f"Feedback-triggered run: {trigger}",
                    agent_config=config,
                    notifications_config=load_notifications_config(),
                )
                _post_devstack_feedback(review_info, test_report, config)
        else:
            _record_test_result(review_info, review_file_obj, tracking_file, "failure")
            _post_devstack_failure_feedback(review_info, config)

        return True  # one feedback run per cycle

    return False


def _compute_latest_patchsets(review_files: list) -> dict:
    """Return a dict mapping (repo_name, change_number) → highest patchset seen."""
    latest: dict = {}
    for rf in review_files:
        info = parse_review_file(rf)
        if info:
            key = (info.repo_name, info.change_number)
            if info.patchset > latest.get(key, 0):
                latest[key] = info.patchset
    return latest


def _find_next_review(
    review_files: list,
    tested_reviews: dict,
    latest_patchset: dict,
    allowed_repos: list,
):
    """
    Return (review_info, review_file, review_id) for the next review that
    should be tested, or (None, None, None) if none qualify.

    A review qualifies when:
    - It is the latest patchset for its change.
    - ``should_test_review`` returns True.
    - It is not already in the tracking file, OR it has ``retry_on_recovery``
      set (meaning a previous run failed due to an unhealthy environment).
    """
    skipped_count = 0
    for review_file in review_files:
        review_info = parse_review_file(review_file)
        if not review_info:
            continue

        # Skip stale patchsets
        change_key = (review_info.repo_name, review_info.change_number)
        if review_info.patchset < latest_patchset.get(change_key, review_info.patchset):
            print(
                f"⏭️  Skipping {review_info.repo_name} #{review_info.change_number} "
                f"PS{review_info.patchset} - newer PS{latest_patchset[change_key]} exists"
            )
            continue

        if not should_test_review(review_info, allowed_repos):
            if review_info.already_tested:
                skipped_count += 1
                if skipped_count <= 3:
                    print(
                        f"⏭️  Skipping {review_info.repo_name} "
                        f"#{review_info.change_number} - Already tested"
                    )
            continue

        review_id = (
            f"{review_info.repo_name}~{review_info.change_number}~ps{review_info.patchset}"
        )
        should_test, _seq = should_process_item(
            review_id, review_info.review_timestamp, tested_reviews
        )
        if not should_test:
            print(
                f"⏭️  Skipping {review_info.repo_name} "
                f"#{review_info.change_number} - Already in tracking"
            )
            continue

        return review_info, review_file, review_id

    return None, None, None


def _record_test_result(
    review_info,
    review_file: Path,
    tracking_file: Path,
    test_result: str,
    test_report_file: "Path | None" = None,
    retry_on_recovery: bool = False,
) -> None:
    """Write a tracking entry for a tested change (success, failure, or env error)."""
    review_id = (
        f"{review_info.repo_name}~{review_info.change_number}~ps{review_info.patchset}"
    )
    # Determine the next sequence number from the current tracking state.
    existing = load_tracking_file(tracking_file)
    existing_entry = existing.get(review_id, {})
    if retry_on_recovery:
        sequence = existing_entry.get("sequence", 1)
    else:
        sequence = existing_entry.get("sequence", 0) + 1

    extra_data: dict = {
        "review_file": str(review_file),
        "test_result": test_result,
    }
    if test_report_file:
        extra_data["test_report_file"] = str(test_report_file)

    record_processed_item(
        tracking_file,
        review_id,
        review_info.review_timestamp,
        sequence,
        id_prefix="",
        extra_data=extra_data,
        retry_on_recovery=retry_on_recovery,
    )


async def run_single_change(change_number: str, patchset: "int | None", config: dict) -> None:
    """Find the review file for a specific change and run DevStack tests on it."""
    reviews_dir = Path(config["reviews_directory"])
    ps_glob = f"ps{patchset}_" if patchset else "ps*_"
    pattern = f"review_*_{change_number}_{ps_glob}*.md"
    review_file = find_latest_report(reviews_dir, pattern)
    if not review_file:
        print(f"❌ No review file found matching {pattern} in {reviews_dir}")
        sys.exit(1)

    print(f"📄 Using review file: {review_file.name}\n")

    review_info = parse_review_file(review_file)
    if not review_info:
        print(f"❌ Could not parse review file: {review_file}")
        sys.exit(1)

    tracking_file = Path(config["tracking"]["tested_reviews_file"])

    success, test_results_file = await test_change_in_devstack(
        review_info, config, trigger="manual (CLI)"
    )

    if success and test_results_file:
        test_report = create_test_report(review_file, Path(test_results_file), reviews_dir)
        if test_report:
            _record_test_result(review_info, review_file, tracking_file, "success", test_report)
            print(f"\n✅ Test complete. Report: {test_report.name}")
            notify_report(
                report_path=test_report,
                subject=(
                    f"DevStack Test: {review_info.repo_name} "
                    f"#{review_info.change_number} PS{review_info.patchset}"
                ),
                summary="DevStack integration test passed",
                agent_config=config,
                notifications_config=load_notifications_config(),
            )
            _post_devstack_feedback(review_info, test_report, config)
        else:
            print(f"\n⚠️  Tests ran but report file could not be created in {reviews_dir}")
    else:
        print(f"\n⚠️  Tests failed or were skipped for change #{change_number}")
        _record_test_result(review_info, review_file, tracking_file, "failure")
        _post_devstack_failure_feedback(review_info, config)


def cli_main():
    """Main entry point for command-line usage."""
    parser = argparse.ArgumentParser(description='DevStack Test Agent')
    parser.add_argument(
        '--change', metavar='N',
        help='Run tests immediately on this Gerrit change number, bypassing the review queue.',
    )
    parser.add_argument(
        '--patchset', '-p', metavar='N', type=int,
        help='Patchset to test (default: latest available review file for the change).',
    )
    args = parser.parse_args()

    if args.change:
        config = load_config_module()
        asyncio.run(run_single_change(str(args.change), args.patchset, config))
    else:
        asyncio.run(main())


if __name__ == "__main__":
    cli_main()
