#!/usr/bin/env python3
"""
Analyze CI failures for a single Gerrit change using AI.

This script is the AI-powered core of the CI Failure Analysis Agent. It:
  1. Reads failure data (jobs, log URLs) from a JSON file
  2. Builds a structured analysis prompt
  3. Invokes an AI agent (via claude-agent-sdk) to fetch logs and analyze failures
  4. Saves a comprehensive markdown report

Usage (standalone):
    ./analyze_ci_failure.py --failure-data /tmp/failure_data.json
    ./analyze_ci_failure.py --failure-data /tmp/failure_data.json --print-prompt
    ./analyze_ci_failure.py --failure-data /tmp/failure_data.json --output-dir ~/my_reports

Usage (called by ci_failure_agent.py):
    python analyze_ci_failure.py --failure-data /tmp/ci_failure_abc123.json --output-dir ~/octavia_ci_failures

The failure-data JSON format:
{
    "change_number": "982567",
    "patchset": "3",
    "project": "openstack/octavia",
    "pipeline": "check",
    "gerrit_url": "https://review.opendev.org/c/openstack/octavia/+/982567",
    "sequence": 1,
    "jobs": [
        {
            "job_name": "octavia-v2-dsvm-scenario-centos-9-stream-ovn",
            "uuid": "abc123def456...",
            "log_url": "https://storage.bhs.logs.ovh.net/v1/.../",
            "duration": 2843.0,
            "voting": true,
            "end_time": "2026-04-30T10:47:23",
            "nodeset": "centos-9-stream"
        }
    ]
}

Tool-agnostic use:
    Run with --print-prompt to get the formatted prompt without invoking any AI.
    You can then paste the prompt into Claude.ai, Cursor, or any other AI tool.
"""
import asyncio
import json
import sys
import argparse
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import load_config
from prompts import get_ci_failure_prompt
from log_scanner import scan_log_for_errors, format_scan_results
from agents_lib import (
    format_usage_info,
    create_forge_client,
    load_context_section,
    extract_ci_forge_comment,
    find_latest_report,
    fetch_log_section,
    AuditRule,
    audit_report_file,
    build_audit_prompt,
)
from agents_lib.utils import slugify

CONFIG = load_config()


class _SafeDict(dict):
    """dict subclass for format_map() that leaves unknown {KEYS} unchanged."""
    def __missing__(self, key: str) -> str:
        return f"{{{key}}}"


# Audit rules for CI failure analysis reports
_CI_AUDIT_RULES = [
    AuditRule.must_start_with("# CI Failure Analysis:"),
    AuditRule.must_contain("## Failing Jobs Overview"),
    AuditRule.must_contain("## Detailed Analysis"),
    AuditRule.must_contain("## Overall Recommendation"),
    AuditRule.must_contain("**Category:**"),
    AuditRule.must_contain("END OF REPORT"),
]


def _prefetch_job_logs(jobs: list, scan_patterns: list) -> str:
    """Pre-fetch job-output.txt for each failing job and run the error scanner.

    Returns a formatted markdown block ready to embed in the AI prompt.
    """
    sections = []
    for job in jobs:
        job_name = job.get("job_name", "unknown")
        log_url = job.get("log_url", "")
        sections.append(f"### Job: {job_name}")

        if not log_url:
            sections.append("_Log URL not available._\n")
            continue

        fetch_url = log_url.rstrip("/") + "/job-output.txt"
        ok, content = fetch_log_section(fetch_url)

        if ok:
            scan = scan_log_for_errors(content, scan_patterns)
            scan_block = format_scan_results(scan, job_name)
            if scan_block:
                sections.append(scan_block)
                sections.append("")
            sections.append("**Log excerpt (last lines of job-output.txt):**")
            sections.append(f"```\n{content}\n```")
        else:
            sections.append(
                f"_Could not pre-fetch log: {content}_\n"
                "_The AI agent may attempt to fetch secondary log files if needed._"
            )
        sections.append("")

    return "\n".join(sections)


