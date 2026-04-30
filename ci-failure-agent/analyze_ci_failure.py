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
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import load_config
from prompts import get_ci_failure_prompt
from agents_lib import format_usage_info
from agents_lib.utils import slugify

CONFIG = load_config()


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
    from claude_agent_sdk import query, ClaudeAgentOptions

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
    print(f"  CI Failure Analysis")
    print(f"{'='*80}")
    print(f"  Project:      {project}")
    print(f"  Change:       #{change_number}")
    print(f"  Patchset:     PS{patchset}")
    print(f"  Pipeline:     {pipeline}")
    print(f"  Failing jobs: {len(jobs)}")
    print(f"  Gerrit:       {gerrit_url}")
    print(f"  Report:       {report_file.name}")
    print(f"{'='*80}\n")

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
    )

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
    print("  (The AI agent will fetch logs from Zuul and analyze each failing job)\n")

    result = None
    usage_info = None

    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                allowed_tools=["Bash", "WebFetch", "Write"],
                model=CONFIG.get("model", "claude-sonnet-4-6"),
            ),
        ):
            if hasattr(message, "text"):
                print(f"  {message.text}")
            elif hasattr(message, "result"):
                result = message.result

                if hasattr(message, "usage") or hasattr(message, "total_cost_usd"):
                    usage_info = format_usage_info(
                        usage_data=getattr(message, "usage", None),
                        cost_usd=getattr(message, "total_cost_usd", None),
                        model=getattr(message, "model", None),
                        duration_ms=getattr(message, "duration_ms", None),
                    )

                print(f"\n{'='*80}")
                print("  Analysis Complete!")
                print(f"{'='*80}")
                if result:
                    preview = result[:400].replace("\n", " ")
                    print(f"\n  Summary: {preview}...")

        # Append token usage to the report
        if report_file.exists():
            if usage_info:
                existing = report_file.read_text()
                if "## Token Usage & Cost" not in existing:
                    report_file.write_text(existing + "\n\n---\n\n" + usage_info)
            print(f"\n  Report saved: {report_file}")
            return report_file
        elif result:
            print(f"\n  Warning: Report file not found — saving AI result directly...")
            content = result
            if usage_info:
                content += "\n\n---\n\n" + usage_info
            report_file.write_text(content)
            print(f"  Saved to: {report_file}")
            return report_file
        else:
            print(f"\n  Warning: No report was generated for change #{change_number}")
            return None

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

    args = parser.parse_args()

    failure_data_file = Path(args.failure_data)
    if not failure_data_file.exists():
        print(f"Error: failure data file not found: {failure_data_file}", file=sys.stderr)
        sys.exit(1)

    with open(failure_data_file) as f:
        failure_data = json.load(f)

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
