#!/usr/bin/env python3
"""
DevStack Test Agent

Watches for new code review files and tests changes in DevStack environment.
Operates asynchronously from code review agent to improve throughput.
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime
# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from agents_lib import (
    load_tracking_file,
    save_tracking_file,
    check_devstack_health,
    devstack_lock,
    get_unique_resource_prefix,
    notify_report,
    load_notifications_config,
    create_model_client,
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


def update_review_with_test_results(review_file: Path, test_results_file: Path) -> bool:
    """
    Update the original review file with DevStack test results.

    Args:
        review_file: Path to original review markdown file
        test_results_file: Path to test results markdown file

    Returns:
        True if successful, False otherwise
    """
    print("\n📝 Updating review file with test results...")

    try:
        # Read both files
        review_content = review_file.read_text(encoding="utf-8")
        test_results = Path(test_results_file).read_text(encoding="utf-8")

        # Extract just the relevant sections from test results
        # (skip the header as review already has change info)
        test_sections = []
        in_section = False
        for line in test_results.split('\n'):
            if line.startswith('## Test Environment'):
                in_section = True
            if in_section:
                test_sections.append(line)

        test_content = '\n'.join(test_sections)

        # Find insertion point in review
        # Insert before "## Code Analysis" or at end
        insertion_marker = "## Code Analysis"
        if insertion_marker in review_content:
            parts = review_content.split(insertion_marker, 1)
            updated_content = (
                parts[0] +
                "\n---\n\n" +
                "# DevStack Integration Testing\n\n" +
                test_content +
                "\n\n---\n\n" +
                insertion_marker +
                parts[1]
            )
        else:
            # Append at end
            updated_content = (
                review_content +
                "\n\n---\n\n" +
                "# DevStack Integration Testing\n\n" +
                test_content
            )

        # Write updated review
        review_file.write_text(updated_content)
        print(f"   ✅ Updated: {review_file.name}")

        # Cleanup temp file
        Path(test_results_file).unlink(missing_ok=True)

        return True

    except Exception as e:
        print(f"   ❌ Error updating review: {e}")
        return False


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

    # Process reviews
    tested_count = 0
    skipped_count = 0

    for review_file in review_files:
        # Parse review
        review_info = parse_review_file(review_file)
        if not review_info:
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
            # Update original review file
            if update_review_with_test_results(review_file, Path(test_results_file)):
                # Record in tracking
                tested_reviews[review_id] = {
                    "tested_at": datetime.now().isoformat(),
                    "review_file": str(review_file),
                    "test_result": "success"
                }
                save_tracking_file(tracking_file, tested_reviews)
                tested_count += 1
                print(f"\n✅ Test complete for {review_info.repo_name} #{review_info.change_number}")
                notify_report(
                    report_path=review_file,
                    subject=(
                        f"DevStack Test: {review_info.repo_name} "
                        f"#{review_info.change_number} PS{review_info.patchset}"
                    ),
                    summary="DevStack integration test passed",
                    agent_config=config,
                    notifications_config=load_notifications_config(),
                )
            else:
                print("\\n⚠️  Test succeeded but failed to update review file")
        else:
            print(f"\n⚠️  Test failed or skipped for {review_info.repo_name} #{review_info.change_number}")

        # Only test one review per run (to avoid holding DevStack lock too long)
        if tested_count >= 1:
            print(f"\n📊 Tested {tested_count} review(s) this pass")
            break

    if tested_count == 0:
        print("\n✓ No new reviews to test")

    print("\n" + "="*80)
    print("✅ DevStack test cycle complete!")
    print("="*80)


def cli_main():
    """Main entry point for command-line usage."""
    asyncio.run(main())


if __name__ == "__main__":
    cli_main()
