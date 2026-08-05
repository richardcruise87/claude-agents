#!/usr/bin/env python3
"""
Backport Review Agent

Reviews open backport changes in Gerrit on a schedule, assessing whether
each backport is appropriate, a clean cherry-pick, and policy-compliant.

Reuses code-review-agent infrastructure (forge client, tracking, feedback)
with a backport-specific prompt that adds:
  - Original upstream change lookup and comparison
  - Backport-Candidate label verification
  - Branch appropriateness checking
  - Backporting rules application

Usage:
    octavia-backport-review
    octavia-backport-review --change 923456   # review a specific backport change
"""
import argparse
import asyncio
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import NamedTuple, Optional

sys.path.insert(0, str(Path(__file__).parent))
# Also expose the code-review-agent config and prompt builder
_CODE_REVIEW_DIR = str(Path(__file__).parent.parent / "code-review-agent")
if _CODE_REVIEW_DIR not in sys.path:
    sys.path.insert(0, _CODE_REVIEW_DIR)

from agents_lib import (
    create_forge_client,
    create_model_client,
    load_agent_config,
    expand_config_paths,
    expand_context_config,
    format_usage_info,
    load_context_section,
    load_review_history,
    should_review_change,
    record_review,
    load_previous_review_context,
    notify_report,
    load_notifications_config,
    HelpOnErrorParser,
    add_change_args,
    add_summary_args,
    resolve_change_target,
    generate_summary,
    print_summary,
    needs_summary,
)

from prompts import get_backport_review_prompt

_CONFIG_DIR = Path(__file__).parent

_DEFAULTS = {
    "model": "claude-sonnet-4-6",
    "monitored_repos": ["openstack/octavia"],
    "source_branch": "master",
    "backport_branches": ["stable/*"],
    "backport_label": "Backport-Candidate",
    "backport_topic_prefix": "backport",
    "repo_path": "/opt/stack/octavia",
    "lookback_days": 7,
    "output_dir": "~/octavia_backport_reviews",
    "backport_tracking_file": "~/.octavia_backports.json",
    "max_reviews_per_cycle": 3,
    "forge": {
        "type": "gerrit",
        "base_url": "https://review.opendev.org",
    },
    "notifications": {"enabled": False},
}

_ENV_OVERRIDES = {
    "OUTPUT_DIR": "output_dir",
    "BACKPORT_REPO": "repo_path",
    "LOOKBACK_DAYS": "lookback_days",
    "MAX_REVIEWS": "max_reviews_per_cycle",
    "CLAUDE_MODEL": "model",
}

_PATH_KEYS = [
    "repo_path",
    "output_dir",
    "backport_tracking_file",
    ("forge", "repo_base_path"),
]


def load_config() -> dict:
    """Load backport agent config and merge with code-review-agent forge settings."""
    # Load the backport agent's own config
    config = load_agent_config(_CONFIG_DIR, _ENV_OVERRIDES, _DEFAULTS)
    config = expand_config_paths(config, _PATH_KEYS)
    config = expand_context_config(config)

    # Pull forge credentials from code-review-agent config if available.
    # Import inside the try block so a missing code-review-agent installation
    # is handled gracefully rather than crashing at module import time.
    try:
        from config import load_config as _load_cr_config  # noqa: PLC0415
        cr_config = _load_cr_config()
        for key in ("forge_type", "forge_base_url", "forge_token_env",
                    "gerrit_base_url", "reviewed_changes_file", "repo_base_path"):
            if key not in config and key in cr_config:
                config[key] = cr_config[key]
        # Use code-review-agent's reviewed_changes_file for tracking if not set
        if "reviewed_changes_file" not in config:
            config["reviewed_changes_file"] = str(
                Path("~/.octavia_backport_reviews.json").expanduser()
            )
    except Exception:  # pylint: disable=broad-except
        config.setdefault("gerrit_base_url", "https://review.opendev.org")
        config.setdefault("reviewed_changes_file",
                          str(Path("~/.octavia_backport_reviews.json").expanduser()))

    return config


# ---------------------------------------------------------------------------
# Backport section builders (same pattern as code-review-agent)
# ---------------------------------------------------------------------------

class _BackportSections(NamedTuple):
    branches_section: str
    rules_section: str
    triage_dir: str


