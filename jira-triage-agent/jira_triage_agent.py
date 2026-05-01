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
from agents_lib import create_model_client
from agents_lib import format_usage_info
from agents_lib import load_notifications_config
from agents_lib import notify_report

CONFIG = load_config()


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
    import argparse
    parser = argparse.ArgumentParser(description="JIRA Triage Agent")
    parser.add_argument("--single-issue", metavar="FILE",
                        help="Process a single issue from a JSON data file (internal)")
    parser.add_argument("--action", choices=["bug", "plan"], default="bug",
                        help="Action to perform when using --single-issue")
    args = parser.parse_args()

    if args.single_issue:
        asyncio.run(_process_single(args.single_issue, args.action))
    else:
        asyncio.run(main())


if __name__ == "__main__":
    cli_main()
