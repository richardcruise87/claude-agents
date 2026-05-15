#!/usr/bin/env python3
"""
Fix Verification Agent

Applies a proposed fix (from the Fix Proposal Agent or supplied manually by a
developer) and re-runs the confirmed reproduction script to determine whether
the fix resolves the bug.

Retry behaviour:
  - ENVIRONMENTAL failures are retried up to max_attempts.
  - FIX_FAILURE stops immediately — retrying won't change the outcome.
  - RESOLVED stops immediately — success.

Modes:
  Automated: watches ~/octavia_fix_proposals/ for new proposals.
  Manual:    --bug N  --patch FILE | --branch NAME | --gerrit ID | --already-applied
"""
import argparse
import asyncio
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agents_lib import (
    load_agent_config,
    apply_cutoff_date,
    expand_config_paths,
    expand_context_config,
    load_context_section,
    generate_learning,
    save_learning,
    notify_report,
    load_notifications_config,
    build_feedback_comment,
    post_launchpad_comment_from_config,
    post_report_to_launchpad,
    find_latest_report,
)
from failure_analyser import (
    analyse_failure,
    format_analysis_section,
    format_verification_result,
)
from patch_applicator import (
    PatchSource,
    PatchSourceType,
    apply_patch,
    revert_patch,
)
from verification_tracker import (
    create_verification_filename,
    load_verification_history,
    record_verification,
    should_verify_proposal,
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_CONFIG_DIR = Path(__file__).parent

_DEFAULTS = {
    "model": "claude-sonnet-4-6",
    "model_provider": "anthropic",
    "fix_proposals_dir": "~/octavia_fix_proposals",
    "reproduction_reports_dir": "~/octavia_bug_reproductions",
    "verifications_output_dir": "~/octavia_fix_verifications",
    "verification_tracking_file": "~/.octavia_fix_verifications.json",
    "devstack_path": "/opt/stack",
    "launchpad_project": "octavia",
    "max_proposals_per_run": 2,
    "cutoff_date": None,
    "verification": {
        "max_attempts": 3,
        "script_timeout": 600,
        "retry_delay_seconds": 60,
    },
    "feedback": {"post_to_launchpad": False},
    "notifications": {"enabled": False},
}

_ENV_OVERRIDES = {
    "VERIFICATIONS_OUTPUT_DIR": "verifications_output_dir",
    "FIX_PROPOSALS_DIR": "fix_proposals_dir",
    "DEVSTACK_PATH": "devstack_path",
    "CUTOFF_DATE": "cutoff_date",
    "MAX_PROPOSALS": "max_proposals_per_run",
    "CLAUDE_MODEL": "model",
}

_PATH_KEYS = [
    "fix_proposals_dir",
    "reproduction_reports_dir",
    "verifications_output_dir",
    "verification_tracking_file",
    "devstack_path",
]


def load_config() -> dict:
    config = load_agent_config(_CONFIG_DIR, _ENV_OVERRIDES, _DEFAULTS)
    config = apply_cutoff_date(config, "cutoff_date", default_days=30)
    config = expand_config_paths(config, _PATH_KEYS)
    config = expand_context_config(config)
    return config


# ---------------------------------------------------------------------------
# Helpers: extract info from fix proposal documents
# ---------------------------------------------------------------------------

def extract_patch_from_proposal(proposal_file: Path) -> str:
    """Return the git diff block embedded in a fix proposal markdown file."""
    content = proposal_file.read_text(encoding="utf-8")
    match = re.search(r"```diff\n(.*?)```", content, re.DOTALL)
    return match.group(1) if match else ""


def extract_bug_info_from_proposal(proposal_file: Path) -> tuple[str, str]:
    """Return (bug_number, bug_title) from a fix proposal filename."""
    # Format: fix_proposal_{bug_number}_{title_slug}_{timestamp}_{seq}.md
    parts = proposal_file.stem.split("_")
    # parts[0]='fix', parts[1]='proposal', parts[2]=bug_number,
    # parts[3:-3]=title, parts[-3]=date, parts[-2]=time, parts[-1]=seq
    if len(parts) < 6 or parts[0] != "fix" or parts[1] != "proposal":
        return "", ""
    bug_number = parts[2]
    title_slug = "_".join(parts[3:-3])
    return bug_number, title_slug.replace("_", " ")


def extract_proposal_timestamp(proposal_file: Path) -> str:
    """Extract ISO-style timestamp from proposal filename."""
    parts = proposal_file.stem.split("_")
    if len(parts) >= 3:
        date_part = parts[-3]
        time_part = parts[-2]
        try:
            int(parts[-1])  # confirm last is sequence number
            return f"{date_part}T{time_part}"
        except (ValueError, IndexError):
            pass
    return datetime.now().isoformat()


def find_reproduction_script(bug_number: str, repro_dir: Path) -> Path | None:
    """Return the most recent reproduction script for a bug."""
    script_dir = repro_dir / "scripts"
    script = script_dir / f"bug_{bug_number}_reproduction.sh"
    return script if script.exists() else None


# ---------------------------------------------------------------------------
# Core: run the verification for one fix
# ---------------------------------------------------------------------------

async def run_verification(
    bug_number: str,
    bug_title: str,
    root_cause: str,
    patch_source: PatchSource,
    repro_script: Path,
    output_dir: Path,
    sequence: int,
    config: dict,
) -> tuple[str, Path, list]:
    """
    Apply patch, run reproduction script, analyse failures, retry if environmental.

    Returns (final_status, report_file, analyses_list).
    final_status is one of: RESOLVED | NOT_RESOLVED | ENVIRONMENTAL_ERROR
    """
    # execute_script lives in the sibling bug-reproduction-agent package.
    # Add it to sys.path if not already present.
    repro_agent_dir = str(Path(__file__).parent.parent / "bug-reproduction-agent")
    if repro_agent_dir not in sys.path:
        sys.path.insert(0, repro_agent_dir)
    try:
        from script_executor import execute_script  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise RuntimeError(
            "Could not import execute_script from bug-reproduction-agent. "
            "Ensure bug-reproduction-agent is installed alongside this agent "
            f"(expected at: {repro_agent_dir})."
        ) from exc

    ver_cfg = config.get("verification", {})
    max_attempts = int(ver_cfg.get("max_attempts", 3))
    script_timeout = int(ver_cfg.get("script_timeout", 600))
    retry_delay = int(ver_cfg.get("retry_delay_seconds", 60))

    script_content = repro_script.read_text(encoding="utf-8")

    report_file = create_verification_filename(output_dir, bug_number, bug_title, sequence)

    # Apply the patch once before the retry loop
    print(f"\n🔧 Applying patch: {patch_source.description}")
    apply_result = apply_patch(patch_source, Path(config["devstack_path"]) / "octavia")

    if not apply_result.success:
        _write_report(
            report_file, bug_number, bug_title, patch_source,
            status="PATCH_ERROR",
            attempts_data=[],
            analyses=[],
            error=apply_result.error,
        )
        return "PATCH_ERROR", report_file, []

    print("   ✅ Patch applied")

    # Load cross-run context for the failure analyser
    _ctx = load_context_section(config, "fix_verification")
    if _ctx:
        print("   📚 Context loaded from context files")

    attempts_data = []
    analyses = []
    final_status = "NOT_RESOLVED"

    try:
        for attempt in range(1, max_attempts + 1):
            print(f"\n🧪 Verification attempt {attempt}/{max_attempts}")
            print(f"   Running reproduction script (timeout: {script_timeout}s)...")

            result = execute_script(script_content, timeout=script_timeout)

            print(f"   Exit code: {result.exit_code} | Time: {result.execution_time:.1f}s")

            # Check if bug no longer triggers (fix works).
            # The reproduction script convention is:
            #   exit 0  — bug WAS reproduced (with BUG REPRODUCED marker)
            #   exit 1  — bug NOT reproduced (fix works)
            # Accept either exit code as RESOLVED provided the bug marker is absent
            # and the script did not time out (which would be inconclusive).
            bug_still_fires = "BUG REPRODUCED" in result.stdout.upper()
            if not bug_still_fires and not result.timeout_exceeded and result.exit_code in (0, 1):
                print("   ✅ Bug no longer triggers — fix RESOLVED!")
                attempts_data.append((result, None))
                final_status = "RESOLVED"
                break

            # Failure — analyse why
            print("   ❌ Verification failed — analysing cause...")
            analysis = await analyse_failure(
                exit_code=result.exit_code,
                execution_time=result.execution_time,
                timeout_exceeded=result.timeout_exceeded,
                stdout=result.stdout,
                stderr=result.stderr,
                bug_number=bug_number,
                bug_title=bug_title,
                root_cause=root_cause,
                patch_description=patch_source.description,
                config=config,
                context_section=_ctx,
            )

            print(f"   🔍 Cause: {analysis.cause}")
            print(f"   {analysis.explanation[:120]}")

            if analysis.cause == "FIX_FAILURE":
                decision = "STOP — fix failure is definitive, no retry"
                attempts_data.append((result, analysis))
                analyses.append(analysis)
                print(f"   {decision}")
                final_status = "NOT_RESOLVED"
                break

            # ENVIRONMENTAL or INCONCLUSIVE
            decision = (
                f"RETRY ({max_attempts - attempt} retries remaining)"
                if attempt < max_attempts
                else "STOP — max attempts reached"
            )
            attempts_data.append((result, analysis))
            analyses.append(analysis)
            print(f"   {decision}")

            if attempt < max_attempts:
                print(f"   ⏳ Waiting {retry_delay}s before retry...")
                time.sleep(retry_delay)
            else:
                final_status = "ENVIRONMENTAL_ERROR"

    finally:
        print("\n🔄 Reverting patch...")
        revert_patch(patch_source, Path(config["devstack_path"]) / "octavia", apply_result)
        print("   ✅ Patch reverted")

    _write_report(
        report_file, bug_number, bug_title, patch_source,
        status=final_status,
        attempts_data=attempts_data,
        analyses=analyses,
    )

    # Save learning on notable outcomes (not RESOLVED)
    if final_status in ("NOT_RESOLVED", "ENVIRONMENTAL_ERROR"):
        last_analysis = analyses[-1] if analyses else None
        _summary = (
            f"Verification {final_status} for bug #{bug_number} — {bug_title[:60]}. "
            f"Patch: {patch_source.description}. Attempts: {len(attempts_data)}. "
            + (last_analysis.explanation[:200] if last_analysis else "")
        )
        _learning = await generate_learning(_summary, "Fix Verification Agent", config)
        if _learning:
            save_learning(config["context"]["agent_context_file"], _learning, "Fix Verification Agent")

    return final_status, report_file, analyses


def _write_report(
    report_file: Path,
    bug_number: str,
    bug_title: str,
    patch_source: PatchSource,
    status: str,
    attempts_data: list,
    analyses: list,
    error: str = "",
) -> None:
    """Write the verification report markdown file."""
    lines = [
        "# Fix Verification Report",
        "",
        f"**Bug ID:** {bug_number}",
        f"**Title:** {bug_title}",
    ]

    status_icons = {
        "RESOLVED": "✅ RESOLVED",
        "NOT_RESOLVED": "❌ NOT_RESOLVED",
        "ENVIRONMENTAL_ERROR": "⚠️ ENVIRONMENTAL_ERROR",
        "PATCH_ERROR": "🔴 PATCH_ERROR",
    }
    lines.append(f"**Status:** {status_icons.get(status, status)}")
    lines.append(f"**Patch:** {patch_source.description}")
    lines.append(f"**Attempts:** {len(attempts_data)}")
    lines.append(f"**Verification Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    if error:
        lines += ["## Error", "", f"Could not apply patch: {error}", ""]

    lines += [
        format_verification_result(status, len(attempts_data),
                                   patch_source.description, analyses),
    ]

    if attempts_data:
        lines += ["## Attempt Details", ""]
        for i, (result, analysis) in enumerate(attempts_data, 1):
            lines += [f"### Attempt {i}", ""]
            if result:
                lines += [
                    f"**Exit code:** {result.exit_code}",
                    f"**Execution time:** {result.execution_time:.1f}s",
                    f"**Timeout:** {result.timeout_exceeded}",
                    "",
                ]
                if result.stdout.strip():
                    lines += ["**Output:**", "```", result.stdout[-3000:], "```", ""]
                if result.stderr.strip():
                    lines += ["**Stderr:**", "```", result.stderr[-1000:], "```", ""]
            if analysis:
                next_decision = (
                    "STOP (fix failure)" if analysis.cause == "FIX_FAILURE"
                    else "RETRY (environmental)" if analysis.should_retry
                    else "STOP (inconclusive)"
                )
                lines.append(
                    format_analysis_section(i, analysis, next_decision)
                )
            lines += ["---", ""]

    lines += ["", "*Generated by Octavia Fix Verification Agent*", ""]
    report_file.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Automated mode: process new fix proposals
# ---------------------------------------------------------------------------

async def run_automated(config: dict) -> None:
    """Process new fix proposals that have not yet been verified."""
    proposals_dir = Path(config["fix_proposals_dir"])
    repro_dir = Path(config["reproduction_reports_dir"])
    output_dir = Path(config["verifications_output_dir"])
    tracking_file = Path(config["verification_tracking_file"])
    max_per_run = int(config.get("max_proposals_per_run", 2))
    notif_config = load_notifications_config()

    output_dir.mkdir(parents=True, exist_ok=True)
    history = load_verification_history(tracking_file)

    proposal_files = sorted(
        [p for p in proposals_dir.glob("fix_proposal_*.md")
         if not p.stem.endswith("_context")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not proposal_files:
        print("No fix proposals found.")
        return

    print(f"📋 Found {len(proposal_files)} proposal(s)")
    processed = 0

    for proposal_file in proposal_files:
        if processed >= max_per_run:
            break

        bug_number, bug_title = extract_bug_info_from_proposal(proposal_file)
        if not bug_number:
            continue

        proposal_ts = extract_proposal_timestamp(proposal_file)
        should, sequence = should_verify_proposal(bug_number, proposal_ts, history)
        if not should:
            continue

        repro_script = find_reproduction_script(bug_number, repro_dir)
        if not repro_script:
            print(f"⏭️  Bug #{bug_number}: no reproduction script found, skipping")
            continue

        # Extract patch from proposal
        patch_diff = extract_patch_from_proposal(proposal_file)
        if not patch_diff:
            print(f"⏭️  Bug #{bug_number}: no diff block in proposal, skipping")
            continue

        # Write patch to a temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".patch", delete=False
        ) as pf:
            pf.write(patch_diff)
            patch_path = pf.name

        patch_source = PatchSource(
            source_type=PatchSourceType.FILE,
            value=patch_path,
            description=f"AI fix proposal for bug #{bug_number} ({proposal_file.name})",
        )

        # Extract root cause from proposal
        content = proposal_file.read_text(encoding="utf-8")
        rc_match = re.search(r"## Why This Fix\n+(.*?)(?=\n##|\Z)", content, re.DOTALL)
        root_cause = rc_match.group(1).strip()[:500] if rc_match else ""

        print(f"\n{'='*80}")
        print(f"Verifying fix for Bug #{bug_number}: {bug_title[:60]}")
        print(f"{'='*80}")

        status, report_file, analyses = await run_verification(
            bug_number=bug_number,
            bug_title=bug_title,
            root_cause=root_cause,
            patch_source=patch_source,
            repro_script=repro_script,
            output_dir=output_dir,
            sequence=sequence,
            config=config,
        )

        # Clean up temp patch file
        try:
            Path(patch_path).unlink(missing_ok=True)
        except Exception:  # pylint: disable=broad-except
            pass

        record_verification(
            tracking_file, bug_number, proposal_ts, sequence,
            report_file, status, patch_source.description,
            attempts=len(analyses) + 1,
        )
        history = load_verification_history(tracking_file)

        # Post to Launchpad
        _post_verification_to_launchpad(bug_number, status, report_file, config)

        # Write feedback file for the Fix Proposal Agent if not resolved
        if status == "NOT_RESOLVED" and analyses:
            _write_proposal_feedback(bug_number, proposals_dir, status, analyses)

        # Notify
        subject = f"Fix Verification: Bug #{bug_number} — {status}"
        summary = f"{bug_title[:60]} | {sequence} attempt(s)"
        notify_report(report_file, subject, summary, config, notif_config)

        processed += 1
        print(f"\n✅ Verification complete: {status}")


def _post_verification_to_launchpad(
    bug_number: str,
    status: str,
    report_file: Path,
    config: dict,
) -> None:
    """Post the verification result as a Launchpad bug comment."""
    content = report_file.read_text(encoding="utf-8")
    model_name = config.get("model", "claude-sonnet-4-6")
    comment = build_feedback_comment(content, model_name, max_chars=4000)

    if status == "RESOLVED":
        subject = "AI Fix Verified ✅ (automated, may contain errors)"
    elif status == "NOT_RESOLVED":
        subject = "AI Fix Verification Failed ❌ (automated, may contain errors)"
    else:
        subject = "AI Fix Verification Inconclusive ⚠️ (automated, may contain errors)"

    post_launchpad_comment_from_config(bug_number, subject, comment, config)


def _write_proposal_feedback(
    bug_number: str,
    proposals_dir: Path,
    status: str,
    analyses: list,
) -> None:
    """Write a feedback file for the Fix Proposal Agent to pick up."""
    feedback_file = proposals_dir / f"fix_proposal_{bug_number}_feedback.txt"
    last_analysis = analyses[-1] if analyses else None
    lines = [
        f"Fix verification result: {status}",
        "",
        "The Fix Verification Agent applied the proposed patch and re-ran the "
        "reproduction script. The bug still triggered.",
        "",
    ]
    if last_analysis:
        lines += ["Failure analysis:", last_analysis.explanation, ""]
    lines += [
        "Please generate a revised fix proposal that addresses this failure.",
    ]
    feedback_file.write_text("\n".join(lines), encoding="utf-8")
    print(f"   📝 Feedback written for Fix Proposal Agent: {feedback_file.name}")


# ---------------------------------------------------------------------------
# Manual mode
# ---------------------------------------------------------------------------

async def run_manual(args: argparse.Namespace, config: dict) -> None:
    """Run a single manual verification based on CLI arguments."""
    bug_number = str(args.bug)
    repro_dir = Path(config["reproduction_reports_dir"])
    output_dir = Path(config["verifications_output_dir"])
    tracking_file = Path(config["verification_tracking_file"])

    output_dir.mkdir(parents=True, exist_ok=True)

    repro_script = find_reproduction_script(bug_number, repro_dir)
    if not repro_script:
        print(f"❌ No reproduction script found for bug #{bug_number}")
        print(f"   Expected: {repro_dir}/scripts/bug_{bug_number}_reproduction.sh")
        sys.exit(1)

    # Build patch source
    if args.already_applied:
        patch_source = PatchSource(
            source_type=PatchSourceType.ALREADY_APPLIED,
            description="Developer pre-applied fix",
        )
    elif args.patch:
        patch_source = PatchSource(
            source_type=PatchSourceType.FILE,
            value=args.patch,
            description=f"Local patch file: {args.patch}",
        )
    elif args.branch:
        patch_source = PatchSource(
            source_type=PatchSourceType.BRANCH,
            value=args.branch,
            description=f"Local branch: {args.branch}",
        )
    elif args.gerrit:
        patch_source = PatchSource(
            source_type=PatchSourceType.GERRIT,
            value=str(args.gerrit),
            description=f"Gerrit change: {args.gerrit}",
        )
    else:
        print("❌ Specify one of: --patch, --branch, --gerrit, --already-applied")
        sys.exit(1)

    history = load_verification_history(tracking_file)
    ts = datetime.now().isoformat()
    _, sequence = should_verify_proposal(bug_number, ts, history)

    bug_title = args.title or f"Bug #{bug_number}"

    print(f"\n{'='*80}")
    print(f"Manual Fix Verification — Bug #{bug_number}")
    print(f"Patch: {patch_source.description}")
    print(f"{'='*80}")

    status, report_file, analyses = await run_verification(
        bug_number=bug_number,
        bug_title=bug_title,
        root_cause="",
        patch_source=patch_source,
        repro_script=repro_script,
        output_dir=output_dir,
        sequence=sequence,
        config=config,
    )

    record_verification(
        tracking_file, bug_number, ts, sequence,
        report_file, status, patch_source.description,
        attempts=len(analyses) + 1,
    )

    _post_verification_to_launchpad(bug_number, status, report_file, config)

    notif_config = load_notifications_config()
    notify_report(
        report_file,
        f"Fix Verification: Bug #{bug_number} — {status}",
        f"{bug_title[:60]}",
        config, notif_config,
    )

    print(f"\n{'='*80}")
    print(f"Result: {status}")
    print(f"Report: {report_file}")
    print(f"{'='*80}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Octavia Fix Verification Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Automated mode (processes new fix proposals)
  octavia-verify-fix

  # Manual mode — verify a local patch file
  octavia-verify-fix --bug 2150752 --patch ~/my-fix.patch

  # Manual mode — verify a local git branch
  octavia-verify-fix --bug 2150752 --branch fix/my-fix

  # Manual mode — verify a Gerrit change
  octavia-verify-fix --bug 2150752 --gerrit 987701

  # Manual mode — fix already applied, just re-run reproduction test
  octavia-verify-fix --bug 2150752 --already-applied
""",
    )
    parser.add_argument("--bug", type=int, metavar="N",
                        help="Bug number (manual mode)")
    parser.add_argument("--patch", metavar="FILE",
                        help="Local patch file to apply")
    parser.add_argument("--branch", metavar="NAME",
                        help="Local git branch to checkout")
    parser.add_argument("--gerrit", type=int, metavar="CHANGE",
                        help="Gerrit change number to fetch and apply")
    parser.add_argument("--already-applied", action="store_true",
                        help="Fix already applied; just re-run reproduction test")
    parser.add_argument("--title", metavar="TITLE",
                        help="Bug title for the report (manual mode, optional)")
    parser.add_argument("--post-only", action="store_true",
                        help="Skip verification; find the latest saved report for --bug N and post it to Launchpad.")

    args = parser.parse_args()
    config = load_config()

    if args.post_only:
        if not args.bug:
            print("❌ --post-only requires --bug N", file=sys.stderr)
            sys.exit(1)
        bug_id = str(args.bug)
        output_dir = Path(config["verifications_output_dir"])
        report = find_latest_report(output_dir, f"verification_{bug_id}_*.md")
        if not report:
            print(f"❌ No verification report found for bug {bug_id} in {output_dir}")
            sys.exit(1)
        print(f"📄 Using report: {report.name}")
        content = report.read_text(encoding="utf-8")
        if "RESOLVED" in content and "NOT_RESOLVED" not in content:
            subject = "AI Fix Verified ✅ (automated, may contain errors)"
        elif "NOT_RESOLVED" in content:
            subject = "AI Fix Verification Failed ❌ (automated, may contain errors)"
        else:
            subject = "AI Fix Verification Inconclusive ⚠️ (automated, may contain errors)"
        ok = post_report_to_launchpad(bug_id, subject, report, config, max_chars=4000)
        sys.exit(0 if ok else 1)

    print("\n" + "="*80)
    print("Fix Verification Agent")
    print("="*80 + "\n")
    print(f"  Proposals dir:  {config['fix_proposals_dir']}")
    print(f"  Reproductions:  {config['reproduction_reports_dir']}")
    print(f"  Output dir:     {config['verifications_output_dir']}")
    print(f"  Max attempts:   {config.get('verification', {}).get('max_attempts', 3)}")
    print(f"  Script timeout: {config.get('verification', {}).get('script_timeout', 600)}s")
    print(f"  Retry delay:    {config.get('verification', {}).get('retry_delay_seconds', 60)}s")
    print()

    if args.bug:
        await run_manual(args, config)
    else:
        await run_automated(config)


def cli_main() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    cli_main()
