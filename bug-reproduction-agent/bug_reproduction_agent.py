#!/usr/bin/env python3
"""
Octavia Bug Reproduction Agent

Watches for bug triage reports, attempts to reproduce bugs in DevStack,
and generates reproduction scripts with comprehensive analysis.
"""
import asyncio
import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from agents_lib import (
    load_agent_config,
    apply_cutoff_date,
    expand_config_paths,
    expand_context_config,
    load_context_section,
    generate_learning,
    save_learning,
    check_devstack_health,
    check_repo_on_main_branch,
    checkout_main_branch,
    notify_report,
    load_notifications_config,
)
from triage_parser import parse_triage_file, get_triage_timestamp
from script_generator import (
    audit_reproduction,
    generate_initial_script,
    generate_fallback_script,
    refine_script,
)
from script_executor import execute_script
from report_generator import generate_report
from reproduction_tracker import (
    load_reproduction_history,
    should_reproduce_bug,
    record_reproduction,
    create_reproduction_filename,
)

# Load configuration
CONFIG = None


def load_config():
    """Load configuration from config.json or config.sample.json."""
    global CONFIG
    config_dir = Path(__file__).parent

    # Define environment variable overrides
    env_overrides = {
        "TRIAGES_DIR": "triage_reports_dir",
        "REPRODUCTIONS_OUTPUT_DIR": "reproductions_output_dir",
        "DEVSTACK_PATH": ("devstack", "path"),
        "MAX_ATTEMPTS": ("reproduction", "max_attempts"),
        "SCRIPT_TIMEOUT": ("reproduction", "script_timeout"),
        "CUTOFF_DATE": "cutoff_date",
        "CLAUDE_MODEL": "model",
    }

    # Load config using shared library
    defaults = {"model": "claude-sonnet-4-6"}
    CONFIG = load_agent_config(config_dir, env_overrides, defaults)

    # Apply cutoff date logic (default to 30 days ago)
    CONFIG = apply_cutoff_date(CONFIG, "cutoff_date", default_days=30)

    # Expand paths
    path_keys = [
        "triage_reports_dir",
        "reproductions_output_dir",
        "reproduction_tracking_file",
        ("devstack", "path"),
        ("devstack", "openrc_file"),
        ("reproduction", "working_directory"),
    ]
    CONFIG = expand_config_paths(CONFIG, path_keys)
    CONFIG = expand_context_config(CONFIG)

    return CONFIG


async def _maybe_save_reproduction_learning(final_status, triage, attempts, reasonings):
    """Save a learning to the agent context file on notable reproduction outcomes."""
    is_notable = (
        final_status == "NOT_REPRODUCED"
        or final_status == "ENVIRONMENT_ERROR"
        or (final_status == "REPRODUCED" and len(attempts) > 1)
    )
    if not is_notable:
        return
    last_reasoning = next((r for r in reversed(reasonings) if r), "")
    result_summary = (
        f"Status: {final_status}. Bug: #{triage.bug_number} — {triage.bug_title}. "
        f"Attempts: {len(attempts)}. {last_reasoning[:300]}"
    )
    learning = await generate_learning(result_summary, "Bug Reproduction Agent", CONFIG)
    if learning:
        save_learning(CONFIG["context"]["agent_context_file"], learning, "Bug Reproduction Agent")


