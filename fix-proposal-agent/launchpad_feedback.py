"""
Launchpad and Gerrit feedback reading/posting for the Fix Proposal Agent.

Launchpad posting delegates to agents_lib.launchpad_client.
Reading Launchpad comments uses agents_lib.launchpad_client (public API, no auth).
Reading Gerrit comments uses the ForgeClient.
"""
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import List, Optional

from agents_lib import build_feedback_comment, post_launchpad_comment, get_launchpad_bug_comments


def post_proposal_to_launchpad(
    bug_id: str,
    proposal_file: Path,
    risk_rating: str,
    config: dict,
) -> None:
    """Post a fix proposal summary as a Launchpad bug comment.

    Errors are logged but never raised.
    """
    if not config.get("feedback", {}).get("post_to_launchpad"):
        return

    feedback_cfg = config.get("feedback", {})
    consumer_key = os.environ.get(feedback_cfg.get("consumer_key_env", ""), "")
    access_token = os.environ.get(feedback_cfg.get("access_token_env", ""), "")
    token_secret = os.environ.get(
        feedback_cfg.get("access_token_secret_env", ""), ""
    )
    if not all([consumer_key, access_token, token_secret]):
        print(
            "⚠️  Launchpad feedback skipped — configure "
            f"{feedback_cfg.get('consumer_key_env')}, "
            f"{feedback_cfg.get('access_token_env')}, and "
            f"{feedback_cfg.get('access_token_secret_env')}."
        )
        return

    try:
        content = proposal_file.read_text(encoding="utf-8")
        model_name = config.get("model", "claude-sonnet-4-6")
        comment = build_feedback_comment(content, model_name, max_chars=5000)
        subject = f"AI Fix Proposal — Risk: {risk_rating} (automated, may contain errors)"
        print(f"\n📤 Posting fix proposal comment to Launchpad bug #{bug_id}...")
        ok = post_launchpad_comment(
            bug_id, subject, comment, consumer_key, access_token, token_secret
        )
        if ok:
            print(f"   ✅ Comment posted to bug #{bug_id}")
        else:
            print("   ⚠️  Comment post returned failure")
    except Exception as exc:
        print(f"   ⚠️  Could not post Launchpad feedback: {exc}")


# ---------------------------------------------------------------------------
# Launchpad comment reading (public API, no auth)
# ---------------------------------------------------------------------------

def get_launchpad_comments_since(
    bug_id: str,
    since_iso: str,
) -> List[dict]:
    """Fetch Launchpad bug comments posted after since_iso.

    Delegates to agents_lib.get_launchpad_bug_comments (public API, no auth).
    """
    return get_launchpad_bug_comments(bug_id, since_iso=since_iso)


# ---------------------------------------------------------------------------
# Gerrit comment reading
# ---------------------------------------------------------------------------

def get_gerrit_comments_since(
    change_id: str,
    since_iso: str,
    forge_client,
) -> List[dict]:
    """Fetch human-authored Gerrit review comments posted after since_iso.

    Strips bot/CI comments (authors containing 'zuul', 'jenkins', 'bot').

    Returns:
        List of dicts with keys: author, message, date.
    """
    try:
        base = forge_client.base_url.rstrip("/")
        url = f"{base}/changes/{urllib.parse.quote(str(change_id), safe='')}/comments"
        # pylint: disable=protected-access
        data = forge_client._http_get_gerrit(url)
        comments = []
        bot_markers = ("zuul", "jenkins", "bot", "ci-bot")
        for _file, file_comments in (data if isinstance(data, dict) else {}).items():
            for comment in file_comments:
                updated = comment.get("updated", "")
                if updated <= since_iso:
                    continue
                author = (
                    comment.get("author", {}).get("name", "")
                    or comment.get("author", {}).get("username", "")
                ).lower()
                if any(m in author for m in bot_markers):
                    continue
                comments.append({
                    "author": author,
                    "message": comment.get("message", ""),
                    "date": updated,
                })
        return comments
    except Exception as exc:
        print(f"⚠️  Could not fetch Gerrit comments for change {change_id}: {exc}")
        return []


# ---------------------------------------------------------------------------
# Gerrit WIP draft push
# ---------------------------------------------------------------------------

def push_gerrit_wip_draft(
    repo_path: Path,
    patch_content: str,
    bug_number: str,
    bug_title: str,
    gerrit_remote: str = "gerrit",
    target_branch: str = "master",
) -> Optional[str]:
    """Apply a patch and push it to Gerrit as a WIP (Work-In-Progress) draft.

    The patch is applied to a temporary branch, committed, pushed as WIP,
    then the temp branch is deleted locally.

    Args:
        repo_path:     Path to the git repository.
        patch_content: The unified diff / git diff output to apply.
        bug_number:    Launchpad bug number (used in commit message).
        bug_title:     Bug title (used in commit message).
        gerrit_remote: Git remote name for Gerrit (default: "gerrit").
        target_branch: Branch to target for the Gerrit change (default: "master").

    Returns:
        Gerrit change URL extracted from push output, or None on failure.
    """
    import subprocess
    import tempfile

    branch_name = f"fix/bug-{bug_number}-ai-proposal"
    commit_msg = (
        f"[WIP] Fix for bug #{bug_number}: {bug_title[:60]}\n\n"
        f"AI-generated fix proposal. Risk rating and reasoning in\n"
        f"the associated fix proposal document.\n\n"
        f"Closes-Bug: #{bug_number}"
    )

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".patch", delete=False
        ) as pf:
            pf.write(patch_content)
            patch_file = pf.name

        # Create temp branch from current HEAD
        subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=repo_path, check=True, capture_output=True,
        )

        # Apply patch
        apply = subprocess.run(
            ["git", "apply", "--index", patch_file],
            cwd=repo_path, capture_output=True, text=True, check=False,
        )
        if apply.returncode != 0:
            print(f"⚠️  git apply failed: {apply.stderr.strip()}")
            return None

        # Commit
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=repo_path, check=True, capture_output=True,
        )

        # Push as WIP to Gerrit
        push = subprocess.run(
            ["git", "push", gerrit_remote,
             f"HEAD:refs/for/{target_branch}%wip"],
            cwd=repo_path, capture_output=True, text=True, check=False,
        )

        # Extract Gerrit change URL from push output
        change_url = None
        for line in (push.stdout + push.stderr).splitlines():
            if "review.opendev.org" in line or "review." in line:
                parts = line.strip().split()
                for part in parts:
                    if part.startswith("http"):
                        change_url = part
                        break

        if change_url:
            print(f"   ✅ Gerrit WIP draft: {change_url}")
        else:
            print("   ⚠️  Gerrit push completed but could not extract change URL")

        return change_url

    except subprocess.CalledProcessError as exc:
        print(f"⚠️  Gerrit WIP push failed: {exc}")
        return None
    except Exception as exc:
        print(f"⚠️  Unexpected error during Gerrit push: {exc}")
        return None
    finally:
        # Always restore the original branch
        try:
            subprocess.run(
                ["git", "checkout", "-"],
                cwd=repo_path, capture_output=True, check=False,
            )
            subprocess.run(
                ["git", "branch", "-D", branch_name],
                cwd=repo_path, capture_output=True, check=False,
            )
        except Exception:
            pass
        try:
            os.unlink(patch_file)
        except Exception:
            pass
