#!/usr/bin/env python3
"""
JIRA Triage Agent

Reads JIRA issues matching a configurable JQL query and:
  - Bugs/Defects: produces an AI-powered triage report
  - Stories/Tasks: produces an AI-powered implementation plan with risk assessment

Output is saved to ~/jira_triages/ (bugs) or ~/jira_plans/ (stories/tasks).
"""

import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import load_config
from issue_tracker import create_output_file_path
from issue_tracker import load_issue_history
from issue_tracker import record_processed_issue
from issue_tracker import should_process_issue
from jira_client import JiraClient
from jira_client import create_jira_client
from prompts import get_jira_bug_triage_prompt
from prompts import get_jira_planning_prompt
from agents_lib import build_feedback_comment
from agents_lib import create_model_client
from agents_lib import find_latest_report
from agents_lib import format_usage_info
from agents_lib import load_context_section
from agents_lib import load_notifications_config
from agents_lib import notify_report
from agents_lib import HelpOnErrorParser
from agents_lib import add_jira_args
from agents_lib import add_post_args
from agents_lib import add_summary_args
from agents_lib import resolve_jira_target
from agents_lib import confirm_reprocess
from agents_lib import generate_summary
from agents_lib import print_summary
from agents_lib import needs_summary

CONFIG = load_config()


# ---------------------------------------------------------------------------
# Forge feedback posting
# ---------------------------------------------------------------------------

def _post_jira_feedback(issue: dict, report_file: "Path", config: dict) -> None:
    """Post the report as a comment on the JIRA issue.

    Errors are logged but never re-raised — a failed post must not prevent
    the report from being recorded locally.
    """
    if not config.get("feedback_enabled"):
        return
    try:
        content = report_file.read_text(encoding="utf-8")
        model_name = config.get("model", "claude-sonnet-4-6")
        comment = build_feedback_comment(content, model_name, max_chars=6000)
        issue_key = JiraClient.issue_key(issue)
        jira = create_jira_client(config)
        private = config.get("feedback_private", True)
        role = config.get("feedback_visibility_role", "Service Desk Team")
        print(f"\n📤 Posting {'private ' if private else ''}comment to JIRA {issue_key}...")
        ok = jira.add_comment(issue_key, comment, private=private, visibility_role=role)
        if ok:
            print(f"   ✅ Comment posted to {issue_key}")
        else:
            print("   ⚠️  Comment post returned failure (see warning above)")
    except Exception as exc:
        print(f"   ⚠️  Could not post JIRA feedback: {exc}")


# ---------------------------------------------------------------------------
# Issue dispatch helpers
# ---------------------------------------------------------------------------

def _is_bug(issue: dict, config: dict) -> bool:
    itype = config.get("issue_types", {}).get("bugs", ["Bug", "Defect"])
    return JiraClient.issue_type(issue) in itype


def _is_plannable(issue: dict, config: dict) -> bool:
    itype = config.get("issue_types", {}).get("planning", ["Story", "Task", "Epic"])
    return JiraClient.issue_type(issue) in itype


def _find_previous_output(output_dir: Path, issue_key: str) -> tuple[str | None, int]:
    """Find the most recent output file for an issue and return (summary, sequence)."""
    slug = issue_key.replace("-", "_")
    pattern = f"jira_{slug}_*_*.md"
    candidates = sorted(output_dir.glob(pattern), key=lambda p: p.stat().st_mtime)
    if not candidates:
        return None, 0
    latest = candidates[-1]
    content = latest.read_text(encoding="utf-8")[:2000]
    # Extract sequence from filename
    parts = latest.stem.split("_")
    try:
        seq = int(parts[-1])
    except (ValueError, IndexError):
        seq = 1
    return content, seq


# ---------------------------------------------------------------------------
# Single-issue processing (called in subprocess for isolation)
# ---------------------------------------------------------------------------

