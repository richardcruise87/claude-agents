"""
Notification dispatch for Claude Agents.

Loads a shared notifications.json config and sends reports to configured
channels (email, Slack, ntfy.sh, desktop). Failures per-channel are caught
and logged; they never propagate to the calling agent.
"""

import json
import os
import smtplib
import subprocess
import sys
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


def load_notifications_config(repo_root: Path | None = None) -> dict:
    """Load the shared notifications.json file.

    Search order:
    1. Path in CLAUDE_AGENTS_NOTIFICATIONS_CONFIG environment variable
    2. repo_root/notifications.json  (auto-detected if repo_root is None)
    3. ~/.config/claude-agents/notifications.json

    Returns an empty dict if no file is found — notifications are then
    silently disabled regardless of per-agent config.
    """
    candidates = []

    env_path = os.environ.get("CLAUDE_AGENTS_NOTIFICATIONS_CONFIG")
    if env_path:
        candidates.append(Path(env_path))

    if repo_root is None:
        # Auto-detect: this file is agents_lib/agents_lib/notifications.py
        # so the repo root is three levels up.
        repo_root = Path(__file__).parent.parent.parent

    candidates.append(Path(repo_root) / "notifications.json")
    candidates.append(Path.home() / ".config" / "claude-agents" / "notifications.json")

    for path in candidates:
        if path.is_file():
            try:
                return json.loads(path.read_text())
            except Exception as e:
                print(f"[notifications] failed to load {path}: {e}", file=sys.stderr)
                return {}

    return {}


def notify_report(
    report_path: Path,
    subject: str,
    summary: str,
    agent_config: dict,
    notifications_config: dict,
) -> None:
    """Send notifications for a newly saved report.

    Only fires if agent_config["notifications"]["enabled"] is True.
    Each channel is dispatched independently; a failure in one does not
    prevent the others from running.

    Args:
        report_path: Path to the saved markdown report file.
        subject:     Short subject line (used as email subject, Slack heading,
                     ntfy title, and desktop notification summary).
        summary:     One-line summary of the report outcome.
        agent_config: The agent's own config dict (contains notifications.enabled).
        notifications_config: Loaded from load_notifications_config().
    """
    agent_notif = agent_config.get("notifications", {})
    if not agent_notif.get("enabled", False):
        return

    if not notifications_config:
        return

    shared_channels = notifications_config.get("channels", {})
    # Per-agent overrides are merged on top of shared channel config
    agent_channels = agent_notif.get("channels", {})

    for channel_name in ("email", "slack", "ntfy", "desktop"):
        shared = shared_channels.get(channel_name, {})
        override = agent_channels.get(channel_name, {})
        cfg = {**shared, **override}

        if not cfg.get("enabled", False):
            continue

        try:
            if channel_name == "email":
                _send_email(cfg, subject, summary, report_path)
            elif channel_name == "slack":
                _send_slack(cfg, subject, summary, report_path)
            elif channel_name == "ntfy":
                _send_ntfy(cfg, subject, summary)
            elif channel_name == "desktop":
                _send_desktop(subject, summary)
        except Exception as e:
            print(f"[notifications] {channel_name} failed: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Channel helpers
# ---------------------------------------------------------------------------

def _resolve_env(cfg: dict, key: str) -> str | None:
    """Return cfg[key] if present, else read from cfg[key + '_env']."""
    direct = cfg.get(key)
    if direct:
        return direct
    env_key = cfg.get(f"{key}_env")
    if env_key:
        return os.environ.get(env_key)
    return None


def _send_email(cfg: dict, subject: str, summary: str, report_path: Path) -> None:
    host = cfg.get("smtp_host", "localhost")
    port = int(cfg.get("smtp_port", 587))
    user = cfg.get("smtp_user")
    password = _resolve_env(cfg, "smtp_password")
    from_addr = cfg.get("from", user or "claude-agents@localhost")
    to_addrs = cfg.get("to", [])
    use_tls = cfg.get("use_tls", True)
    include_body = cfg.get("include_report_body", True)

    if not to_addrs:
        raise ValueError("email.to is empty")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs)

    body_lines = [summary, "", f"Report saved to: {report_path}"]
    if include_body and report_path.is_file():
        body_lines += ["", "---", "", report_path.read_text()]

    msg.attach(MIMEText("\n".join(body_lines), "plain"))

    if use_tls:
        server = smtplib.SMTP(host, port)
        server.starttls()
    else:
        server = smtplib.SMTP_SSL(host, port) if port == 465 else smtplib.SMTP(host, port)

    if user and password:
        server.login(user, password)

    server.sendmail(from_addr, to_addrs, msg.as_string())
    server.quit()
    print(f"[notifications] email sent to {', '.join(to_addrs)}")


def _send_slack(cfg: dict, subject: str, summary: str, report_path: Path) -> None:
    webhook_url = _resolve_env(cfg, "webhook_url")
    if not webhook_url:
        raise ValueError("slack.webhook_url / slack.webhook_url_env not configured")

    # Truncate report snippet for Slack (keep it readable in channel)
    snippet = ""
    if report_path.is_file():
        text = report_path.read_text()
        snippet = text[:500] + ("…" if len(text) > 500 else "")

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": subject}},
        {"type": "section", "text": {"type": "mrkdwn", "text": summary}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"Report: `{report_path}`"}},
    ]
    if snippet:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"```{snippet}```"},
        })

    payload = json.dumps({"blocks": blocks}).encode()
    req = urllib.request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status not in (200, 204):
            raise RuntimeError(f"Slack returned HTTP {resp.status}")
    print("[notifications] Slack message sent")


def _send_ntfy(cfg: dict, subject: str, summary: str) -> None:
    url = cfg.get("url")
    if not url:
        raise ValueError("ntfy.url not configured")

    token = _resolve_env(cfg, "token")
    priority = cfg.get("priority", "default")

    headers = {"Title": subject, "Priority": priority, "Content-Type": "text/plain"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = summary.encode()
    req = urllib.request.Request(url, data=payload, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status not in (200, 204):
            raise RuntimeError(f"ntfy returned HTTP {resp.status}")
    print("[notifications] ntfy notification sent")


def _send_desktop(subject: str, summary: str) -> None:
    # Only attempt if a display is available
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return

    result = subprocess.run(
        ["notify-send", subject, summary],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode().strip() or "notify-send failed")
    print("[notifications] desktop notification sent")
