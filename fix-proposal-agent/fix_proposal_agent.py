#!/usr/bin/env python3
"""
Fix Proposal Agent

Reads triage and reproduction reports for REPRODUCED bugs and uses an AI
model to generate a targeted code fix with a structured risk rating.

The developer receives a proposal document and can:
  - Accept the AI fix (apply the embedded patch)
  - Use Claude Code (paste the context packet)
  - Request changes (write feedback to fix_proposal_{N}_feedback.txt)
  - Abandon (mark the Launchpad bug ai-fix-rejected)
"""
import asyncio
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))

from agents_lib import (
    create_model_client,
    format_usage_info,
    load_agent_config,
    apply_cutoff_date,
    expand_config_paths,
    expand_context_config,
    load_context_section,
    generate_learning,
    save_learning,
    notify_report,
    load_notifications_config,
    post_report_to_launchpad,
    find_latest_report,
)
from launchpad_feedback import (
    get_gerrit_comments_since,
    get_launchpad_comments_since,
    post_proposal_to_launchpad,
    push_gerrit_wip_draft,
)
from prompts import get_fix_proposal_prompt
from proposal_tracker import (
    create_proposal_filename,
    load_proposal_history,
    read_local_feedback,
    record_proposal,
    should_propose_fix,
)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_CONFIG_DIR = Path(__file__).parent

_DEFAULTS = {
    "model": "claude-sonnet-4-6",
    "model_provider": "anthropic",
    "triage_reports_dir": "~/octavia_bug_triages",
    "reproduction_reports_dir": "~/octavia_bug_reproductions",
    "proposals_output_dir": "~/octavia_fix_proposals",
    "proposal_tracking_file": "~/.octavia_fix_proposals.json",
    "devstack_path": "/opt/stack",
    "launchpad_project": "octavia",
    "max_proposals_per_run": 2,
    "cutoff_date": None,
    "gerrit": {
        "push_wip_draft": False,
        "base_url": "https://review.opendev.org",
    },
    "feedback": {
        "post_to_launchpad": False,
        "read_launchpad_comments": False,
        "read_gerrit_comments": False,
    },
    "notifications": {"enabled": False},
}

_ENV_OVERRIDES = {
    "PROPOSALS_OUTPUT_DIR": "proposals_output_dir",
    "TRIAGE_REPORTS_DIR": "triage_reports_dir",
    "REPRODUCTION_REPORTS_DIR": "reproduction_reports_dir",
    "DEVSTACK_PATH": "devstack_path",
    "MAX_PROPOSALS": "max_proposals_per_run",
    "CUTOFF_DATE": "cutoff_date",
    "CLAUDE_MODEL": "model",
}

_PATH_KEYS = [
    "triage_reports_dir",
    "reproduction_reports_dir",
    "proposals_output_dir",
    "proposal_tracking_file",
    "devstack_path",
]


def load_config() -> dict:
    config = load_agent_config(_CONFIG_DIR, _ENV_OVERRIDES, _DEFAULTS)
    config = apply_cutoff_date(config, "cutoff_date", default_days=30)
    config = expand_config_paths(config, _PATH_KEYS)
    config = expand_context_config(config)
    return config


# ---------------------------------------------------------------------------
# Helper: find reproduction report for a bug
# ---------------------------------------------------------------------------

