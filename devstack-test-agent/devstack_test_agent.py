#!/usr/bin/env python3
"""
DevStack Test Agent

Watches for new code review files and tests changes in DevStack environment.
Operates asynchronously from code review agent to improve throughput.
"""
import argparse
import asyncio
import sys
from pathlib import Path
from datetime import datetime
# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from agents_lib import (
    load_tracking_file,
    save_tracking_file,
    find_latest_report,
    check_devstack_health,
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
from review_parser import parse_review_file, should_test_review

# Load configuration
CONFIG = None


def load_config_module():
    """Load configuration from config.json or config.sample.json."""
    global CONFIG
    CONFIG = load_config()
    return CONFIG


async def test_change_in_devstack(review_info, config: dict) -> tuple[bool, str]:
    """
    Test a code change in DevStack using AI agent.

    Args:
        review_info: Parsed review information
        config: Configuration dictionary

    Returns:
        Tuple of (success, test_results_file_path)
    """
    print(f"\n{'='*80}")
    print("🧪 Testing Change in DevStack")
    print(f"📋 Repository: {review_info.repo_name}")
    print(f"📋 Change: {review_info.change_number} (Patchset {review_info.patchset})")
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

            # Construct patchset ref
            last_two = str(review_info.change_number)[-2:]
            patchset_ref = f"refs/changes/{last_two}/{review_info.change_number}/{review_info.patchset}"

            # Results file (temp location, will be incorporated into review)
            results_file = Path(f"/tmp/devstack_test_{review_info.change_number}_ps{review_info.patchset}.md")

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
            )

            # Prepend cross-run context
            _ctx = load_context_section(config, "devstack_test")
            if _ctx:
                prompt = _ctx + "\n\n---\n\n" + prompt

            print("🤖 Starting DevStack integration testing...\n")

            # Run test with AI agent
            test_result = None
            try:
                _client = create_model_client(config)
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
                if results_file.exists():
                    print(f"\n✓ Test results saved to: {results_file}")
                    return (True, str(results_file))
                if test_result:
                    # Save result manually if AI didn't write file
                    print("\n⚠️  Results file not found - saving manually...")
                    results_file.write_text(test_result, encoding="utf-8")
                    print(f"✓ Saved results to: {results_file}")
                    return (True, str(results_file))
                print("\n❌ No test results generated")
                return (False, "")

            except Exception as e:
                print(f"\n❌ Error during testing: {e}")
                import traceback
                traceback.print_exc()
                return (False, "")

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
        test_results = Path(test_results_file).read_text(encoding="utf-8")

        # Extract from "## Test Environment" onwards — skip the AI preamble
        # since the review already contains the change details.
        test_sections = []
        in_section = False
        for line in test_results.split('\n'):
            if line.startswith('## Test Environment'):
                in_section = True
            if in_section:
                test_sections.append(line)
        test_content = '\n'.join(test_sections)

        # Derive test report filename from review filename, replacing prefix and timestamp.
        # review_openstack_octavia_932847_ps1_20260402_090051.md
        # → testing_report_openstack_octavia_932847_ps1_20260507_143022.md
        stem_parts = review_file.stem.split('_')
        middle_parts = stem_parts[1:-2]  # strip 'review' prefix and old timestamp
        new_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        new_stem = 'testing_report_' + '_'.join(middle_parts) + '_' + new_timestamp
        test_report_file = output_dir / f"{new_stem}.md"

        combined = (
            review_content.rstrip() +
            "\n\n---\n\n" +
            "# DevStack Integration Testing\n\n" +
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

    # Check DevStack health
    print("🏥 Checking DevStack health...")
    health = check_devstack_health(config)
    if not health.all_healthy:
        print("   ❌ DevStack is not healthy!")
        for error in health.errors:
            print(f"      - {error}")
        print("\n⚠️  Cannot run tests - DevStack environment needs attention")
        return

    print("   ✅ DevStack is healthy\n")

    # Load tracking file
    tracking_file = Path(config["tracking"]["tested_reviews_file"])
    tested_reviews = load_tracking_file(tracking_file)

    # Find review files
    reviews_dir = Path(config["reviews_directory"])
    if not reviews_dir.exists():
        print(f"❌ Reviews directory does not exist: {reviews_dir}")
        return

    review_files = sorted(reviews_dir.glob("review_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)

    if not review_files:
        print(f"No review files found in {reviews_dir}")
        return

    print(f"📋 Found {len(review_files)} review files\n")

    # Get filter settings
    allowed_repos = config["filters"]["only_test_repositories"]

    # Pre-compute the highest patchset available for each change so we can
    # skip stale patchsets without waiting for the tracking file.
    latest_patchset: dict = {}
    for _rf in review_files:
        _info = parse_review_file(_rf)
        if _info:
            key = (_info.repo_name, _info.change_number)
            if _info.patchset > latest_patchset.get(key, 0):
                latest_patchset[key] = _info.patchset

    # Process reviews
    tested_count = 0
    skipped_count = 0

    for review_file in review_files:
        # Parse review
        review_info = parse_review_file(review_file)
        if not review_info:
            continue

        # Skip if a newer patchset exists for this change
        change_key = (review_info.repo_name, review_info.change_number)
        if review_info.patchset < latest_patchset.get(change_key, review_info.patchset):
            print(
                f"⏭️  Skipping {review_info.repo_name} #{review_info.change_number} "
                f"PS{review_info.patchset} - newer PS{latest_patchset[change_key]} exists"
            )
            continue

        # Check if should test
        if not should_test_review(review_info, allowed_repos):
            if review_info.already_tested:
                skipped_count += 1
                if skipped_count <= 3:
                    print(f"⏭️  Skipping {review_info.repo_name} #{review_info.change_number} - Already tested")
            continue

        # Check tracking file
        review_id = f"{review_info.repo_name}~{review_info.change_number}~ps{review_info.patchset}"
        if review_id in tested_reviews:
            print(f"⏭️  Skipping {review_info.repo_name} #{review_info.change_number} - Already in tracking")
            continue

        print(f"\n📌 Testing {review_info.repo_name} #{review_info.change_number} PS{review_info.patchset}")

        # Test in DevStack
        success, test_results_file = await test_change_in_devstack(review_info, config)

        if success and test_results_file:
            # Create a new testing_report_* file (review file is not modified)
            test_report = create_test_report(
                review_file, Path(test_results_file), reviews_dir
            )
            if test_report:
                _record_test_result(review_info, review_file, tracking_file, "success", test_report)
                tested_reviews = load_tracking_file(tracking_file)  # keep in sync for loop
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

        # Only test one review per run (to avoid holding DevStack lock too long)
        if tested_count >= 1:
            print(f"\n📊 Tested {tested_count} review(s) this pass")
            break

    if tested_count == 0:
        print("\n✓ No new reviews to test")

    print("\n" + "="*80)
    print("✅ DevStack test cycle complete!")
    print("="*80)


def _record_test_result(
    review_info,
    review_file: Path,
    tracking_file: Path,
    test_result: str,
    test_report_file: "Path | None" = None,
) -> None:
    """Write a tracking entry for a tested change (success or failure)."""
    tested_reviews = load_tracking_file(tracking_file)
    review_id = (
        f"{review_info.repo_name}~{review_info.change_number}~ps{review_info.patchset}"
    )
    entry = {
        "tested_at": datetime.now().isoformat(),
        "review_file": str(review_file),
        "test_result": test_result,
    }
    if test_report_file:
        entry["test_report_file"] = str(test_report_file)
    tested_reviews[review_id] = entry
    save_tracking_file(tracking_file, tested_reviews)


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

    print(f"📌 Testing {review_info.repo_name} #{review_info.change_number} PS{review_info.patchset}")

    success, test_results_file = await test_change_in_devstack(review_info, config)

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
