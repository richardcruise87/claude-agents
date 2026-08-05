#!/usr/bin/env python3
"""
Backport Monitor

Runs daily. Queries Gerrit for recently merged changes that have the
Backport-Candidate label set, then attempts a clean cherry-pick to each
configured stable branch. Conflicts are skipped and logged.

Usage:
    octavia-backport-monitor
    octavia-backport-monitor --dry-run     # log what would happen, no git operations
    octavia-backport-monitor --repo openstack/octavia --lookback 14
"""
import argparse
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agents_lib import (
    create_forge_client,
    load_agent_config,
    expand_config_paths,
    expand_context_config,
    HelpOnErrorParser,
)
from backport_tracker import (
    record_backport,
    is_already_processed,
)

_CONFIG_DIR = Path(__file__).parent

_DEFAULTS = {
    "model": "claude-sonnet-4-6",
    "monitored_repos": ["openstack/octavia"],
    "source_branch": "master",
    "backport_branches": ["stable/*"],
    "backport_label": "Backport-Candidate",
    "backport_topic_prefix": "backport",
    "repo_path": "/opt/stack/octavia",
    "gerrit_remote": "gerrit",
    "lookback_days": 7,
    "backport_tracking_file": "~/.octavia_backports.json",
    "output_dir": "~/octavia_backport_reviews",
    "forge": {
        "type": "gerrit",
        "base_url": "https://review.opendev.org",
    },
    "notifications": {"enabled": False},
}

_ENV_OVERRIDES = {
    "BACKPORT_REPO": "repo_path",
    "LOOKBACK_DAYS": "lookback_days",
    "GERRIT_REMOTE": "gerrit_remote",
    "CLAUDE_MODEL": "model",
}

_PATH_KEYS = [
    "repo_path",
    "backport_tracking_file",
    "output_dir",
]


def load_config() -> dict:
    config = load_agent_config(_CONFIG_DIR, _ENV_OVERRIDES, _DEFAULTS)
    config = expand_config_paths(config, _PATH_KEYS)
    config = expand_context_config(config)
    return config


# ---------------------------------------------------------------------------
# Branch expansion
# ---------------------------------------------------------------------------

def expand_branch_patterns(patterns: list, repo_path: Path) -> list:
    """Expand wildcard patterns like stable/* to real remote branches."""
    branches = []
    for pattern in patterns:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "branch", "-r", "--list", f"origin/{pattern}"],
            capture_output=True, text=True, check=False,
        )
        for line in result.stdout.splitlines():
            branch = line.strip().removeprefix("origin/").strip()
            if branch and branch not in branches:
                branches.append(branch)
    return branches


# ---------------------------------------------------------------------------
# Cherry-pick logic
# ---------------------------------------------------------------------------

def _git(repo_path: Path, *args: str, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo_path)] + list(args),
        capture_output=True, text=True, check=check,
    )