def _post_ci_feedback(failure_data: dict, report_content: str) -> bool:
    """Post the CI analysis summary as a comment on the forge change.

    Returns True on success, False on any failure. Errors are logged but
    never re-raised.
    """
    if not CONFIG.get("feedback_enabled"):
        return False

    try:
        forge = create_forge_client(CONFIG)
        change_number = str(failure_data["change_number"])
        project = failure_data["project"]
        model_name = CONFIG.get("model", "claude-sonnet-4-6")

        change_info = forge.get_change(change_number, project)
        comment = extract_ci_forge_comment(report_content, model_name)

        print(f"\n📤 Posting CI analysis feedback to {change_info.forge_type}...")
        ok = forge.post_feedback(change_info, comment, vote=None, line_comments=[])
        if ok:
            print("   ✅ Feedback posted successfully")
        else:
            print("   ⚠️  Feedback post returned failure (see warnings above)")
        return ok
    except Exception as exc:
        print(f"   ⚠️  Could not post forge feedback: {exc}")
        return False


def _post_only_ci(failure_data: dict, output_dir: "str | None") -> bool:
    """Find the latest saved CI report for a change and post it to the forge."""
    change_number = str(failure_data["change_number"])
    patchset = failure_data.get("patchset")
    reports_dir = Path(
        output_dir or CONFIG.get("reports_output_dir", "~/octavia_ci_failures")
    ).expanduser()
    ps_glob = f"ps{patchset}_" if patchset is not None else "ps*_"
    report = find_latest_report(reports_dir, f"ci_failure_*_{change_number}_{ps_glob}*.md")
    if not report:
        print(f"❌ No CI report found for change {change_number} in {reports_dir}")
        return False
    print(f"📄 Using report: {report.name}")
    return _post_ci_feedback(failure_data, report.read_text(encoding="utf-8"))


def create_report_filename(output_dir, project, change_number, patchset, sequence):
    """Generate a timestamped report filename."""
    project_slug = slugify(project.split("/")[-1])
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(output_dir) / f"ci_failure_{project_slug}_{change_number}_ps{patchset}_{timestamp}_{sequence}.md"