async def process_bug(issue: dict, sequence: int, save_path: str) -> None:
    """Triage a single JIRA bug and save the report."""
    client = create_jira_client(CONFIG)
    _provider = CONFIG.get("model_provider", "anthropic")
    devstack = CONFIG.get("devstack_path", "/opt/stack")

    triages_dir = Path(CONFIG["triages_dir"])
    previous_summary, prev_seq = _find_previous_output(triages_dir, JiraClient.issue_key(issue))

    prompt = get_jira_bug_triage_prompt(
        issue_key=JiraClient.issue_key(issue),
        summary=JiraClient.summary(issue),
        issue_type=JiraClient.issue_type(issue),
        status=JiraClient.status(issue),
        priority=JiraClient.priority(issue),
        reporter=JiraClient.reporter(issue),
        assignee=JiraClient.assignee(issue),
        jira_url=client.issue_url(issue),
        created=JiraClient.created(issue),
        updated=JiraClient.updated(issue),
        description=JiraClient.description_text(issue),
        devstack_path=devstack,
        sequence=sequence,
        previous_triage_summary=previous_summary,
        previous_sequence=prev_seq if prev_seq else None,
        provider=_provider,
        save_path=save_path,
    )

    _ctx = load_context_section(CONFIG, "jira_triage")
    if _ctx:
        prompt = _ctx + "\n\n---\n\n" + prompt

    print(f"🤖 Starting bug triage for {JiraClient.issue_key(issue)}...\n")

    model_client = create_model_client(CONFIG)
    result = await model_client.query(
        prompt=prompt,
        tools=["Bash", "Read", "Write", "Grep", "Glob"],
        on_progress=lambda text: print(f"  {text}"),
    )

    report_path = Path(save_path)
    _save_result(result, report_path)
    print(f"\n✅ Triage saved to: {report_path}")
    _post_jira_feedback(issue, report_path, CONFIG)


async def process_plan(issue: dict, sequence: int, save_path: str) -> None:
    """Produce an implementation plan for a JIRA Story/Task and save it."""
    client = create_jira_client(CONFIG)
    _provider = CONFIG.get("model_provider", "anthropic")
    devstack = CONFIG.get("devstack_path", "/opt/stack")

    plans_dir = Path(CONFIG["plans_dir"])
    previous_summary, prev_seq = _find_previous_output(plans_dir, JiraClient.issue_key(issue))

    prompt = get_jira_planning_prompt(
        issue_key=JiraClient.issue_key(issue),
        summary=JiraClient.summary(issue),
        issue_type=JiraClient.issue_type(issue),
        status=JiraClient.status(issue),
        priority=JiraClient.priority(issue),
        reporter=JiraClient.reporter(issue),
        assignee=JiraClient.assignee(issue),
        jira_url=client.issue_url(issue),
        created=JiraClient.created(issue),
        updated=JiraClient.updated(issue),
        description=JiraClient.description_text(issue),
        devstack_path=devstack,
        sequence=sequence,
        previous_plan_summary=previous_summary,
        previous_sequence=prev_seq if prev_seq else None,
        provider=_provider,
        save_path=save_path,
    )

    _ctx = load_context_section(CONFIG, "jira_triage")
    if _ctx:
        prompt = _ctx + "\n\n---\n\n" + prompt

    print(f"🤖 Producing implementation plan for {JiraClient.issue_key(issue)}...\n")

    model_client = create_model_client(CONFIG)
    result = await model_client.query(
        prompt=prompt,
        tools=["Bash", "Read", "Grep", "Glob"],
        on_progress=lambda text: print(f"  {text}"),
    )

    report_path = Path(save_path)
    _save_result(result, report_path)
    print(f"\n✅ Plan saved to: {report_path}")
    _post_jira_feedback(issue, report_path, CONFIG)


