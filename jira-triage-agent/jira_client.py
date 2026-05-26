"""
JIRA REST API client (Atlassian Cloud v3).

Uses stdlib urllib — no third-party JIRA SDK needed.
Supports Basic auth with an API token (email + token).
"""

import base64
import json
import os
import urllib.parse
import urllib.request


class JiraClient:
    """Minimal JIRA Cloud REST API v3 client."""

    def __init__(self, base_url: str, email: str, token: str):
        self._base = base_url.rstrip("/")
        self._api = f"{self._base}/rest/api/3"
        self._auth = base64.b64encode(f"{email}:{token}".encode()).decode()

    @classmethod
    def from_config(cls, config: dict) -> "JiraClient":
        """Create a client from the agent config dict."""
        jira_cfg = config.get("jira", {})
        base_url = jira_cfg.get("base_url", "")
        email = jira_cfg.get("email", "")
        token_env = jira_cfg.get("token_env", "JIRA_API_TOKEN")
        token = os.environ.get(token_env, "")
        if not all([base_url, email, token]):
            raise ValueError(
                f"JIRA config incomplete. Need jira.base_url, jira.email, "
                f"and env var {token_env} to be set."
            )
        return cls(base_url, email, token)

    def _headers(self) -> dict:
        return {
            "Authorization": f"Basic {self._auth}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _get(self, path: str) -> dict | list:
        url = path if path.startswith("http") else f"{self._api}{path}"
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                body = ""
            detail = f" — {body}" if body else ""
            raise RuntimeError(
                f"JIRA HTTP {exc.code} for {url}: {exc.reason}{detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Network error fetching {url}: {exc.reason}") from exc

    def _post(self, path: str, payload: dict) -> dict:
        url = f"{self._api}{path}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                body = ""
            detail = f" — {body}" if body else ""
            raise RuntimeError(
                f"JIRA HTTP {exc.code} for {url}: {exc.reason}{detail}"
            ) from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_issues(self, jql: str, max_results: int = 50) -> list[dict]:
        """Run a JQL query and return a list of issue dicts.

        Each dict contains the fields needed for triage/planning:
        summary, description, issuetype, status, priority,
        created, updated, reporter, assignee, labels, components.
        """
        fields = [
            "summary", "description", "issuetype", "status", "priority",
            "created", "updated", "reporter", "assignee", "labels",
            "components", "comment",
        ]
        payload = {
            "jql": jql,
            "maxResults": max_results,
            "fields": fields,
            "expand": [],
        }
        data = self._post("/search", payload)
        return data.get("issues", [])

    def get_issue(self, issue_key: str) -> dict:
        """Fetch full details for a single issue."""
        return self._get(f"/issue/{urllib.parse.quote(issue_key)}")

    def add_comment(self, issue_key: str, body_text: str,
                    private: bool = False, visibility_role: str = "Service Desk Team") -> bool:
        """Post a comment on a JIRA issue.

        Args:
            issue_key:       JIRA issue key, e.g. ``"PROJ-123"``.
            body_text:       Plain-text / basic-markdown comment content.
            private:         When True, restrict visibility to ``visibility_role``.
            visibility_role: JIRA role name used for private comments.

        Returns:
            True on success, False on any error (error is logged, never raised).
        """
        payload: dict = {"body": _text_to_adf(body_text)}
        if private:
            payload["visibility"] = {"type": "role", "value": visibility_role}
        try:
            self._post(f"/issue/{urllib.parse.quote(issue_key)}/comment", payload)
            return True
        except RuntimeError as exc:
            print(f"⚠️  JIRA comment post failed for {issue_key}: {exc}")
            return False

    # ------------------------------------------------------------------
    # Issue field helpers
    # ------------------------------------------------------------------

    @staticmethod
    def issue_key(issue: dict) -> str:
        return issue.get("key", "UNKNOWN")

    @staticmethod
    def issue_type(issue: dict) -> str:
        return issue.get("fields", {}).get("issuetype", {}).get("name", "")

    @staticmethod
    def summary(issue: dict) -> str:
        return issue.get("fields", {}).get("summary", "")

    @staticmethod
    def status(issue: dict) -> str:
        return issue.get("fields", {}).get("status", {}).get("name", "")

    @staticmethod
    def priority(issue: dict) -> str:
        p = issue.get("fields", {}).get("priority") or {}
        return p.get("name", "None")

    @staticmethod
    def reporter(issue: dict) -> str:
        r = issue.get("fields", {}).get("reporter") or {}
        return r.get("displayName") or r.get("emailAddress", "Unknown")

    @staticmethod
    def assignee(issue: dict) -> str:
        a = issue.get("fields", {}).get("assignee") or {}
        return a.get("displayName") or a.get("emailAddress", "Unassigned")

    @staticmethod
    def created(issue: dict) -> str:
        return (issue.get("fields", {}).get("created") or "")[:10]

    @staticmethod
    def updated(issue: dict) -> str:
        return issue.get("fields", {}).get("updated") or ""

    @staticmethod
    def description_text(issue: dict) -> str:
        """Convert the description field to plain text.

        JIRA Cloud uses Atlassian Document Format (ADF) for rich text.
        This method extracts readable plain text from ADF nodes, or returns
        the raw value if it is already a string (JIRA Server / Data Center).
        """
        desc = issue.get("fields", {}).get("description")
        if desc is None:
            return "(No description provided)"
        if isinstance(desc, str):
            return desc.strip() or "(No description provided)"
        # ADF object
        return _adf_to_text(desc).strip() or "(No description provided)"

    def issue_url(self, issue: dict) -> str:
        key = self.issue_key(issue)
        return f"{self._base}/browse/{key}"


# ---------------------------------------------------------------------------
# Plain text → ADF  (for posting comments)
# ---------------------------------------------------------------------------

def _text_to_adf(text: str) -> dict:
    """Convert plain text (with basic markdown) to Atlassian Document Format.

    Handles:
    - Fenced code blocks (``` ... ```)
    - Double-newline paragraph breaks
    - Everything else becomes plain paragraph text
    """
    content = []
    # Split on blank lines to get blocks; handle code fences as a unit
    blocks: list[str] = []
    current: list[str] = []
    in_code = False
    for line in text.splitlines():
        if line.startswith("```"):
            if in_code:
                current.append(line)
                blocks.append("\n".join(current))
                current = []
                in_code = False
            else:
                if current:
                    blocks.append("\n".join(current))
                    current = []
                current.append(line)
                in_code = True
        elif in_code:
            current.append(line)
        elif line == "" and current:
            blocks.append("\n".join(current))
            current = []
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current))

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if block.startswith("```"):
            lines = block.splitlines()
            lang = lines[0][3:].strip() if len(lines) > 0 else ""
            code_body = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            node: dict = {"type": "codeBlock", "content": [{"type": "text", "text": code_body}]}
            if lang:
                node["attrs"] = {"language": lang}
            content.append(node)
        else:
            content.append({
                "type": "paragraph",
                "content": [{"type": "text", "text": block}],
            })

    if not content:
        content.append({"type": "paragraph", "content": [{"type": "text", "text": ""}]})

    return {"version": 1, "type": "doc", "content": content}