def _build_backport_sections(config: dict) -> _BackportSections:
    """Build backport-related prompt sections from config."""
    branches = config.get("backport_branches", [])
    if branches:
        branches_section = (
            "The following branch patterns are configured as backport targets:\n"
            + "\n".join(f"- `{b}`" for b in branches)
        )
    else:
        branches_section = "No backport target branches are configured."

    rules_section = ""
    rules_file = config.get("backport_rules_file")
    if rules_file:
        rules_path = Path(str(rules_file)).expanduser()
        if rules_path.exists():
            rules_section = rules_path.read_text(encoding="utf-8")
        else:
            print(f"⚠️  Backport rules file not found: {rules_path}")

    triage_dir = str(
        Path(config.get("triages_output_dir", "~/octavia_bug_triages")).expanduser()
    )
    return _BackportSections(branches_section, rules_section, triage_dir)


# ---------------------------------------------------------------------------
# Review a single backport change
# ---------------------------------------------------------------------------

async def review_backport_change(
    change_url_or_number: str,
    config: dict,
    requested_patchset: Optional[int] = None,
) -> Optional[Path]:
    """Review a single backport change and save a report."""
    forge = create_forge_client(config)
    gerrit_base_url = config.get("gerrit_base_url", "https://review.opendev.org")
    repo_base_path = Path(config.get("repo_base_path", config.get("repo_path", "/opt/stack")))
    output_dir = Path(config["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    tracking_file = Path(config["reviewed_changes_file"])

    # Resolve the change
    repo_hint = config.get("monitored_repos", [None])[0]
    if re.match(r"^https?://", change_url_or_number):
        change = forge.get_change_from_url(change_url_or_number)
    else:
        change = forge.get_change(change_url_or_number.strip(), repo_hint)

    repo_name = change.repo_name
    repo_path = repo_base_path / repo_name.split("/")[-1]

    # Determine patchset
    current_patchset = change.patchset
    patchset_ref = change.git_fetch_ref
    if change.forge_type == "gerrit" and requested_patchset:
        current_patchset = int(requested_patchset)
        last2 = str(change.change_id)[-2:].zfill(2)
        patchset_ref = f"refs/changes/{last2}/{change.change_id}/{current_patchset}"

    # Tracking — detect if we already reviewed this patchset
    history = load_review_history(tracking_file)
    should, sequence = should_review_change(change, history)
    if not should:
        print(f"   ⏭️  #{change.change_id} — already reviewed at current patchset")
        return None

    # Previous review context
    previous_review_content, previous_record = load_previous_review_context(
        output_dir, change, history
    )
    previous_patchset = previous_record.patchset if previous_record else None
    previous_review_section = ""
    if previous_review_content and previous_patchset:
        previous_review_section = (
            f"\n## Previous Backport Review Context\n\n"
            f"Patchset {previous_patchset} was reviewed before.\n\n"
            f"```\n{previous_review_content[:2000]}\n```\n\n"
            f"Focus on what changed since PS {previous_patchset}.\n"
        )

    # Review file
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    repo_slug = repo_name.replace("/", "_")
    review_file = output_dir / f"backport_review_{repo_slug}_{change.change_id}_ps{current_patchset}_{ts}.md"

    # Build prompt
    _bp = _build_backport_sections(config)
    _provider = config.get("model_provider", "anthropic")
    prompt = get_backport_review_prompt(
        repo_name=repo_name,
        change_number=change.change_id,
        current_patchset=current_patchset,
        gerrit_base_url=gerrit_base_url,
        repo_path=repo_path,
        patchset_ref=patchset_ref,
        target_branch=change.branch,
        source_branch=config.get("source_branch", "master"),
        specific_patchset_note="",
        previous_review_section=previous_review_section,
        previous_patchset=previous_patchset,
        provider=_provider,
        save_path=str(review_file),
        forge_type=change.forge_type,
        forge_url=change.forge_url,
        sequence=sequence,
        head_sha=change.head_sha,
        backport_branches_section=_bp.branches_section,
        backport_rules_section=_bp.rules_section,
        triage_reports_dir=_bp.triage_dir,
    )

    # Prepend context learnings
    _ctx = load_context_section(config, "backport")
    if _ctx:
        prompt = _ctx + "\n\n---\n\n" + prompt

    print(f"\n🔍 Reviewing backport #{change.change_id}: {change.title[:60]}")
    print(f"   Target branch: {change.branch}")

    client = create_model_client(config)
    _result = await client.query(
        prompt=prompt,
        tools=["Bash", "Read", "Write", "Grep", "Glob"],
        on_progress=lambda text: print(f"  {text}"),
    )
    review_result = _result.text

    if review_result:
        review_file.write_text(review_result, encoding="utf-8")

    if _result.usage:
        usage_str = format_usage_info(
            _result.usage, _result.cost_usd, _result.model, _result.duration_ms
        )
        if review_file.exists():
            existing = review_file.read_text(encoding="utf-8")
            if "## Token Usage" not in existing:
                review_file.write_text(existing + "\n\n---\n\n" + usage_str, encoding="utf-8")

    record_review(tracking_file, change, sequence, review_file)
    print(f"   ✅ Backport review saved: {review_file.name}")

    notify_report(
        report_path=review_file,
        subject=f"Backport Review: {repo_name} #{change.change_id} PS{current_patchset}",
        summary=f"Backport review for {change.title[:60]}",
        agent_config=config,
        notifications_config=load_notifications_config(),
    )

    return review_file


# ---------------------------------------------------------------------------
# Main monitoring loop
# ---------------------------------------------------------------------------

async def main(change_url: Optional[str] = None) -> None:
    config = load_config()
    forge = create_forge_client(config)

    print(f"\n{'='*80}")
    print("Backport Review Agent")
    print(f"{'='*80}")
    print(f"  Output dir: {config['output_dir']}")
    print(f"  Model:      {config.get('model', 'claude-sonnet-4-6')}")
    print()

    if change_url:
        # Manual mode — review a single specific change
        await review_backport_change(change_url, config)
        return

    # Monitoring mode — find open backport changes
    monitored_repos = config.get("monitored_repos", [])
    topic_prefix = config.get("backport_topic_prefix", "backport")
    max_per_cycle = int(config.get("max_reviews_per_cycle", 3))
    reviewed = 0

    for repo in monitored_repos:
        if reviewed >= max_per_cycle:
            break

        print(f"\n🔍 Scanning {repo} for open backport changes...")

        # Query for open changes with the backport topic on stable/* branches
        try:
            # Gerrit query: open changes on stable/* branches with backport topic
            open_changes = forge.list_changes(
                repo, status="open",
                label=None,  # no label filter — rely on topic
                max_results=50,
            )
        except Exception as exc:
            print(f"   ❌ Could not query Gerrit: {exc}")
            continue

        # Filter to changes that look like backports
        backport_changes = [
            c for c in open_changes
            if (c.branch.startswith("stable/") or c.branch.startswith("unmaintained/"))
            and (
                f"{topic_prefix}-" in (c.description or "").lower()
                or c.title.lower().startswith("backport")
                or "cherry picked from" in (c.description or "").lower()
            )
        ]
        print(f"   Found {len(backport_changes)} open backport change(s)")

        history = load_review_history(Path(config["reviewed_changes_file"]))
        for change in sorted(backport_changes, key=lambda c: c.updated_at, reverse=True):
            if reviewed >= max_per_cycle:
                break
            should, _ = should_review_change(change, history)
            if not should:
                continue
            result = await review_backport_change(change.change_id, config)
            if result:
                reviewed += 1

    print(f"\n{'='*80}")
    print(f"✅ Backport review cycle complete — {reviewed} review(s) saved")
    print(f"{'='*80}")


def cli_main() -> None:
    config = load_config()
    parser = HelpOnErrorParser(
        description="Octavia Backport Review Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan all configured repos for open backport changes (monitoring mode)
  %(prog)s

  # Review a specific backport change by number
  %(prog)s --change 923456

  # Review a specific backport change by Gerrit URL
  %(prog)s --url https://review.opendev.org/c/openstack/octavia/+/923456

  # Save review to a custom directory
  %(prog)s --change 923456 --output-dir /tmp/backport-reviews

  # Print a short summary of the review after running
  %(prog)s --change 923456 --print-summary
        """,
    )
    add_change_args(parser, config)
    add_summary_args(parser)
    args = parser.parse_args()

    change_ref, _patchset, _output_dir, _skip = resolve_change_target(args, config)
    _summary_prompt = Path(__file__).parent / "prompts" / "backport_review_summary_prompt.txt"

    if args.post_summary:
        print(
            "❌ --post-summary is not supported for the backport review agent — "
            "no forge posting is configured. Use --print-summary to display the summary locally.",
            file=sys.stderr,
        )
        sys.exit(1)

    asyncio.run(main(change_url=change_ref))

    if needs_summary(args, config):
        from agents_lib import find_latest_report as _flr  # noqa: PLC0415
        output_dir = Path(config["output_dir"])
        report = _flr(output_dir, "review_*.md")
        summary = generate_summary(report, _summary_prompt, config) if report else None
        if summary:
            print_summary(summary, report)
        else:
            print("ℹ️  No output file produced — summary not available.")


if __name__ == "__main__":
    cli_main()
