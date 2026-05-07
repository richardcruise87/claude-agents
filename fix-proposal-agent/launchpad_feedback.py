"""
Launchpad and Gerrit feedback reading/posting for the Fix Proposal Agent.

Posting uses OAuth 1.0a (same pattern as bug-triage-agent).
Reading Launchpad comments uses the public REST API (no auth required).
Reading Gerrit comments uses the ForgeClient.
"""
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import List, Optional

from agents_lib import build_feedback_comment


# ---------------------------------------------------------------------------
# Launchpad OAuth posting (stdlib only — identical to bug-triage-agent)
# ---------------------------------------------------------------------------

def _launchpad_auth_header(
    method: str,
    url: str,
    consumer_key: str,
    access_token: str,
    token_secret: str,
) -> str:
    """Build an OAuth 1.0a HMAC-SHA1 Authorization header for Launchpad."""
    timestamp = str(int(time.time()))
    nonce = uuid.uuid4().hex
    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_token": access_token,
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp,
        "oauth_nonce": nonce,
        "oauth_version": "1.0",
    }
    param_string = "&".join(
        f"{urllib.parse.quote(k, safe='')}={urllib.parse.quote(v, safe='')}"
        for k, v in sorted(oauth_params.items())
    )
    base_string = "&".join([
        method.upper(),
        urllib.parse.quote(url, safe=""),
        urllib.parse.quote(param_string, safe=""),
    ])
    # Launchpad desktop integrations use a blank consumer secret
    signing_key = f"&{urllib.parse.quote(token_secret, safe='')}"
    raw_sig = hmac.new(
        signing_key.encode(), base_string.encode(), hashlib.sha1
    ).digest()
    oauth_params["oauth_signature"] = base64.b64encode(raw_sig).decode()
    return "OAuth " + ", ".join(
        f'{k}="{urllib.parse.quote(v, safe="")}"'
        for k, v in oauth_params.items()
    )


def post_launchpad_comment(
    bug_id: str,
    subject: str,
    content: str,
    consumer_key: str,
    access_token: str,
    token_secret: str,
) -> bool:
    """Post a comment to a Launchpad bug. Returns True on success."""
    url = f"https://api.launchpad.net/1.0/bugs/{bug_id}/messages"
    body = urllib.parse.urlencode(
        {"subject": subject, "content": content}
    ).encode("utf-8")
    auth = _launchpad_auth_header(
        "POST", url, consumer_key, access_token, token_secret
    )
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", auth)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status in (200, 201)
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            detail = ""
        print(f"⚠️  Launchpad comment failed (HTTP {exc.code}): {exc.reason} — {detail}")
        return False
    except urllib.error.URLError as exc:
        print(f"⚠️  Launchpad comment failed (network): {exc.reason}")
        return False


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

    Uses the public REST API — no authentication required.

    Returns:
        List of dicts with keys: author, content, date_created.
    """
    url = f"https://api.launchpad.net/1.0/bugs/{bug_id}/messages"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        comments = []
        for entry in data.get("entries", []):
            date_created = entry.get("date_created", "")
            if date_created > since_iso:
                comments.append({
                    "author": entry.get("owner_link", "unknown"),
                    "content": entry.get("content", ""),
                    "date_created": date_created,
                })
        return comments
    except Exception as exc:
        print(f"⚠️  Could not fetch Launchpad comments for bug #{bug_id}: {exc}")
        return []


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