def _save_result(result, report_path: Path) -> None:
    """Write AI result to file, appending usage info."""
    usage_info = format_usage_info(
        usage_data=result.usage,
        cost_usd=result.cost_usd,
        model=result.model,
        duration_ms=result.duration_ms,
    )
    if not report_path.exists():
        content = result.text or ""
        if usage_info:
            content += "\n\n---\n\n" + usage_info
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(content, encoding="utf-8")
    else:
        existing = report_path.read_text(encoding="utf-8")
        if usage_info and "## Token Usage & Cost" not in existing:
            report_path.write_text(existing + "\n\n---\n\n" + usage_info, encoding="utf-8")


# ---------------------------------------------------------------------------
# Subprocess isolation (matches bug_triage_agent.py pattern)
# ---------------------------------------------------------------------------

async def _process_single(issue_data_file: str, action: str) -> None:
    """Entry point when called via subprocess for isolation."""
    with open(issue_data_file, encoding="utf-8") as f:
        data = json.load(f)
    issue = data["issue"]
    sequence = data["sequence"]
    save_path = data["save_path"]

    if action == "bug":
        await process_bug(issue, sequence, save_path)
    else:
        await process_plan(issue, sequence, save_path)


def _run_subprocess(issue: dict, sequence: int, save_path: str, action: str) -> bool:
    """Process one issue in a subprocess to get a fresh asyncio event loop."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="jira_issue_", delete=False, encoding="utf-8"
    ) as f:
        json.dump({"issue": issue, "sequence": sequence, "save_path": save_path}, f)
        tmp = f.name

    try:
        result = subprocess.run(
            [sys.executable, __file__, "--single-issue", tmp, "--action", action],
            cwd=str(Path(__file__).parent),
            check=False,
            timeout=1800,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"❌ Processing timed out for {JiraClient.issue_key(issue)}")
        return False
    finally:
        Path(tmp).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Main monitoring loop
# ---------------------------------------------------------------------------

async def monitor_and_process(max_issues: int = 5) -> None:
    """Fetch JIRA issues via JQL and triage/plan each one."""
    jira_cfg = CONFIG.get("jira", {})
    jql = jira_cfg.get("jql", "")
    if not jql:
        print("❌ No JQL configured. Set jira.jql in config.json.")
        return

    print(f"\n🔍 Running JQL: {jql}")
    forge = create_jira_client(CONFIG)
    try:
        issues = forge.fetch_issues(jql, max_results=50)
    except Exception as e:
        print(f"❌ Error fetching from JIRA: {e}")
        return

    print(f"✓ Found {len(issues)} issue(s)")

    cutoff = CONFIG.get("cutoff_date", "")
    tracking_file = Path(CONFIG["triage_tracking_file"])
    history = load_issue_history(tracking_file)

    triages_dir = Path(CONFIG["triages_dir"])
    plans_dir = Path(CONFIG["plans_dir"])
    triages_dir.mkdir(parents=True, exist_ok=True)
    plans_dir.mkdir(parents=True, exist_ok=True)

    processed = 0
    skipped_old = 0
    skipped_done = 0

    for issue in issues:
        if processed >= max_issues:
            break

        issue_key = JiraClient.issue_key(issue)
        issue_updated = JiraClient.updated(issue)
        issue_type = JiraClient.issue_type(issue)
        summary = JiraClient.summary(issue)

        # Cutoff date filter (based on creation date)
        if cutoff and JiraClient.created(issue) < cutoff:
            skipped_old += 1
            continue

        should, seq = should_process_issue(issue_key, issue_updated, history)
        if not should:
            skipped_done += 1
            continue

        if _is_bug(issue, CONFIG):
            output_dir = triages_dir
            action = "bug"
            label = "Bug"
        elif _is_plannable(issue, CONFIG):
            output_dir = plans_dir
            action = "plan"
            label = issue_type
        else:
            print(f"  ⏭️  {issue_key}: unknown type '{issue_type}', skipping")
            skipped_done += 1
            continue

        output_file = create_output_file_path(output_dir, issue_key, summary, seq)
        print(f"\n📌 [{label}] {issue_key}: {summary[:70]}")

        success = _run_subprocess(issue, seq, str(output_file), action)
        if success and output_file.exists():
            record_processed_issue(tracking_file, issue_key, issue_updated, seq,
                                   extra_data={"issue_type": issue_type, "action": action})
            notify_report(
                report_path=output_file,
                subject=f"JIRA {label}: {issue_key} — {summary[:50]}",
                summary=f"{'Triage' if action == 'bug' else 'Implementation plan'} "
                        f"complete for {issue_key}",
                agent_config=CONFIG,
                notifications_config=load_notifications_config(),
            )
            processed += 1
        else:
            print(f"   ⚠️  Processing did not produce output for {issue_key}")

    print(f"\n✅ Processed {processed} issue(s)")
    if skipped_old:
        print(f"⏭️  Skipped {skipped_old} created before cutoff date")
    if skipped_done:
        print(f"⏭️  Skipped {skipped_done} already up-to-date")


async def main() -> None:
    """Main entry point."""
    triages_dir = Path(CONFIG["triages_dir"])
    plans_dir = Path(CONFIG["plans_dir"])
    triages_dir.mkdir(parents=True, exist_ok=True)
    plans_dir.mkdir(parents=True, exist_ok=True)

    jira_cfg = CONFIG.get("jira", {})
    print("🚀 JIRA Triage Agent Starting...")
    print(f"🔗 JIRA: {jira_cfg.get('base_url', '(not configured)')}")
    print(f"📋 JQL:  {jira_cfg.get('jql', '(not configured)')}")
    print(f"📁 Triages: {triages_dir}")
    print(f"📁 Plans:   {plans_dir}")
    print(f"🤖 Model:   {CONFIG.get('model', 'claude-sonnet-4-6')}")
    print(f"📅 Cutoff:  {CONFIG.get('cutoff_date', '30 days ago')}")
    print("")

    await monitor_and_process(max_issues=CONFIG["max_issues_per_run"])


def cli_main() -> None:
    import argparse  # noqa: PLC0415 — used for formatter_class reference

    parser = HelpOnErrorParser(
        description="JIRA Triage Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process issues matching the configured JQL query (monitoring mode)
  %(prog)s

  # Triage or plan a specific issue by key
  %(prog)s --issue PROJ-123

  # Triage an issue by JIRA URL
  %(prog)s --url https://myco.atlassian.net/browse/PROJ-123

  # Re-process without the tracking-file confirmation prompt
  %(prog)s --issue PROJ-123 --skip-tracking

  # Save report to a custom directory
  %(prog)s --issue PROJ-123 --output-dir /tmp/jira-triages

  # Process without posting a comment to JIRA
  %(prog)s --issue PROJ-123 --no-post

  # Post the latest saved report as a JIRA comment (no re-triage)
  %(prog)s --issue PROJ-123 --post-only

  # Internal use: process a single issue from a JSON data file
  %(prog)s --single-issue /tmp/issue.json --action bug

  # Print a short summary of the triage/plan report after running
  %(prog)s --issue PROJ-123 --print-summary

  # Post only the summary as a JIRA comment (not the full report)
  %(prog)s --issue PROJ-123 --post-summary
        """,
    )
    add_jira_args(parser, CONFIG)
    add_post_args(parser)
    add_summary_args(parser)
    parser.add_argument("--single-issue", metavar="FILE",
                        help="Process a single issue from a JSON data file (internal subprocess mode).")
    parser.add_argument("--action", choices=["bug", "plan"], default="bug",
                        help="Action to perform when using --single-issue.")
    args = parser.parse_args()

    if args.single_issue:
        asyncio.run(_process_single(args.single_issue, args.action))
        return

    issue_key, _output_dir, skip_tracking = resolve_jira_target(args, CONFIG)
    _summary_prompt = Path(__file__).parent / "prompts" / "jira_triage_summary_prompt.txt"

    if args.no_post:
        CONFIG["feedback_enabled"] = False
        print("📵 External posting disabled (--no-post)\n")

    if args.post_only:
        if not issue_key:
            print("❌ --post-only requires --issue or --url", file=sys.stderr)
            sys.exit(1)
        triages_dir = Path(CONFIG["triages_dir"])
        plans_dir = Path(CONFIG["plans_dir"])
        report = find_latest_report(triages_dir, f"jira_{issue_key}_*.md") or \
            find_latest_report(plans_dir, f"jira_{issue_key}_*.md")
        if not report:
            print(f"❌ No report found for issue {issue_key} in {triages_dir} or {plans_dir}")
            sys.exit(1)
        print(f"📄 Using report: {report.name}")
        cached_summary = None
        if needs_summary(args, CONFIG):
            cached_summary = generate_summary(report, _summary_prompt, CONFIG)
            if cached_summary:
                print_summary(cached_summary, report)
        if not args.post_summary:
            jira = create_jira_client(CONFIG)
            content = report.read_text(encoding="utf-8")
            comment = build_feedback_comment(content, CONFIG.get("model", ""), max_chars=6000)
            ok = jira.add_comment(issue_key, comment, private=CONFIG.get("feedback_private", True))
            sys.exit(0 if ok else 1)
        else:
            if cached_summary:
                jira = create_jira_client(CONFIG)
                model_name = CONFIG.get("model", "claude-sonnet-4-6")
                comment = (
                    f"*AI triage summary by {model_name}*\n\n{cached_summary}\n\n"
                    "---\n*This summary was generated by an AI and may contain errors.*"
                )
                jira.add_comment(issue_key, comment,
                                 private=CONFIG.get("feedback_private", True))
        return

    if issue_key:
        history = load_issue_history(Path(CONFIG["issue_tracking_file"]))
        should, seq = should_process_issue(issue_key, None, history)
        if not should and not skip_tracking:
            if not confirm_reprocess("issue", issue_key):
                return
        jira = create_jira_client(CONFIG)
        try:
            issue = jira.get_issue(issue_key)
        except Exception as exc:
            print(f"❌ Could not fetch JIRA issue {issue_key}: {exc}")
            sys.exit(1)
        triages_dir = Path(CONFIG["triages_dir"])
        plans_dir = Path(CONFIG["plans_dir"])
        triages_dir.mkdir(parents=True, exist_ok=True)
        plans_dir.mkdir(parents=True, exist_ok=True)
        action = "plan" if not _is_bug(issue, CONFIG) else "bug"
        output_dir = triages_dir if action == "bug" else plans_dir
        summary_slug = JiraClient.summary(issue)[:50]
        save_path = str(create_output_file_path(output_dir, issue_key, summary_slug, seq))
        _run_subprocess(issue, seq, save_path, action)
    else:
        asyncio.run(main())

    if needs_summary(args, CONFIG):
        triages_dir = Path(CONFIG["triages_dir"])
        plans_dir = Path(CONFIG["plans_dir"])
        if issue_key:
            report = find_latest_report(triages_dir, f"jira_{issue_key}_*.md") or \
                find_latest_report(plans_dir, f"jira_{issue_key}_*.md")
        else:
            report = find_latest_report(triages_dir, "jira_*.md") or \
                find_latest_report(plans_dir, "jira_*.md")
        ai_summary = generate_summary(report, _summary_prompt, CONFIG) if report else None
        if ai_summary:
            print_summary(ai_summary, report)
            if args.post_summary and issue_key:
                jira = create_jira_client(CONFIG)
                model_name = CONFIG.get("model", "claude-sonnet-4-6")
                comment = (
                    f"*AI triage summary by {model_name}*\n\n{ai_summary}\n\n"
                    "---\n*This summary was generated by an AI and may contain errors.*"
                )
                jira.add_comment(issue_key, comment,
                                 private=CONFIG.get("feedback_private", True))
        else:
            print("ℹ️  No output file produced — summary not available.")


if __name__ == "__main__":
    cli_main()