def _get_current_branch(repo_path: Path) -> str:
    result = _git(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
    return result.stdout.strip() or "HEAD"


def _get_change_id_from_commit(repo_path: Path, sha: str) -> str:
    """Extract the Gerrit Change-Id from a commit message."""
    result = _git(repo_path, "log", "-1", "--format=%B", sha)
    for line in result.stdout.splitlines():
        if line.startswith("Change-Id:"):
            return line.split(":", 1)[1].strip()
    return ""


def attempt_cherry_pick(
    change,
    branch: str,
    config: dict,
    dry_run: bool = False,
) -> dict:
    """
    Attempt to cherry-pick a merged change to a stable branch.

    Returns a dict with keys: status, message, backport_change_url, commit_sha.
    status values: BACKPORTED | CONFLICT | FETCH_FAILED | PUSH_FAILED | DRY_RUN
    """
    repo_path = Path(config["repo_path"])
    remote = config.get("gerrit_remote", "gerrit")
    topic_prefix = config.get("backport_topic_prefix", "backport")
    original_branch = _get_current_branch(repo_path)
    backport_branch = f"backport-{change.change_id}-to-{branch.replace('/', '-')}"

    print(f"\n   Cherry-picking {change.change_id} → {branch}")
    if dry_run:
        print("   [DRY RUN] Would attempt cherry-pick")
        return {"status": "DRY_RUN", "message": "Dry run — no git operations performed"}

    # Fetch the merged change
    fetch_result = _git(repo_path, "fetch", remote, change.git_fetch_ref)
    if fetch_result.returncode != 0:
        return {"status": "FETCH_FAILED",
                "message": f"Could not fetch {change.git_fetch_ref}: {fetch_result.stderr.strip()}"}

    # Get the commit SHA
    sha_result = _git(repo_path, "rev-parse", "FETCH_HEAD")
    commit_sha = sha_result.stdout.strip()
    original_change_id = _get_change_id_from_commit(repo_path, commit_sha)

    try:
        # Fetch and checkout the target branch
        _git(repo_path, "fetch", remote, f"refs/heads/{branch}", check=False)
        checkout = _git(repo_path, "checkout", "-b", backport_branch, f"{remote}/{branch}")
        if checkout.returncode != 0:
            # Branch may already exist from a previous attempt; try switching to it.
            fallback = _git(repo_path, "checkout", backport_branch)
            if fallback.returncode != 0:
                return {
                    "status": "FETCH_FAILED",
                    "message": (
                        f"Could not create or switch to {backport_branch}: "
                        f"{checkout.stderr.strip()[:200]}"
                    ),
                }

        # Attempt cherry-pick
        pick = _git(repo_path, "cherry-pick", commit_sha)
        if pick.returncode != 0:
            _git(repo_path, "cherry-pick", "--abort")
            _git(repo_path, "checkout", original_branch)
            _git(repo_path, "branch", "-D", backport_branch)
            return {
                "status": "CONFLICT",
                "commit_sha": commit_sha,
                "message": f"Cherry-pick conflict: {pick.stderr.strip()[:300]}",
            }

        # Amend commit message to reference upstream
        orig_msg_result = _git(repo_path, "log", "-1", "--format=%B")
        orig_msg = orig_msg_result.stdout.strip()
        new_msg = (
            f"Backport of {change.change_id}: {change.title}\n\n"
            f"{orig_msg}\n\n"
            f"(cherry picked from commit {commit_sha})\n"
            f"Original-Change-Id: {original_change_id}"
        )
        _git(repo_path, "commit", "--amend", "--no-edit", "-m", new_msg)

        # Push to Gerrit
        topic = f"{topic_prefix}-{change.change_id}"
        push_ref = f"refs/for/{branch}%topic={topic}"
        push = _git(repo_path, "push", remote, f"HEAD:{push_ref}")
        if push.returncode != 0:
            # Parse the Gerrit change URL from push output if present
            _git(repo_path, "checkout", original_branch)
            _git(repo_path, "branch", "-D", backport_branch)
            return {
                "status": "PUSH_FAILED",
                "commit_sha": commit_sha,
                "message": f"Push failed: {push.stderr.strip()[:300]}",
            }

        # Extract the new change URL from push output
        backport_url = ""
        url_match = re.search(r"https?://\S+", push.stdout + push.stderr)
        if url_match:
            backport_url = url_match.group(0).rstrip(")")

        print(f"   ✅ Backport pushed: {backport_url or 'URL not parsed'}")
        return {
            "status": "BACKPORTED",
            "commit_sha": commit_sha,
            "backport_change_url": backport_url,
            "message": f"Successfully backported to {branch}",
        }

    finally:
        # Always restore original branch and clean up
        _git(repo_path, "checkout", original_branch)
        _git(repo_path, "branch", "-D", backport_branch, check=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(dry_run: bool = False, repos: list = None, lookback_days: int = None,
         single_change: str = None) -> None:
    config = load_config()
    forge = create_forge_client(config)

    monitored_repos = repos or config.get("monitored_repos", [])
    days_back = lookback_days or int(config.get("lookback_days", 7))
    since = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    label = config.get("backport_label", "Backport-Candidate")
    tracking_file = Path(config["backport_tracking_file"])
    repo_path = Path(config["repo_path"])

    print(f"\n{'='*80}")
    print("Backport Monitor")
    print(f"{'='*80}")
    print(f"  Repos:          {', '.join(monitored_repos)}")
    print(f"  Label:          {label}=+1")
    print(f"  Lookback:       {days_back} days (since {since})")
    print(f"  Repo path:      {repo_path}")
    print(f"  Dry run:        {dry_run}")
    print()

    # Ensure the repo is up to date
    if not dry_run:
        print("🔄 Fetching remote branches...")
        subprocess.run(
            ["git", "-C", str(repo_path), "fetch", "--all", "--prune", "--quiet"],
            check=False,
        )

    backport_branches = config.get("backport_branches", [])
    target_branches = expand_branch_patterns(backport_branches, repo_path)
    if not target_branches:
        print("⚠️  No target branches found matching configured patterns")
        print(f"   Patterns: {backport_branches}")
        return
    print(f"🌿 Target branches: {', '.join(target_branches)}")

    total_backported = 0
    total_conflicts = 0

    if single_change:
        print(f"\n🎯 Single-change mode: targeting change #{single_change}")
        for repo in monitored_repos:
            try:
                change = forge.get_change(single_change, repo)
            except Exception as exc:
                print(f"   ❌ Could not fetch change #{single_change} from {repo}: {exc}")
                continue
            for branch in target_branches:
                if is_already_processed(tracking_file, change.change_id, branch):
                    print(f"   ⏭️  Already backported #{change.change_id} to {branch}")
                    continue
                result = attempt_cherry_pick(change, branch, config, dry_run=dry_run)
                status = result["status"]
                if status == "BACKPORTED":
                    total_backported += 1
                    print(f"   ✅ {branch}: backported → {result.get('backport_change_url', '')}")
                elif status == "CONFLICT":
                    total_conflicts += 1
                    print(f"   ⚠️  {branch}: CONFLICT — {result.get('message', '')[:120]}")
        print(f"\n{'='*80}")
        print(f"✅ Done — backported: {total_backported}, conflicts: {total_conflicts}")
        print(f"{'='*80}")
        return

    for repo in monitored_repos:
        print(f"\n📋 Checking {repo} for merged {label}=+1 changes...")
        try:
            merged_changes = forge.list_changes(
                repo, status="merged", label=f"{label}=+1", since=since,
            )
        except Exception as exc:
            print(f"   ❌ Could not query Gerrit: {exc}")
            continue

        print(f"   Found {len(merged_changes)} merged backport candidate(s)")

        for change in merged_changes:
            print(f"\n   Change #{change.change_id}: {change.title[:60]}")

            for branch in target_branches:
                if is_already_processed(tracking_file, change.change_id, branch):
                    print(f"      ⏭️  {branch}: already processed")
                    continue

                result = attempt_cherry_pick(change, branch, config, dry_run=dry_run)
                status = result["status"]

                if status == "BACKPORTED":
                    total_backported += 1
                    print(f"      ✅ {branch}: backported → {result.get('backport_change_url', '')}")
                elif status == "CONFLICT":
                    total_conflicts += 1
                    print(f"      ⚠️  {branch}: CONFLICT — {result.get('message', '')[:120]}")
                elif status == "DRY_RUN":
                    print(f"      🔵 {branch}: would attempt cherry-pick")
                else:
                    print(f"      ❌ {branch}: {status} — {result.get('message', '')[:120]}")

                if not dry_run:
                    record_backport(
                        tracking_file,
                        change_id=change.change_id,
                        branch=branch,
                        status=status,
                        backport_change_url=result.get("backport_change_url"),
                        commit_sha=result.get("commit_sha"),
                    )

    print(f"\n{'='*80}")
    print("✅ Backport monitor complete")
    print(f"   Backported: {total_backported}  |  Conflicts skipped: {total_conflicts}")
    print(f"{'='*80}")


def cli_main() -> None:
    parser = HelpOnErrorParser(
        description="Octavia Backport Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan for recent merged changes with Backport-Candidate=+1
  %(prog)s

  # Dry run — show what would be cherry-picked without making changes
  %(prog)s --dry-run

  # Restrict to a specific repo
  %(prog)s --repo openstack/octavia

  # Override look-back window
  %(prog)s --lookback 14

  # Attempt to backport a single specific merged change
  %(prog)s --change 982567
        """,
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Log what would happen without making git changes")
    parser.add_argument("--repo", action="append", dest="repos",
                        help="Repo to process (can repeat; default: from config)")
    parser.add_argument("--lookback", type=int, dest="lookback_days",
                        help="Days to look back for merged changes (default: from config)")
    parser.add_argument(
        "--change",
        metavar="N",
        help="Attempt to backport a single specific merged change number.",
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        default=None,
        help="Override the configured output directory.",
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run, repos=args.repos, lookback_days=args.lookback_days,
         single_change=args.change)


if __name__ == "__main__":
    cli_main()