async def process_triage(triage_file: Path) -> bool:
    """
    Process a single triage report - attempt to reproduce the bug.

    Args:
        triage_file: Path to triage markdown file

    Returns:
        True if successful, False otherwise
    """
    print(f"\n{'='*80}")
    print(f"Processing triage: {triage_file.name}")
    print(f"{'='*80}\n")

    try:
        # Parse triage report
        print("📄 Parsing triage report...")
        triage = parse_triage_file(triage_file)
        print(f"   Bug: #{triage.bug_number} - {triage.bug_title}")
        print(f"   Severity: {triage.severity}")
        print(f"   Reproduction steps: {len(triage.reproduction_steps)} bash blocks")

        # Check DevStack health
        print("\n🏥 Checking DevStack health...")
        health = check_devstack_health(CONFIG)
        if not health.all_healthy:
            print("   ❌ DevStack is not healthy!")
            for error in health.errors:
                print(f"      - {error}")

            # Generate report with environment error
            output_dir = Path(CONFIG["reproductions_output_dir"])
            output_dir.mkdir(parents=True, exist_ok=True)
            report_file = create_reproduction_filename(
                output_dir,
                triage.bug_number,
                triage.bug_title,
                1
            )

            report = generate_report(
                triage,
                health,
                [],
                "ENVIRONMENT_ERROR",
                None,
                None
            )

            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(report)

            print(f"\n📝 Report saved: {report_file}")

            # Record in tracking — retry_on_recovery so the bug is picked up
            # again once DevStack is healthy.
            triage_timestamp = get_triage_timestamp(triage_file)
            tracking_file = Path(CONFIG["reproduction_tracking_file"])
            record_reproduction(
                tracking_file,
                triage.bug_number,
                triage_timestamp,
                1,
                "ENVIRONMENT_ERROR",
                0,
                None,
                retry_on_recovery=True,
            )

            return False

        print("   ✅ DevStack is healthy")

        # Check Octavia repos are on main branch
        devstack_path = Path(CONFIG["devstack"]["path"])
        octavia_repos = ["octavia", "octavia-lib", "python-octaviaclient"]

        print("\n📋 Checking repository branches...")
        for repo_name in octavia_repos:
            repo_path = devstack_path / repo_name
            if repo_path.exists():
                branch_check = check_repo_on_main_branch(repo_path)
                if not branch_check.on_main:
                    print(f"   ⚠️  {repo_name}: {branch_check.error}")
                    print("      Attempting to checkout main/master...")
                    success, message = checkout_main_branch(repo_path)
                    if success:
                        print(f"      ✅ {message}")
                    else:
                        print(f"      ❌ {message}")
                else:
                    print(f"   ✅ {repo_name}: On {branch_check.current_branch} branch")

        # Load context from rules/global/agent context files and inject into scripts
        context_section = load_context_section(CONFIG, "bug_reproduction")
        if context_section:
            print("   📚 Context loaded from context files")

        # Attempt reproduction (up to max_attempts)
        max_attempts = CONFIG.get("reproduction", {}).get("max_attempts", 3)
        script_timeout = CONFIG.get("reproduction", {}).get("script_timeout", 600)
        attempts = []  # List of (script, ExecutionResult, usage_dict)
        reasonings = []  # Agent's explanation per attempt (parallel to attempts)
        final_status = "NOT_REPRODUCED"
        successful_script = None

        # Track total usage across all attempts
        total_usage = {
            'usage': {
                'input_tokens': 0,
                'output_tokens': 0,
                'cache_creation_input_tokens': 0,
                'cache_read_input_tokens': 0,
            },
            'cost_usd': 0.0,
            'duration_ms': 0,
            'model': None,
        }

        for attempt in range(1, max_attempts + 1):
            print(f"\n🔧 Attempt {attempt}/{max_attempts}")

            usage_dict = {}
            reasoning = None
            if attempt == 1:
                # Generate initial script from triage
                print("   Generating initial script from triage...")
                try:
                    script, reasoning, usage_dict = await generate_initial_script(
                        triage, CONFIG, context_section=context_section
                    )
                except Exception as e:
                    print(f"   ⚠️ AI generation failed: {e}")
                    print("   Using fallback script...")
                    script = generate_fallback_script(triage, CONFIG)
            else:
                # Refine previous script
                previous_script, previous_result, _ = attempts[-1]
                print(f"   Refining script (previous attempt: {previous_result.error_type})...")
                try:
                    script, reasoning, usage_dict = await refine_script(
                        previous_script,
                        previous_result,
                        attempt,
                        triage,
                        CONFIG,
                        context_section=context_section,
                    )
                except Exception as e:
                    print(f"   ⚠️ AI refinement failed: {e}")
                    print("   Using previous script with minor adjustments...")
                    script = previous_script  # Fallback to previous

            # Accumulate usage stats
            if usage_dict:
                if usage_dict.get('usage'):
                    usage_keys = ['input_tokens', 'output_tokens',
                                  'cache_creation_input_tokens', 'cache_read_input_tokens']
                    for key in usage_keys:
                        total_usage['usage'][key] += usage_dict['usage'].get(key, 0)
                if usage_dict.get('cost_usd') is not None:
                    total_usage['cost_usd'] += usage_dict['cost_usd']
                if usage_dict.get('duration_ms'):
                    total_usage['duration_ms'] += usage_dict['duration_ms']
                if usage_dict.get('model') and not total_usage['model']:
                    total_usage['model'] = usage_dict['model']

            # Execute script
            print(f"   Executing script (timeout: {script_timeout}s)...")
            result = execute_script(script, timeout=script_timeout)

            attempts.append((script, result, usage_dict))
            reasonings.append(reasoning)

            print(f"   Exit code: {result.exit_code}")
            print(f"   Error type: {result.error_type}")
            print(f"   Execution time: {result.execution_time:.1f}s")

            # Check if the script exited cleanly or has an explicit reproduction marker.
            # Always run an audit to confirm the output actually shows the bug —
            # an empty or trivial script can also exit 0 without triggering anything.
            if result.success or result.error_type == "BUG_REPRODUCED":
                confirmed = await audit_reproduction(script, result, triage, CONFIG, reasoning)
                if confirmed:
                    print("   ✅ Bug reproduced and confirmed by audit!")
                    final_status = "REPRODUCED"
                    successful_script = script
                    break
                print("   ⚠️ Script exited 0 but audit found no bug evidence — treating as failure")
                result.error_type = "SCRIPT_FAILURE"

            # Check if environment error
            if result.error_type == "ENVIRONMENT_ERROR":
                print("   ⚠️ Environment error detected, aborting...")
                final_status = "ENVIRONMENT_ERROR"
                break

            # Continue to next attempt
            print(f"   ❌ Attempt {attempt} failed, will {'retry' if attempt < max_attempts else 'stop'}")

        # Generate reproduction report
        print("\n📝 Generating reproduction report...")
        output_dir = Path(CONFIG["reproductions_output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)

        report_file = create_reproduction_filename(
            output_dir,
            triage.bug_number,
            triage.bug_title,
            1
        )

        # Save successful script if reproduced
        script_path = None
        if final_status == "REPRODUCED" and successful_script:
            script_path = output_dir / "scripts" / f"bug_{triage.bug_number}_reproduction.sh"
            script_path.parent.mkdir(parents=True, exist_ok=True)
            with open(script_path, 'w', encoding='utf-8') as f:
                f.write(successful_script)
            script_path.chmod(0o755)
            print(f"   💾 Saved reproduction script: {script_path}")

        report = generate_report(
            triage,
            health,
            attempts,
            final_status,
            script_path,
            total_usage,
            reasonings=reasonings,
        )

        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)

        print(f"   💾 Saved report: {report_file}")

        # Verify report file was created before marking as complete
        if not report_file.exists():
            print("\n❌ ERROR: Report file not found after write!")
            print(f"   Expected: {report_file}")
            print("   Will retry on next pass")
            return False

        # Record in tracking (only after confirming file exists)
        triage_timestamp = get_triage_timestamp(triage_file)
        tracking_file = Path(CONFIG["reproduction_tracking_file"])
        record_reproduction(
            tracking_file,
            triage.bug_number,
            triage_timestamp,
            1,
            final_status,
            len(attempts),
            str(script_path) if script_path else None
        )
        print("   ✓ Recorded in tracking file")

        notify_report(
            report_path=report_file,
            subject=f"Bug Reproduction: #{triage.bug_number} – {triage.bug_title}",
            summary=f"Result: {final_status} | Attempts: {len(attempts)}",
            agent_config=CONFIG,
            notifications_config=load_notifications_config(),
        )

        print(f"\n{'='*80}")
        if final_status == "REPRODUCED":
            print(f"✅ Bug #{triage.bug_number} successfully reproduced!")
        elif final_status == "NOT_REPRODUCED":
            print(f"❌ Bug #{triage.bug_number} could not be reproduced")
        else:
            print(f"⚠️ Bug #{triage.bug_number} reproduction: {final_status}")
        print(f"{'='*80}\n")

        # Save a learning on notable outcomes
        await _maybe_save_reproduction_learning(final_status, triage, attempts, reasonings)

        return final_status == "REPRODUCED"

    except Exception as e:
        print(f"\n❌ Error processing triage: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Main entry point - find and process new triages."""
    print("\n" + "="*80)
    print("Octavia Bug Reproduction Agent")
    print("="*80 + "\n")

    # Load configuration
    global CONFIG
    CONFIG = load_config()

    print("Configuration:")
    print(f"  Triage reports: {CONFIG['triage_reports_dir']}")
    print(f"  Output directory: {CONFIG['reproductions_output_dir']}")
    print(f"  Tracking file: {CONFIG['reproduction_tracking_file']}")
    print(f"  Model: {CONFIG.get('model', 'claude-sonnet-4-6')}")
    print(f"  Max attempts: {CONFIG.get('reproduction', {}).get('max_attempts', 3)}")
    print(f"  Script timeout: {CONFIG.get('reproduction', {}).get('script_timeout', 600)}s")
    print()

    # Load tracking history
    tracking_file = Path(CONFIG["reproduction_tracking_file"])
    history = load_reproduction_history(tracking_file)

    # Find unprocessed triage reports
    triage_dir = Path(CONFIG["triage_reports_dir"])
    if not triage_dir.exists():
        print(f"❌ Triage directory does not exist: {triage_dir}")
        return

    triage_files = sorted(triage_dir.glob("bug_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)

    if not triage_files:
        print(f"No triage files found in {triage_dir}")
        return

    print(f"Found {len(triage_files)} triage files")

    # Find first unprocessed triage
    for triage_file in triage_files:
        # Extract bug number from filename
        filename = triage_file.stem
        parts = filename.split('_')
        if len(parts) < 2:
            continue

        bug_number = parts[1]  # bug_NUMBER_...
        triage_timestamp = get_triage_timestamp(triage_file)

        # Check if should process
        should_process, _sequence = should_reproduce_bug(bug_number, triage_timestamp, history)

        if should_process:
            print(f"\nProcessing new triage: {triage_file.name}")
            await process_triage(triage_file)
            break  # Process only one triage per run
        print(f"Skipping already processed: {triage_file.name}")

    print("\n" + "="*80)
    print("✅ Reproduction cycle complete!")
    print("="*80 + "\n")


def cli_main():
    """CLI entry point for package installation."""
    asyncio.run(main())


if __name__ == "__main__":
    cli_main()
