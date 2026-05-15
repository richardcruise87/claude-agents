"""
Launchpad REST API client for Claude agents.

Provides posting and reading utilities for Launchpad bugs. Posting uses
launchpadlib (handles OAuth signing correctly for all credential types).
Reading uses the public Launchpad REST API and requires no authentication.
"""
import json
import os
import urllib.error
import urllib.request
from typing import List, Optional


def post_launchpad_comment(
    bug_id: str,
    subject: str,
    content: str,
    consumer_key: str,
    access_token: str,
    token_secret: str,
) -> bool:
    """Post a comment to a Launchpad bug.

    Uses launchpadlib to handle OAuth signing, which supports all credential
    types including system-wide credentials.

    Args:
        bug_id:       Launchpad bug number (string or int).
        subject:      Comment subject line.
        content:      Comment body text.
        consumer_key: OAuth consumer key from launchpad credentials.
        access_token: OAuth access token.
        token_secret: OAuth access token secret.

    Returns:
        True on success, False on any error (errors are printed, never raised).
    """
    try:
        from launchpadlib.launchpad import Launchpad          # pylint: disable=import-outside-toplevel
        from launchpadlib.credentials import Credentials, AccessToken  # pylint: disable=import-outside-toplevel
    except ImportError:
        print("⚠️  launchpadlib not installed — run: pip install launchpadlib")
        return False

    try:
        creds = Credentials(consumer_name=consumer_key)
        creds.access_token = AccessToken(access_token, token_secret)
        lp = Launchpad(
            creds,
            "https://api.launchpad.net/",
            "https://launchpad.net",
            service_root="production",
            version="devel",
        )
        bug = lp.bugs[int(bug_id)]
        bug.newMessage(subject=subject, content=content)
        print(f"   ✅ Comment posted to Launchpad bug #{bug_id}")
        return True
    except Exception as exc:  # pylint: disable=broad-except
        print(f"⚠️  Launchpad comment failed for bug #{bug_id}: {exc}")
        return False


def post_launchpad_comment_from_config(
    bug_id: str,
    subject: str,
    content: str,
    config: dict,
) -> bool:
    """Post a Launchpad comment using credentials from agent config / env vars.

    Reads the three OAuth credential env-var names from:
        config["feedback_consumer_key_env"]
        config["feedback_access_token_env"]
        config["feedback_access_token_secret_env"]

    Respects `feedback.post_to_launchpad` — returns False immediately if the
    flag is False or absent, so callers don't need to check it separately.

    Returns False (with a warning) if any credential is missing or posting
    fails.  Errors are never raised.
    """
    feedback_cfg = config.get("feedback", {})

    # Honour the post_to_launchpad flag from the nested feedback section
    if not feedback_cfg.get("post_to_launchpad"):
        return False

    # Support both flat keys (legacy) and nested feedback dict
    ck_env = config.get("feedback_consumer_key_env") or feedback_cfg.get("consumer_key_env", "")
    at_env = config.get("feedback_access_token_env") or feedback_cfg.get("access_token_env", "")
    ts_env = (
        config.get("feedback_access_token_secret_env")
        or feedback_cfg.get("access_token_secret_env", "")
    )

    consumer_key = os.environ.get(ck_env, "") if ck_env else ""
    access_token = os.environ.get(at_env, "") if at_env else ""
    token_secret = os.environ.get(ts_env, "") if ts_env else ""

    if not all([consumer_key, access_token, token_secret]):
        missing = [
            name for name, val in [
                (ck_env, consumer_key),
                (at_env, access_token),
                (ts_env, token_secret),
            ] if not val
        ]
        print(
            f"⚠️  Launchpad posting skipped — set env vars: {', '.join(missing)}"
        )
        return False

    return post_launchpad_comment(bug_id, subject, content,
                                  consumer_key, access_token, token_secret)


def get_launchpad_bug_comments(
    bug_id: str,
    since_iso: Optional[str] = None,
) -> List[dict]:
    """Fetch comments on a Launchpad bug via the public REST API (no auth needed).

    Args:
        bug_id:    Launchpad bug number.
        since_iso: ISO 8601 timestamp; only return comments created after this.
                   Pass None to return all comments.

    Returns:
        List of dicts with keys: author, content, date_created.
        Returns an empty list on any error.
    """
    url = f"https://api.launchpad.net/1.0/bugs/{bug_id}/messages"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        comments = []
        for entry in data.get("entries", []):
            date_created = entry.get("date_created", "")
            if since_iso and date_created <= since_iso:
                continue
            comments.append({
                "author": entry.get("owner_link", "unknown"),
                "content": entry.get("content", ""),
                "date_created": date_created,
            })
        return comments
    except Exception as exc:  # pylint: disable=broad-except
        print(f"⚠️  Could not fetch Launchpad comments for bug #{bug_id}: {exc}")
        return []


def post_report_to_launchpad(
    bug_id: str,
    subject: str,
    report_file: "Path",
    config: dict,
    max_chars: int = 5000,
) -> bool:
    """Read a saved report file and post it as a Launchpad bug comment.

    Convenience wrapper used by agents' --post-only paths. Reads the file,
    builds a sanitised feedback comment via build_feedback_comment(), then
    delegates to post_launchpad_comment_from_config().

    Returns True on success, False on any failure (errors are printed, not raised).
    """
    from pathlib import Path as _Path
    from .utils import build_feedback_comment

    try:
        content = _Path(report_file).read_text(encoding="utf-8")
        model_name = config.get("model", "claude-sonnet-4-6")
        comment = build_feedback_comment(content, model_name, max_chars=max_chars)
        print(f"\n📤 Posting report to Launchpad bug #{bug_id}...")
        return post_launchpad_comment_from_config(bug_id, subject, comment, config)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"⚠️  Could not post report to Launchpad bug #{bug_id}: {exc}")
        return False