def find_reproduction_report(bug_number: str, repro_dir: Path) -> Optional[Path]:
    """Return the most recent REPRODUCED reproduction report for a bug."""
    pattern = f"reproduction_{bug_number}_*_*.md"
    candidates = sorted(repro_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            content = path.read_text(encoding="utf-8")
            if "REPRODUCED" in content and "NOT_REPRODUCED" not in content[:500]:
                return path
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Helper: extract triage timestamp from filename
# ---------------------------------------------------------------------------

def get_triage_timestamp(triage_path: Path) -> str:
    """Extract the ISO-style timestamp from a triage filename."""
    parts = triage_path.stem.split("_")
    if len(parts) >= 2:
        date_part = parts[-3] if len(parts) >= 3 else parts[-2]
        time_part = parts[-2] if len(parts) >= 3 else parts[-1]
        try:
            int(parts[-1])  # confirm last part is a sequence number
            return f"{date_part}T{time_part}"
        except (ValueError, IndexError):
            pass
    return triage_path.stat().st_mtime.__class__.__name__


# ---------------------------------------------------------------------------
# Helper: extract bug number and title from triage filename
# ---------------------------------------------------------------------------

def parse_triage_filename(triage_path: Path) -> tuple[str, str]:
    """Return (bug_number, bug_title_slug) from a triage filename."""
    parts = triage_path.stem.split("_")
    # Format: bug_{number}_{title_slug}_{YYYYMMDD}_{HHMMSS}_{sequence}
    if len(parts) < 5 or parts[0] != "bug":
        return ("", "")
    bug_number = parts[1]
    # Title slug: everything between number and the timestamp (last 3 parts)
    title_parts = parts[2:-3] if len(parts) > 5 else parts[2:-2]
    return bug_number, "_".join(title_parts)


# ---------------------------------------------------------------------------
# Helper: extract risk rating from proposal file
# ---------------------------------------------------------------------------

def extract_risk_rating(proposal_file: Path) -> str:
    """Extract the overall risk rating from a written proposal document."""
    try:
        content = proposal_file.read_text(encoding="utf-8")
        m = re.search(r"\*\*Risk Rating\*\*:\s*(LOW|MEDIUM|HIGH)", content)
        if m:
            return m.group(1)
    except Exception:
        pass
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Core: generate one fix proposal
# ---------------------------------------------------------------------------

async def propose_fix(
    bug_number: str,
    bug_title: str,
    triage_file: Path,
    repro_file: Optional[Path],
    sequence: int,
    feedback: Optional[str],
    config: dict,
) -> Optional[Path]:
    """Run the AI agent to generate a fix proposal.

    Returns the path to the written proposal file, or None on failure.
    """
    print(f"\n{'='*80}")
    print(f"🔧 Generating Fix Proposal for Bug #{bug_number}")
    if sequence > 1:
        print(f"   Revision #{sequence} (developer feedback incorporated)")
    print(f"{'='*80}\n")

    proposals_dir = Path(config["proposals_output_dir"])
    proposals_dir.mkdir(parents=True, exist_ok=True)

    # Infer repo path from devstack_path + project name (octavia)
    repo_path = str(Path(config["devstack_path"]) / config.get("launchpad_project", "octavia"))

    prompt = get_fix_proposal_prompt(
        bug_number=bug_number,
        bug_title=bug_title,
        triage_file=triage_file,
        repro_file=repro_file,
        repo_path=repo_path,
        proposals_output_dir=str(proposals_dir),
        sequence=sequence,
        feedback=feedback,
        provider=config.get("model_provider", "anthropic"),
    )

    # Prepend cross-run context
    _ctx = load_context_section(config, "fix_proposal")
    if _ctx:
        prompt = _ctx + "\n\n---\n\n" + prompt

    print("🤖 Starting fix proposal generation...\n")

    client = create_model_client(config)
    try:
        result = await client.query(
            prompt=prompt,
            tools=["Bash", "Read", "Write", "Grep", "Glob"],
            on_progress=lambda text: print(f"  {text}"),
        )
    except Exception as exc:
        print(f"\n❌ Error during proposal generation: {exc}")
        import traceback
        traceback.print_exc()
        return None

    print(f"\n{'='*80}")
    print("✅ Proposal generation complete!")
    if result.usage:
        print(format_usage_info(result.usage, result.cost_usd, result.model, result.duration_ms))
    print(f"{'='*80}")

    # Locate the written proposal file
    pattern = f"fix_proposal_{bug_number}_*_{sequence}.md"
    candidates = [p for p in proposals_dir.glob(pattern)
                  if not p.stem.endswith("_context")]
    if not candidates:
        # Fallback: any fix_proposal_{bug_number}_* written in this run
        candidates = [p for p in proposals_dir.glob(f"fix_proposal_{bug_number}_*.md")
                      if not p.stem.endswith("_context")]
    if not candidates:
        print(f"\n❌ Proposal file not found in {proposals_dir}")
        if result.text:
            # AI returned text but didn't write the file — save manually
            fallback = create_proposal_filename(proposals_dir, bug_number, bug_title, sequence)
            fallback.write_text(result.text, encoding="utf-8")
            print(f"   Saved manually to: {fallback.name}")
            return fallback
        return None

    proposal_file = max(candidates, key=lambda p: p.stat().st_mtime)
    print(f"\n✓ Proposal saved to: {proposal_file.name}")
    return proposal_file


# ---------------------------------------------------------------------------
# Core: handle Gerrit WIP push after proposal is written
# ---------------------------------------------------------------------------

def handle_gerrit_push(
    proposal_file: Path,
    bug_number: str,
    bug_title: str,
    config: dict,
) -> Optional[str]:
    """Push a WIP draft to Gerrit if configured. Returns change URL or None."""
    gerrit_cfg = config.get("gerrit", {})
    if not gerrit_cfg.get("push_wip_draft"):
        return None

    repo_path = Path(config["devstack_path"]) / config.get("launchpad_project", "octavia")
    if not repo_path.exists():
        print(f"⚠️  Cannot push to Gerrit — repo not found at {repo_path}")
        return None

    # Extract the patch from the proposal document
    content = proposal_file.read_text(encoding="utf-8")
    patch_match = re.search(r"```diff\n(.*?)```", content, re.DOTALL)
    if not patch_match:
        print("⚠️  Cannot push to Gerrit — no diff block found in proposal")
        return None

    patch_content = patch_match.group(1)
    gerrit_remote = gerrit_cfg.get("remote_name", "gerrit")
    print(f"\n📤 Pushing WIP draft to Gerrit (remote: {gerrit_remote})...")
    return push_gerrit_wip_draft(
        repo_path=repo_path,
        patch_content=patch_content,
        bug_number=bug_number,
        bug_title=bug_title,
        gerrit_remote=gerrit_remote,
    )


# ---------------------------------------------------------------------------
# Core: gather feedback from all configured sources
# ---------------------------------------------------------------------------

def collect_feedback(
    bug_number: str,
    record: dict,
    proposals_dir: Path,
    config: dict,
) -> Optional[str]:
    """Collect developer feedback from all configured sources.

    Returns combined feedback text, or None if no feedback found.
    """
    feedback_parts = []
    feedback_cfg = config.get("feedback", {})

    # 1. Local feedback file (always checked)
    local = read_local_feedback(bug_number, proposals_dir)
    if local:
        feedback_parts.append(f"[Local feedback file]\n{local}")

    # 2. Launchpad comments (configurable)
    if feedback_cfg.get("read_launchpad_comments"):
        since = record.get("last_processed", "")
        lp_comments = get_launchpad_comments_since(bug_number, since)
        if lp_comments:
            joined = "\n\n".join(c["content"] for c in lp_comments)
            feedback_parts.append(f"[Launchpad comments]\n{joined}")

    # 3. Gerrit review comments (configurable)
    if feedback_cfg.get("read_gerrit_comments") and record.get("gerrit_change_id"):
        from agents_lib import create_forge_client
        forge = create_forge_client(config)
        since = record.get("last_processed", "")
        gerrit_comments = get_gerrit_comments_since(
            record["gerrit_change_id"], since, forge
        )
        if gerrit_comments:
            joined = "\n\n".join(c["message"] for c in gerrit_comments)
            feedback_parts.append(f"[Gerrit review comments]\n{joined}")

    if not feedback_parts:
        return None
    return "\n\n---\n\n".join(feedback_parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main() -> None:
    print("\n" + "="*80)
    print("Fix Proposal Agent")
    print("="*80 + "\n")

    config = load_config()

    triage_dir = Path(config["triage_reports_dir"])
    repro_dir = Path(config["reproduction_reports_dir"])
    proposals_dir = Path(config["proposals_output_dir"])
    tracking_file = Path(config["proposal_tracking_file"])
    max_proposals = int(config.get("max_proposals_per_run", 2))
    cutoff_date = config.get("cutoff_date", "")

    print("Configuration:")
    print(f"  Triage reports:      {triage_dir}")
    print(f"  Reproduction reports:{repro_dir}")
    print(f"  Proposals output:    {proposals_dir}")
    print(f"  Cutoff date:         {cutoff_date}")
    print(f"  Max proposals/run:   {max_proposals}")
    print()

    proposals_dir.mkdir(parents=True, exist_ok=True)
    history = load_proposal_history(tracking_file)

    if not triage_dir.exists():
        print(f"❌ Triage reports directory not found: {triage_dir}")
        return

    # -----------------------------------------------------------------------
    # Phase 1: generate new proposals for REPRODUCED bugs
    # -----------------------------------------------------------------------

    triage_files = sorted(
        triage_dir.glob("bug_*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not triage_files:
        print("No triage reports found.")
    else:
        print(f"📋 Found {len(triage_files)} triage report(s)\n")

    proposed_count = 0
    notif_config = load_notifications_config()

    for triage_file in triage_files:
        if proposed_count >= max_proposals:
            break

        bug_number, bug_title_slug = parse_triage_filename(triage_file)
        if not bug_number:
            continue

        # Apply cutoff date filter
        if cutoff_date:
            parts = triage_file.stem.split("_")
            # date part is parts[-3] in format YYYYMMDD
            if len(parts) >= 3:
                try:
                    file_date = parts[-3]  # YYYYMMDD
                    if file_date < cutoff_date.replace("-", ""):
                        continue
                except (IndexError, ValueError):
                    pass

        # Find reproduction report — only propose for REPRODUCED bugs
        repro_file = find_reproduction_report(bug_number, repro_dir) if repro_dir.exists() else None
        if not repro_file:
            continue  # Skip unless bug has been confirmed reproduced

        triage_timestamp = get_triage_timestamp(triage_file)
        should, sequence = should_propose_fix(bug_number, triage_timestamp, history)
        if not should:
            continue

        bug_title = bug_title_slug.replace("_", " ")
        print(f"\n📌 Bug #{bug_number}: {bug_title[:60]}")

        proposal_file = await propose_fix(
            bug_number=bug_number,
            bug_title=bug_title,
            triage_file=triage_file,
            repro_file=repro_file,
            sequence=sequence,
            feedback=None,
            config=config,
        )

        if not proposal_file:
            print(f"⚠️  Proposal generation failed for bug #{bug_number}")
            continue

        risk_rating = extract_risk_rating(proposal_file)

        # Optional Gerrit WIP push
        gerrit_change_id = handle_gerrit_push(
            proposal_file, bug_number, bug_title, config
        )

        # Record in tracking
        record_proposal(
            tracking_file,
            bug_number,
            triage_timestamp,
            sequence,
            proposal_file,
            status="proposed",
            gerrit_change_id=gerrit_change_id,
        )
        history = load_proposal_history(tracking_file)

        # Post to Launchpad (optional)
        post_proposal_to_launchpad(bug_number, proposal_file, risk_rating, config)

        # Notify
        notify_report(
            report_path=proposal_file,
            subject=f"Fix Proposal: Bug #{bug_number} — Risk: {risk_rating}",
            summary=f"{bug_title[:60]} | Sequence {sequence}",
            agent_config=config,
            notifications_config=notif_config,
        )

        proposed_count += 1
        print(f"\n✅ Proposal complete for bug #{bug_number} (risk: {risk_rating})")

        # Save learning when this is a revised proposal (sequence > 1) — notable
        if sequence > 1:
            _summary = (
                f"Revised fix proposal (sequence {sequence}) for bug #{bug_number} — {bug_title[:60]}. "
                f"Risk: {risk_rating}."
            )
            _learning = await generate_learning(_summary, "Fix Proposal Agent", config)
            if _learning:
                save_learning(config["context"]["agent_context_file"], _learning, "Fix Proposal Agent")

    # -----------------------------------------------------------------------
    # Phase 2: refinement loop — process developer feedback
    # -----------------------------------------------------------------------

    print("\n🔄 Checking for developer feedback on open proposals...")
    refined_count = 0

    for fix_key, record in list(history.items()):
        if record.get("status") not in ("proposed", None):
            continue
        if proposed_count + refined_count >= max_proposals:
            break

        bug_number = fix_key.removeprefix("fix_")
        feedback = collect_feedback(bug_number, record, proposals_dir, config)
        if not feedback:
            continue

        # Find the triage file for context
        matching_triages = list(triage_dir.glob(f"bug_{bug_number}_*.md"))
        if not matching_triages:
            continue
        triage_file = max(matching_triages, key=lambda p: p.stat().st_mtime)
        _, bug_title_slug = parse_triage_filename(triage_file)
        bug_title = bug_title_slug.replace("_", " ")
        triage_timestamp = get_triage_timestamp(triage_file)
        repro_file = find_reproduction_report(bug_number, repro_dir) if repro_dir.exists() else None
        next_sequence = record.get("sequence", 1) + 1

        print(f"\n💬 Feedback detected for bug #{bug_number} — generating revision #{next_sequence}")

        proposal_file = await propose_fix(
            bug_number=bug_number,
            bug_title=bug_title,
            triage_file=triage_file,
            repro_file=repro_file,
            sequence=next_sequence,
            feedback=feedback,
            config=config,
        )

        if not proposal_file:
            continue

        risk_rating = extract_risk_rating(proposal_file)
        gerrit_change_id = handle_gerrit_push(
            proposal_file, bug_number, bug_title, config
        )
        record_proposal(
            tracking_file,
            bug_number,
            triage_timestamp,
            next_sequence,
            proposal_file,
            status="proposed",
            gerrit_change_id=gerrit_change_id,
        )
        history = load_proposal_history(tracking_file)

        post_proposal_to_launchpad(bug_number, proposal_file, risk_rating, config)
        notify_report(
            report_path=proposal_file,
            subject=f"Fix Proposal (Revised): Bug #{bug_number} — Risk: {risk_rating}",
            summary=f"{bug_title[:60]} | Revision {next_sequence}",
            agent_config=config,
            notifications_config=notif_config,
        )

        refined_count += 1

    if refined_count == 0:
        print("   No feedback found — nothing to refine")

    # -----------------------------------------------------------------------
    # Summary
    # -----------------------------------------------------------------------

    print("\n" + "="*80)
    print("✅ Fix proposal cycle complete!")
    print(f"   New proposals:   {proposed_count}")
    print(f"   Refined:         {refined_count}")
    if proposals_dir.exists():
        print(f"   Output dir:      {proposals_dir}")
    print("="*80)


def cli_main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description='Octavia Fix Proposal Agent')
    parser.add_argument('--bug', metavar='N', type=int,
                        help='Bug number for --post-only mode')
    parser.add_argument('--post-only', action='store_true',
                        help='Skip proposal generation; find the latest saved proposal for --bug N and post it to Launchpad.')
    args = parser.parse_args()

    if args.post_only:
        if not args.bug:
            import sys
            print("❌ --post-only requires --bug N", file=sys.stderr)
            sys.exit(1)
        bug_id = str(args.bug)
        config = load_config()
        proposals_dir = Path(config["proposals_output_dir"])
        # The glob excludes _context files by requiring a digit sequence before .md
        # (filenames end in _<sequence>.md, context files end in _context.md)
        candidates = sorted(
            p for p in proposals_dir.glob(f"fix_proposal_{bug_id}_*.md")
            if not p.stem.endswith("_context")
        )
        report = candidates[-1] if candidates else None
        if not report:
            import sys
            print(f"❌ No proposal report found for bug {bug_id} in {proposals_dir}")
            sys.exit(1)
        print(f"📄 Using report: {report.name}")
        subject = "AI Fix Proposal (automated, may contain errors)"
        ok = post_report_to_launchpad(bug_id, subject, report, config, max_chars=5000)
        import sys
        sys.exit(0 if ok else 1)

    asyncio.run(main())


if __name__ == "__main__":
    cli_main()
