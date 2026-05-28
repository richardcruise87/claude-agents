"""
Git repository information helpers.

All functions run git commands deterministically and return structured data
so that agent prompts receive pre-computed facts rather than running bash.
Every function returns a value and never raises — errors are returned as
part of the result so the caller can decide how to handle them.
"""

import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _git(args: List[str], cwd: Path, timeout: int = 30) -> Tuple[int, str, str]:
    """Run a git command; return (returncode, stdout, stderr). Never raises."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", f"git {args[0]} timed out after {timeout}s"
    except FileNotFoundError:
        return 1, "", "git not found in PATH"


def get_branch_name(repo_path: Path) -> str:
    """Return the current branch name, or 'HEAD' if detached, or '' on error."""
    rc, out, _ = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    return out.strip() if rc == 0 else ""


def checkout_ref(repo_path: Path, ref: str) -> Tuple[bool, str]:
    """Checkout a git ref. Returns (success, message)."""
    rc, _, err = _git(["checkout", ref], repo_path)
    if rc == 0:
        return True, f"Checked out {ref}"
    return False, err.strip() or f"git checkout {ref} failed (exit {rc})"


def get_commit_info(repo_path: Path, ref: str = "HEAD") -> Dict:
    """Return structured commit information for the given ref.

    Returns a dict with keys:
        sha, short_sha, author, date, subject, body,
        change_id (Gerrit Change-Id or ''), bug_refs (list of '#NNNN' strings),
        error ('' on success, message on failure)
    """
    fmt = "%x00".join(["%H", "%h", "%an <%ae>", "%ai", "%s", "%b"])
    rc, out, err = _git(["log", "-1", f"--pretty=format:{fmt}", ref], repo_path)
    if rc != 0:
        return {
            "sha": "", "short_sha": "", "author": "", "date": "",
            "subject": "", "body": "", "change_id": "", "bug_refs": [],
            "error": err.strip() or f"git log failed (exit {rc})",
        }

    parts = out.split("\x00")
    sha, short_sha, author, date, subject = (parts + [""] * 5)[:5]
    body = "\x00".join(parts[5:]) if len(parts) > 5 else ""

    change_id = ""
    m = re.search(r"Change-Id:\s*(I[0-9a-f]+)", body)
    if m:
        change_id = m.group(1)

    bug_refs = re.findall(r"(?:Closes|Partial|Related)-Bug:\s*#?(\d+)", body, re.IGNORECASE)

    return {
        "sha": sha.strip(),
        "short_sha": short_sha.strip(),
        "author": author.strip(),
        "date": date.strip(),
        "subject": subject.strip(),
        "body": body.strip(),
        "change_id": change_id,
        "bug_refs": bug_refs,
        "error": "",
    }


def get_changed_files(
    repo_path: Path,
    max_diff_lines: int = 300,
) -> Dict:
    """Return information about files changed in the current HEAD commit.

    Returns a dict with keys:
        stat (str): output of git show --stat
        names (list[str]): list of changed file paths
        diff (str): unified diff, truncated to max_diff_lines
        diff_truncated (bool): True if diff was cut short
        error (str): '' on success, error message on failure
    """
    rc_stat, stat, err = _git(["show", "--stat"], repo_path)
    if rc_stat != 0:
        return {"stat": "", "names": [], "diff": "", "diff_truncated": False,
                "error": err.strip() or "git show --stat failed"}

    rc_names, names_out, _ = _git(["diff", "HEAD~1", "--name-only"], repo_path)
    names = [n for n in names_out.splitlines() if n.strip()] if rc_names == 0 else []

    rc_diff, diff_out, _ = _git(["diff", "HEAD~1"], repo_path, timeout=60)
    diff_lines = diff_out.splitlines() if rc_diff == 0 else []
    truncated = len(diff_lines) > max_diff_lines
    diff = "\n".join(diff_lines[:max_diff_lines])

    return {
        "stat": stat.strip(),
        "names": names,
        "diff": diff,
        "diff_truncated": truncated,
        "error": "",
    }


def expand_remote_branches(repo_path: Path, pattern: str) -> List[str]:
    """Expand a branch pattern (e.g. 'stable/*') to real remote branch names.

    Fetches all remotes first so the listing is up-to-date.
    Returns a list of branch names (without 'origin/' prefix), or [] on error.
    """
    _git(["fetch", "--all", "--quiet"], repo_path, timeout=120)
    rc, out, _ = _git(["branch", "-r", "--list", f"origin/{pattern}"], repo_path)
    if rc != 0:
        return []
    branches = []
    for line in out.splitlines():
        branch = line.strip().removeprefix("origin/").strip()
        if branch and not branch.startswith("HEAD"):
            branches.append(branch)
    return branches


def format_commit_info(info: Dict) -> str:
    """Format a get_commit_info() dict as a human-readable string for prompts."""
    if info.get("error"):
        return f"[git commit info unavailable: {info['error']}]"
    lines = [
        f"SHA:     {info['sha']}",
        f"Author:  {info['author']}",
        f"Date:    {info['date']}",
        f"Subject: {info['subject']}",
    ]
    if info["body"]:
        lines.append("")
        lines.append(info["body"])
    if info["change_id"]:
        lines.append(f"\nChange-Id: {info['change_id']}")
    if info["bug_refs"]:
        lines.append(f"Bug refs: {', '.join('#' + b for b in info['bug_refs'])}")
    return "\n".join(lines)


def format_changed_files(info: Dict, max_diff_lines: Optional[int] = None) -> str:
    """Format a get_changed_files() dict as a human-readable block for prompts."""
    if info.get("error"):
        return f"[git change info unavailable: {info['error']}]"
    parts = [info["stat"]]
    if info["diff"]:
        truncation_note = (
            f"\n[diff truncated at {max_diff_lines or len(info['diff'].splitlines())} lines"
            " — use the Read tool to inspect specific files for full context]"
            if info["diff_truncated"] else ""
        )
        parts.append(f"\n```diff\n{info['diff']}\n```{truncation_note}")
    return "\n".join(parts)
