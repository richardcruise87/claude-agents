"""
Patch application and reversion for the Fix Verification Agent.

Supports multiple patch sources: local files, local branches, Gerrit changes,
and the case where the developer has already applied the fix manually.
"""
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from agents_lib import get_branch_name, checkout_ref, git_stash_save, git_stash_pop


class PatchSourceType(Enum):
    FILE = "file"          # Local unified diff / git diff file
    BRANCH = "branch"      # Local git branch name
    GERRIT = "gerrit"      # Gerrit change number
    ALREADY_APPLIED = "already_applied"  # Developer pre-applied; do nothing


@dataclass
class PatchSource:
    """Describes where the patch comes from."""
    source_type: PatchSourceType
    value: str = ""        # Path, branch name, or change number
    gerrit_base_url: str = "https://review.opendev.org"
    description: str = ""  # Human-readable label for reports

    def __post_init__(self) -> None:
        if not self.description:
            if self.source_type == PatchSourceType.FILE:
                self.description = f"Local patch file: {self.value}"
            elif self.source_type == PatchSourceType.BRANCH:
                self.description = f"Local branch: {self.value}"
            elif self.source_type == PatchSourceType.GERRIT:
                self.description = f"Gerrit change: {self.value}"
            else:
                self.description = "Pre-applied by developer"


@dataclass
class ApplyResult:
    """Outcome of a patch application attempt."""
    success: bool
    error: str = ""
    original_branch: str = ""  # Saved for revert
    applied_ref: str = ""      # The ref actually checked out (Gerrit only)


def _run(cmd: list, cwd: Path, timeout: int = 60) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True,
        timeout=timeout, check=False,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _current_branch(repo_path: Path) -> str:
    """Return the current git branch name, or HEAD sha if detached."""
    name = get_branch_name(repo_path)
    if name and name != "HEAD":
        return name
    # Detached HEAD — return the commit SHA
    rc, sha, _ = _run(["git", "rev-parse", "HEAD"], repo_path)
    return sha if rc == 0 else "unknown"


def _apply_file(source: PatchSource, repo_path: Path, original: str) -> ApplyResult:
    patch_path = Path(source.value).expanduser()
    if not patch_path.exists():
        return ApplyResult(success=False,
                           error=f"Patch file not found: {patch_path}",
                           original_branch=original)
    rc, _, err = _run(["git", "apply", "--index", str(patch_path)], repo_path)
    if rc != 0:
        return ApplyResult(success=False, error=f"git apply failed: {err}",
                           original_branch=original)
    return ApplyResult(success=True, original_branch=original)


def _apply_branch(source: PatchSource, repo_path: Path, original: str) -> ApplyResult:
    git_stash_save(repo_path)
    ok, msg = checkout_ref(repo_path, source.value)
    if not ok:
        git_stash_pop(repo_path)
        return ApplyResult(success=False,
                           error=f"git checkout {source.value} failed: {msg}",
                           original_branch=original)
    return ApplyResult(success=True, original_branch=original)


def _apply_gerrit(source: PatchSource, repo_path: Path, original: str) -> ApplyResult:
    change_id = source.value
    last2 = str(change_id)[-2:].zfill(2)
    fetch_ref = f"refs/changes/{last2}/{change_id}/*"
    rc, _, err = _run(["git", "fetch", "gerrit", fetch_ref], repo_path, timeout=120)
    if rc != 0:
        fetch_ref = f"refs/changes/{last2}/{change_id}/1"
        rc, _, err = _run(["git", "fetch", "gerrit", fetch_ref], repo_path, timeout=120)
    if rc != 0:
        return ApplyResult(success=False,
                           error=f"Could not fetch Gerrit change {change_id}: {err}",
                           original_branch=original)
    rc2, _, err2 = _run(["git", "checkout", "FETCH_HEAD"], repo_path)
    if rc2 != 0:
        return ApplyResult(success=False,
                           error=f"Could not checkout FETCH_HEAD for {change_id}: {err2}",
                           original_branch=original)
    return ApplyResult(success=True, original_branch=original,
                       applied_ref=f"Gerrit {change_id} (FETCH_HEAD)")


def apply_patch(source: PatchSource, repo_path: Path) -> ApplyResult:
    """
    Apply the patch described by *source* to *repo_path*.

    Returns an ApplyResult describing success or the reason for failure.
    The original branch is saved in ApplyResult.original_branch so it can
    be passed to revert_patch() later.
    """
    original = _current_branch(repo_path)

    if source.source_type == PatchSourceType.ALREADY_APPLIED:
        return ApplyResult(success=True, original_branch=original)

    if source.source_type == PatchSourceType.FILE:
        return _apply_file(source, repo_path, original)

    if source.source_type == PatchSourceType.BRANCH:
        return _apply_branch(source, repo_path, original)

    if source.source_type == PatchSourceType.GERRIT:
        return _apply_gerrit(source, repo_path, original)

    return ApplyResult(
        success=False,
        error=f"Unknown patch source type: {source.source_type}",
        original_branch=original,
    )


def revert_patch(source: PatchSource, repo_path: Path, apply_result: ApplyResult) -> None:
    """
    Restore *repo_path* to its state before apply_patch() was called.

    Best-effort: errors are printed but not raised so the calling agent
    can continue even if cleanup is imperfect.
    """
    if source.source_type == PatchSourceType.ALREADY_APPLIED:
        return  # Developer applied it; don't touch it

    try:
        if source.source_type == PatchSourceType.FILE:
            _run(["git", "apply", "--reverse", "--index",
                  str(Path(source.value).expanduser())], repo_path)

        elif source.source_type in (PatchSourceType.BRANCH, PatchSourceType.GERRIT):
            original = apply_result.original_branch or "main"
            checkout_ref(repo_path, original)
            # Pop any stash saved during apply
            git_stash_pop(repo_path)

    except Exception as exc:  # pylint: disable=broad-except
        print(f"⚠️  Warning: patch revert failed: {exc}")