# ---------------------------------------------------------------------------
# ADF → plain text
# ---------------------------------------------------------------------------

def _adf_to_text(node: dict, indent: int = 0) -> str:
    """Recursively convert an ADF node tree to readable plain text."""
    if not isinstance(node, dict):
        return ""

    node_type = node.get("type", "")
    text = node.get("text", "")
    content = node.get("content", [])

    parts = []

    if node_type == "text":
        parts.append(text)
    elif node_type in ("paragraph", "blockquote"):
        inner = "".join(_adf_to_text(c) for c in content)
        parts.append(inner + "\n")
    elif node_type == "heading":
        inner = "".join(_adf_to_text(c) for c in content)
        level = node.get("attrs", {}).get("level", 1)
        parts.append("#" * level + " " + inner + "\n")
    elif node_type in ("bulletList", "orderedList"):
        for i, item in enumerate(content, 1):
            bullet = "-" if node_type == "bulletList" else f"{i}."
            inner = "".join(_adf_to_text(c) for c in item.get("content", []))
            parts.append(f"{' ' * indent}{bullet} {inner.strip()}\n")
    elif node_type == "listItem":
        parts.append("".join(_adf_to_text(c, indent + 2) for c in content))
    elif node_type == "codeBlock":
        lang = node.get("attrs", {}).get("language", "")
        inner = "".join(_adf_to_text(c) for c in content)
        parts.append(f"```{lang}\n{inner}\n```\n")
    elif node_type == "hardBreak":
        parts.append("\n")
    elif node_type == "rule":
        parts.append("---\n")
    elif node_type == "mention":
        display = node.get("attrs", {}).get("text", "@someone")
        parts.append(display)
    elif node_type == "inlineCard":
        url = node.get("attrs", {}).get("url", "")
        parts.append(f"[{url}]({url})")
    elif node_type == "link":
        href = node.get("attrs", {}).get("href", "")
        inner = "".join(_adf_to_text(c) for c in content)
        parts.append(f"[{inner}]({href})")
    elif node_type == "table":
        for row in content:
            cells = row.get("content", [])
            cell_texts = ["".join(_adf_to_text(c) for c in cell.get("content", [])) for cell in cells]
            parts.append(" | ".join(t.strip() for t in cell_texts) + "\n")
    else:
        # Unknown node — recurse into children
        parts.append("".join(_adf_to_text(c, indent) for c in content))

    return "".join(parts)


# ---------------------------------------------------------------------------
# Config helper
# ---------------------------------------------------------------------------

def create_jira_client(config: dict) -> JiraClient:
    """Factory function — reads config and env var for token."""
    return JiraClient.from_config(config)