async def analyze_failure(failure_data, output_dir=None, print_prompt=False):
    """
    Analyze CI failures for a single change using an AI agent.

    Args:
        failure_data: Dict containing change info and list of failing jobs
        output_dir: Override output directory (defaults to config value)
        print_prompt: If True, print the formatted prompt and exit without calling AI.
                      Use this with other AI tools (Cursor, Claude.ai, etc.)

    Returns:
        Path to the generated report file, or None on failure
    """
    from agents_lib import create_model_client as _create_model_client

    change_number = str(failure_data["change_number"])
    patchset = str(failure_data["patchset"])
    project = failure_data["project"]
    pipeline = failure_data["pipeline"]
    gerrit_url = failure_data.get(
        "gerrit_url",
        f"{CONFIG['gerrit_base_url']}/c/{project}/+/{change_number}",
    )
    jobs = failure_data["jobs"]
    sequence = failure_data.get("sequence", 1)

    if output_dir is None:
        output_dir = CONFIG["reports_output_dir"]
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report_file = create_report_filename(output_dir, project, change_number, patchset, sequence)

    print(f"\n{'='*80}")
    print("  CI Failure Analysis")
    print(f"{'='*80}")
    print(f"  Project:      {project}")
    print(f"  Change:       #{change_number}")
    print(f"  Patchset:     PS{patchset}")
    print(f"  Pipeline:     {pipeline}")
    print(f"  Failing jobs: {len(jobs)}")
    print(f"  Gerrit:       {gerrit_url}")
    print(f"  Report:       {report_file.name}")
    print(f"{'='*80}\n")

    # Pre-fetch logs and run error scanner before calling the AI.
    scan_patterns = CONFIG.get("log_scan_patterns", [])
    print(f"📡 Pre-fetching logs for {len(jobs)} job(s)...")
    job_log_excerpts = _prefetch_job_logs(jobs, scan_patterns)
    print("   ✅ Log pre-fetch complete\n")

    # Load and pre-fill the report template.
    _template_path = Path(__file__).parent / "report_template.md"
    _zuul_search = (
        f"{CONFIG['zuul_base_url']}/t/{CONFIG['zuul_tenant']}/builds?change={change_number}"
    )
    _analysis_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    _gerrit_url = f"{CONFIG['gerrit_base_url']}/c/{project}/+/{change_number}"
    if _template_path.exists():
        report_template = _template_path.read_text(encoding="utf-8").format_map(
            _SafeDict(
                PROJECT=project,
                CHANGE_NUMBER=str(change_number),
                PATCHSET=str(patchset),
                PIPELINE=pipeline,
                ANALYSIS_DATE=_analysis_date,
                GERRIT_URL=_gerrit_url,
                TOTAL_FAILURES=str(len(jobs)),
                ZUUL_BUILD_SEARCH_URL=_zuul_search,
            )
        )
    else:
        report_template = f"[Write the CI failure analysis report here for change #{change_number}]"

    _provider = CONFIG.get("model_provider", "anthropic")
    prompt = get_ci_failure_prompt(
        project=project,
        change_number=change_number,
        patchset=patchset,
        pipeline=pipeline,
        gerrit_base_url=CONFIG["gerrit_base_url"],
        zuul_base_url=CONFIG["zuul_base_url"],
        zuul_tenant=CONFIG["zuul_tenant"],
        failing_jobs=jobs,
        output_file=str(report_file),
        provider=_provider,
        save_path=str(report_file),
        job_log_excerpts=job_log_excerpts,
        report_template=report_template,
    )

    _ctx = load_context_section(CONFIG, "ci_failure")
    if _ctx:
        prompt = _ctx + "\n\n---\n\n" + prompt

    if print_prompt:
        print("=" * 80)
        print("FORMATTED PROMPT (--print-prompt mode)")
        print("Copy the text below and paste into your AI tool of choice.")
        print("=" * 80)
        print(prompt)
        print("=" * 80)
        print(f"\nReport would be saved to: {report_file}")
        print("\nTo use with an AI tool other than Claude Code:")
        print("  1. Copy the prompt above")
        print("  2. Paste into your preferred AI assistant")
        print("  3. Instruct it to write the report to the path shown above")
        return None

    print("Starting AI-powered CI failure analysis...\n")
    print("  (Logs are pre-fetched; the AI focuses on root cause analysis)\n")

    result = None
    usage_info = None

    try:
        _client = _create_model_client(CONFIG)
        _res = await _client.query(
            prompt=prompt,
            # WebFetch kept as fallback for secondary log files the AI may need;
            # primary job-output.txt is already embedded in the prompt.
            tools=["Bash", "WebFetch", "Write"],
            on_progress=lambda text: print(f"  {text}"),
        )
        result = _res.text
        usage_info = format_usage_info(
            usage_data=_res.usage,
            cost_usd=_res.cost_usd,
            model=_res.model,
            duration_ms=_res.duration_ms,
        )

        print(f"\n{'='*80}")
        print("  Analysis Complete!")
        print(f"{'='*80}")

        # Resolve canonical report content.
        if report_file.exists() and report_file.stat().st_size > 200:
            content = report_file.read_text(encoding="utf-8")
        elif result:
            print("\n  ⚠️  Report file not found — saving AI result directly...")
            content = result
        else:
            print(f"\n  Warning: No report was generated for change #{change_number}")
            return None

        # Append token usage once.
        if usage_info and "## Token Usage & Cost" not in content:
            content += "\n\n---\n\n" + usage_info
        report_file.write_text(content, encoding="utf-8")
        print(f"\n  Report saved: {report_file}")

        # Audit loop: validate report format; ask AI to fix if needed.
        _MAX_AUDIT_RETRIES = 2
        for _attempt in range(_MAX_AUDIT_RETRIES + 1):
            _passed, _errors = audit_report_file(report_file, _CI_AUDIT_RULES)
            if _passed:
                print("   ✅ Report format validated")
                break
            print(f"\n   ⚠️  Report format issues (attempt {_attempt + 1}/{_MAX_AUDIT_RETRIES + 1}):")
            for _err in _errors:
                print(f"      - {_err}")
            if _attempt < _MAX_AUDIT_RETRIES:
                _fix_prompt = (
                    f"Read the report at {report_file}, fix every issue listed "
                    f"below, and rewrite the entire file.\n\n"
                    + build_audit_prompt(_errors, str(report_file))
                )
                await _client.query(
                    prompt=_fix_prompt,
                    tools=["Read", "Write"],
                    on_progress=lambda text: print(f"  {text}"),
                )
            else:
                print("   ⚠️  Report still invalid after retries — proceeding with best effort")

        _post_ci_feedback(failure_data, report_file.read_text(encoding="utf-8"))
        return report_file

    except Exception as e:
        print(f"\n  Error during analysis: {e}")
        import traceback
        traceback.print_exc()
        return None


