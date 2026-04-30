#!/usr/bin/env python3
"""
OpenStack CI Failure Analysis Agent.

Monitors Zuul CI for failures in configured OpenStack repositories and
generates AI-powered analysis reports explaining why jobs failed and
whether re-running or a code fix is needed.

Monitoring mode (automated / systemd):
    ./ci_failure_agent.py
    ./ci_failure_agent.py --project openstack/octavia
    ./ci_failure_agent.py --pipeline check
    ./ci_failure_agent.py --hours-back 48
    ./ci_failure_agent.py --list-failures

Manual mode (analyse a specific failure right now):
    ./ci_failure_agent.py --change 982567
    ./ci_failure_agent.py --change 982567 --pipeline check
    ./ci_failure_agent.py --build <zuul-build-uuid>
"""
import json
import sys
import subprocess
import tempfile
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import load_config
from zuul_client import (
    fetch_recent_failures,
    group_failures_by_change,
    get_builds_for_change,
    get_build_by_uuid,
    get_latest_patchset_failures,
)
from failure_tracker import has_been_analyzed, record_analyzed_failure

CONFIG = load_config()
SCRIPT_DIR = Path(__file__).parent
ANALYZE_SCRIPT = SCRIPT_DIR / "analyze_ci_failure.py"


def run_analysis_subprocess(failure_data, output_dir):
    """
    Analyze a single CI failure group in a subprocess.

    Using a subprocess prevents asyncio event loop conflicts when processing
    multiple changes (each subprocess gets a fresh asyncio loop).

    Args:
        failure_data: Dict with change info and failing jobs list
        output_dir: Directory to write the report

    Returns:
        Path to the generated report file, or None on failure
    """
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        prefix="ci_failure_",
        delete=False,
    ) as f:
        json.dump(failure_data, f, indent=2)
        temp_file = Path(f.name)

    try:
        result = subprocess.run(
            [
                sys.executable,
                str(ANALYZE_SCRIPT),
                "--failure-data", str(temp_file),
                "--output-dir", str(output_dir),
            ],
            cwd=str(SCRIPT_DIR),
            timeout=1800,
        )

        if result.returncode != 0:
            print(f"  Warning: Analysis process exited with code {result.returncode}")

        # Find the report created during this subprocess run
        change_number = failure_data["change_number"]
        patchset = failure_data["patchset"]
        pattern = f"ci_failure_*_{change_number}_ps{patchset}_*.md"
        reports = sorted(
            Path(output_dir).glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        return reports[0] if reports else None

    except subprocess.TimeoutExpired:
        print(f"  Error: Analysis timed out for change #{failure_data['change_number']}")
        return None
    except Exception as e:
        print(f"  Error running analysis subprocess: {e}")
        return None
    finally:
        temp_file.unlink(missing_ok=True)


def list_recent_failures(projects, pipelines, hours_back):
    """
    Fetch and display recent failures without running analysis.

    Useful for previewing what would be analyzed.
    """
    print(f"\n{'='*80}")
    print(f"  Recent CI Failures (last {hours_back}h) — list mode only")
    print(f"{'='*80}\n")

    for project in projects:
        for pipeline in pipelines:
            print(f"  {project} / {pipeline}:")
            builds = fetch_recent_failures(
                project=project,
                pipeline=pipeline,
                zuul_base_url=CONFIG["zuul_base_url"],
                tenant=CONFIG["zuul_tenant"],
                hours_back=hours_back,
            )
            if not builds:
                print("    No recent failures found.")
                continue

            grouped = group_failures_by_change(builds, skip_non_voting=CONFIG["skip_non_voting"])
            for (change, patchset, proj, pip), jobs in sorted(grouped.items()):
                max_end = max(b.get("end_time", "") for b in jobs)
                job_names = [b.get("job_name", "?") for b in jobs]
                print(f"    Change #{change} PS{patchset}  ({max_end})")
                for j in job_names:
                    print(f"      - {j}")
            print()


def process_repo(project, pipeline, hours_back, output_dir, analyzed_count, max_changes):
    """
    Fetch failures for one project+pipeline and analyze unprocessed ones.

    Args:
        project: Project name
        pipeline: Pipeline name
        hours_back: Hours back to search
        output_dir: Report output directory
        analyzed_count: Running count of changes analyzed this cycle
        max_changes: Maximum changes to analyze per cycle

    Returns:
        Updated analyzed_count
    """
    print(f"\n  Checking {project} / {pipeline}  (last {hours_back}h)...")

    builds = fetch_recent_failures(
        project=project,
        pipeline=pipeline,
        zuul_base_url=CONFIG["zuul_base_url"],
        tenant=CONFIG["zuul_tenant"],
        hours_back=hours_back,
    )

    if not builds:
        print(f"    No failures found.")
        return analyzed_count

    print(f"    Found {len(builds)} failed builds.")

    grouped = group_failures_by_change(builds, skip_non_voting=CONFIG["skip_non_voting"])
    if not grouped:
        print(f"    No failures to process after filtering.")
        return analyzed_count

    print(f"    Grouped into {len(grouped)} unique change/patchset combinations.")

    # Sort by most recent failure first
    sorted_groups = sorted(
        grouped.items(),
        key=lambda kv: max(b.get("end_time", "1970-01-01T00:00:00") for b in kv[1]),
        reverse=True,
    )

    for (change_number, patchset, proj, pip), jobs in sorted_groups:
        if analyzed_count >= max_changes:
            print(f"\n    Reached max_changes_per_cycle ({max_changes}), stopping.")
            break

        # Use the latest job end_time as "last updated" for tracking
        last_updated = max(b.get("end_time", "1970-01-01T00:00:00") for b in jobs)

        already_done, sequence = has_been_analyzed(
            tracking_file=CONFIG["analyzed_failures_file"],
            change_number=change_number,
            patchset=patchset,
            pipeline=pipeline,
            last_updated=last_updated,
        )

        if already_done:
            print(f"    Skipping #{change_number} PS{patchset} — already analyzed.")
            continue

        # Build ref_url from first job (Zuul includes the Gerrit URL)
        gerrit_url = f"{CONFIG['gerrit_base_url']}/c/{project}/+/{change_number}"
        if jobs and jobs[0].get("ref_url"):
            gerrit_url = jobs[0]["ref_url"]

        failure_data = {
            "change_number": change_number,
            "patchset": patchset,
            "project": proj,
            "pipeline": pip,
            "gerrit_url": gerrit_url,
            "sequence": sequence,
            "jobs": [
                {
                    "job_name": b.get("job_name", "unknown"),
                    "uuid": b.get("uuid", ""),
                    "log_url": b.get("log_url", ""),
                    "duration": b.get("duration", 0),
                    "voting": b.get("voting", True),
                    "end_time": b.get("end_time", ""),
                    "nodeset": b.get("nodeset", ""),
                }
                for b in jobs
            ],
        }

        print(f"\n    Analyzing #{change_number} PS{patchset}  ({len(jobs)} failing jobs)")

        report_file = run_analysis_subprocess(failure_data, output_dir)

        if report_file:
            print(f"    Report: {report_file.name}")
            record_analyzed_failure(
                tracking_file=CONFIG["analyzed_failures_file"],
                change_number=change_number,
                patchset=patchset,
                pipeline=pipeline,
                last_updated=last_updated,
                sequence=sequence,
                extra_data={"report_file": str(report_file)},
            )
            analyzed_count += 1
        else:
            print(f"    Warning: No report generated for #{change_number}.")

    return analyzed_count


def _build_to_job_dict(build):
    """Extract the fields we pass to analyze_ci_failure from a Zuul build dict."""
    log_url = build.get("log_url", "")
    if log_url and not log_url.endswith("/"):
        log_url += "/"
    return {
        "job_name": build.get("job_name", "unknown"),
        "uuid": build.get("uuid", ""),
        "log_url": log_url,
        "duration": build.get("duration", 0),
        "voting": build.get("voting", True),
        "end_time": build.get("end_time", ""),
        "nodeset": build.get("nodeset", ""),
    }


def analyze_by_change(change_number, pipeline=None):
    """
    Manually analyze a specific Gerrit change number.

    Queries Zuul for all failed builds for that change, selects the latest
    patchset, and runs analysis for each failing pipeline (or just the one
    specified via --pipeline).

    Args:
        change_number: Gerrit change number (string or int)
        pipeline: Optional pipeline to restrict analysis to
    """
    change_number = str(change_number)

    print(f"\n{'='*80}")
    print(f"  Manual Analysis — Gerrit Change #{change_number}")
    if pipeline:
        print(f"  Pipeline filter: {pipeline}")
    print(f"  Zuul: {CONFIG['zuul_base_url']}")
    print(f"{'='*80}")

    print(f"\n  Fetching failed builds for change #{change_number}...")
    builds = get_builds_for_change(
        change_number=change_number,
        zuul_base_url=CONFIG["zuul_base_url"],
        tenant=CONFIG["zuul_tenant"],
        pipeline=pipeline,
        result="FAILURE",
    )

    if not builds:
        print(f"\n  No failed builds found for change #{change_number}.")
        if not pipeline:
            print(f"  Tip: try --pipeline check or --pipeline gate if you expect failures.")
        return

    print(f"  Found {len(builds)} failed build(s).")

    latest_patchset, grouped = get_latest_patchset_failures(builds)
    if not grouped:
        print(f"  Could not group failures — check the build data.")
        return

    pipeline_names = sorted({pip for (_, _, pip) in grouped.keys()})
    print(f"  Latest patchset: PS{latest_patchset}")
    print(f"  Failing pipeline(s): {', '.join(pipeline_names)}")

    output_dir = Path(CONFIG["reports_output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    for (ps, proj, pip), jobs in sorted(grouped.items()):
        last_updated = max(b.get("end_time", "1970-01-01T00:00:00") for b in jobs)
        gerrit_url = f"{CONFIG['gerrit_base_url']}/c/{proj}/+/{change_number}"
        if jobs and jobs[0].get("ref_url"):
            gerrit_url = jobs[0]["ref_url"]

        failure_data = {
            "change_number": change_number,
            "patchset": ps,
            "project": proj,
            "pipeline": pip,
            "gerrit_url": gerrit_url,
            "sequence": 1,
            "jobs": [_build_to_job_dict(b) for b in jobs],
        }

        print(f"\n  Analyzing PS{ps} / {pip}  ({len(jobs)} failing job(s))...")
        report_file = run_analysis_subprocess(failure_data, output_dir)

        if report_file:
            print(f"  Report saved: {report_file}")
        else:
            print(f"  Warning: No report generated for {pip}.")


def analyze_by_build(build_uuid):
    """
    Manually analyze a single Zuul build by its UUID.

    Fetches build metadata from Zuul and runs a single-job analysis report.

    Args:
        build_uuid: Zuul build UUID (full UUID string)
    """
    print(f"\n{'='*80}")
    print(f"  Manual Analysis — Zuul Build {build_uuid}")
    print(f"  Zuul: {CONFIG['zuul_base_url']}")
    print(f"{'='*80}")

    print(f"\n  Fetching build details from Zuul...")
    build = get_build_by_uuid(
        uuid=build_uuid,
        zuul_base_url=CONFIG["zuul_base_url"],
        tenant=CONFIG["zuul_tenant"],
    )

    if not build:
        print(f"\n  Could not retrieve build {build_uuid}.")
        print(f"  Verify the UUID and that ZUUL_TENANT is correct (current: {CONFIG['zuul_tenant']}).")
        return

    job_name = build.get("job_name", "unknown")
    project = build.get("project", "unknown")
    change = build.get("change")
    patchset = str(build.get("patchset", "1"))
    pipeline = build.get("pipeline", "unknown")
    result = build.get("result", "UNKNOWN")

    print(f"\n  Job:      {job_name}")
    print(f"  Project:  {project}")
    print(f"  Change:   #{change} PS{patchset}")
    print(f"  Pipeline: {pipeline}")
    print(f"  Result:   {result}")

    if result not in ("FAILURE", "TIMED_OUT", "POST_FAILURE", "NODE_FAILURE"):
        print(f"\n  Note: Result is '{result}' — not a typical failure, but analyzing anyway.")

    gerrit_url = f"{CONFIG['gerrit_base_url']}/c/{project}/+/{change}" if change else ""
    if build.get("ref_url"):
        gerrit_url = build["ref_url"]

    failure_data = {
        "change_number": str(change) if change else "unknown",
        "patchset": patchset,
        "project": project,
        "pipeline": pipeline,
        "gerrit_url": gerrit_url,
        "sequence": 1,
        "jobs": [_build_to_job_dict(build)],
    }

    output_dir = Path(CONFIG["reports_output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n  Running analysis...")
    report_file = run_analysis_subprocess(failure_data, output_dir)

    if report_file:
        print(f"\n  Report saved: {report_file}")
    else:
        print(f"\n  Warning: No report was generated.")


def main_loop(projects=None, pipelines=None, hours_back=None, list_only=False):
    """
    Main entry point for the monitoring loop.

    Args:
        projects: List of project names to check (overrides config)
        pipelines: List of pipeline names to check (overrides config)
        hours_back: Hours back to look for failures (overrides config)
        list_only: If True, list failures without analyzing
    """
    start_time = datetime.now()

    if projects is None:
        projects = CONFIG["repositories"]
    if pipelines is None:
        pipelines = CONFIG["zuul_pipelines"]
    if hours_back is None:
        hours_back = CONFIG["hours_back"]

    print(f"\n{'='*80}")
    print(f"  OpenStack CI Failure Analysis Agent")
    print(f"{'='*80}")
    print(f"  Projects:    {', '.join(projects)}")
    print(f"  Pipelines:   {', '.join(pipelines)}")
    print(f"  Hours back:  {hours_back}")
    if not list_only:
        print(f"  Max changes: {CONFIG['max_changes_per_cycle']}")
        print(f"  Output dir:  {CONFIG['reports_output_dir']}")
    print(f"  Zuul:        {CONFIG['zuul_base_url']}")
    print(f"  Started:     {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*80}")

    if list_only:
        list_recent_failures(projects, pipelines, hours_back)
        return

    output_dir = Path(CONFIG["reports_output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)

    max_changes = CONFIG["max_changes_per_cycle"]
    analyzed_count = 0

    for project in projects:
        for pipeline in pipelines:
            analyzed_count = process_repo(
                project=project,
                pipeline=pipeline,
                hours_back=hours_back,
                output_dir=output_dir,
                analyzed_count=analyzed_count,
                max_changes=max_changes,
            )

    duration = (datetime.now() - start_time).total_seconds()

    print(f"\n{'='*80}")
    print(f"  Run complete")
    print(f"  Duration:         {duration:.1f}s")
    print(f"  Changes analyzed: {analyzed_count}")
    print(f"  Reports in:       {output_dir}")
    print(f"{'='*80}")


def main():
    parser = argparse.ArgumentParser(
        description="OpenStack CI Failure Analysis Agent — monitors Zuul for failures and explains them",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Manual analysis (analyse a specific failure right now):
  # Analyse latest failed pipeline for a Gerrit change
  %(prog)s --change 982567

  # Analyse a specific pipeline for a change
  %(prog)s --change 982567 --pipeline check

  # Analyse a single Zuul build by UUID
  %(prog)s --build abc123def456789...

Monitoring mode (scan all configured repos for recent failures):
  %(prog)s
  %(prog)s --project openstack/octavia
  %(prog)s --pipeline gate
  %(prog)s --hours-back 48
  %(prog)s --list-failures
        """,
    )

    # ── Manual analysis arguments ──────────────────────────────────────────────
    manual = parser.add_argument_group("manual analysis")
    manual.add_argument(
        "--change",
        metavar="CHANGE_NUMBER",
        help=(
            "Analyse a specific Gerrit change. Fetches all failed builds for "
            "the latest patchset and generates a report. Combine with "
            "--pipeline to restrict to one pipeline."
        ),
    )
    manual.add_argument(
        "--build",
        metavar="UUID",
        help="Analyse a single Zuul build by its full UUID.",
    )

    # ── Monitoring mode arguments ──────────────────────────────────────────────
    monitoring = parser.add_argument_group("monitoring mode")
    monitoring.add_argument(
        "--project",
        metavar="PROJECT",
        help="Restrict to one project (e.g., openstack/octavia). Overrides config.",
    )
    monitoring.add_argument(
        "--pipeline",
        metavar="PIPELINE",
        help=(
            "Restrict to one pipeline (e.g., check, gate). "
            "Used by both --change and monitoring mode."
        ),
    )
    monitoring.add_argument(
        "--hours-back",
        type=int,
        metavar="N",
        help="Hours back to search for failures. Overrides config.",
    )
    monitoring.add_argument(
        "--list-failures",
        action="store_true",
        help="List recent failures without running AI analysis.",
    )

    args = parser.parse_args()

    # Manual modes take priority over monitoring loop
    if args.change and args.build:
        parser.error("--change and --build are mutually exclusive")

    if args.change:
        analyze_by_change(args.change, pipeline=args.pipeline)
        return

    if args.build:
        analyze_by_build(args.build)
        return

    # Monitoring loop
    main_loop(
        projects=[args.project] if args.project else None,
        pipelines=[args.pipeline] if args.pipeline else None,
        hours_back=args.hours_back,
        list_only=args.list_failures,
    )


def cli_main():
    """Entry point for console_scripts."""
    main()


if __name__ == "__main__":
    cli_main()