def main():
    parser = argparse.ArgumentParser(
        description="Analyze CI failures for an OpenStack Gerrit change",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Analyze using failure data JSON (standard usage)
  %(prog)s --failure-data /tmp/failure_data.json

  # Print prompt only — paste into any AI tool (Cursor, Claude.ai, etc.)
  %(prog)s --failure-data /tmp/failure_data.json --print-prompt

  # Save report to a custom directory
  %(prog)s --failure-data /tmp/failure_data.json --output-dir ~/my_ci_reports

Failure data JSON format:
  {
    "change_number": "982567",
    "patchset": "3",
    "project": "openstack/octavia",
    "pipeline": "check",
    "gerrit_url": "https://review.opendev.org/c/openstack/octavia/+/982567",
    "jobs": [
      {
        "job_name": "octavia-v2-dsvm-scenario-centos-9-stream-ovn",
        "uuid": "abc123...",
        "log_url": "https://storage.bhs.logs.ovh.net/v1/.../",
        "duration": 2843.0,
        "voting": true,
        "end_time": "2026-04-30T10:47:23",
        "nodeset": "centos-9-stream"
      }
    ]
  }
        """,
    )

    parser.add_argument(
        "--failure-data",
        required=True,
        metavar="FILE",
        help="JSON file containing failure information (jobs, log URLs, change details)",
    )
    parser.add_argument(
        "--print-prompt",
        action="store_true",
        help=(
            "Print the formatted analysis prompt and exit without invoking AI. "
            "Useful for using with other AI tools (Cursor, Claude.ai, Copilot, etc.)"
        ),
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        help="Directory to save the report (overrides config)",
    )
    parser.add_argument(
        "--post-only",
        action="store_true",
        help="Skip analysis; find the latest saved report for this change and post it to the forge.",
    )

    args = parser.parse_args()

    failure_data_file = Path(args.failure_data)
    if not failure_data_file.exists():
        print(f"Error: failure data file not found: {failure_data_file}", file=sys.stderr)
        sys.exit(1)

    with open(failure_data_file, encoding='utf-8') as f:
        failure_data = json.load(f)

    if args.post_only:
        ok = _post_only_ci(failure_data, args.output_dir)
        sys.exit(0 if ok else 1)

    asyncio.run(analyze_failure(
        failure_data=failure_data,
        output_dir=args.output_dir,
        print_prompt=args.print_prompt,
    ))


def cli_main():
    """Entry point for console_scripts."""
    main()


if __name__ == "__main__":
    cli_main()
