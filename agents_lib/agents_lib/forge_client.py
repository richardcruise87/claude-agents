"""
Forge client abstraction for code-review operations.

Provides a unified interface for Gerrit, GitHub, and GitLab so the
code-review agent can work with any of the three without code changes —
only a config switch is needed.

Usage:
    from agents_lib import create_forge_client
    forge = create_forge_client(config)
    changes = forge.list_open_changes("openstack/octavia", since="2026-01-01")
    change  = forge.get_change("982567")
"""

import base64
import json
import os
import re
import urllib.request
import urllib.parse
import urllib.error
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Shared dataclasses
# ---------------------------------------------------------------------------

@dataclass
class LineComment:
    """A review comment anchored to a specific line in a file."""

    file_path: str
    line: int
    message: str
    line_end: Optional[int] = None  # for range references e.g. Lines 10-15


@dataclass
class ChangeInfo:
    """Normalised representation of a Gerrit change / GitHub PR / GitLab MR."""

    change_id: str          # PR/MR number or Gerrit change number (string)
    repo_name: str          # "owner/repo" or "namespace/project"
    title: str
    branch: str             # target branch (e.g. "main", "master")
    created_at: str         # ISO-8601 timestamp
    updated_at: str         # ISO-8601 timestamp
    head_sha: str           # current HEAD commit SHA
    patchset: Optional[int]  # Gerrit only; None for GitHub/GitLab
    git_fetch_ref: str  # ref to pass to "git fetch origin <ref>"
    forge_url: str          # URL to view the change in a browser
    author: str
    forge_type: str  # "gerrit" | "github" | "gitlab"
    description: str = ""   # PR/MR body / Gerrit change description


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class ForgeClient:
    """Abstract base class for forge API clients."""

    def list_open_changes(
        self,
        repo: str,
        since: Optional[str] = None,
        max_results: int = 50,
    ) -> list[ChangeInfo]:
        """List open changes/PRs/MRs for a repository.

        Args:
            repo:        Repository in "owner/repo" or "namespace/project" format.
            since:       ISO date string — skip changes created before this date.
            max_results: Maximum number of results to return.
        """
        raise NotImplementedError

    def get_change(
        self,
        change_id: str,
        repo: Optional[str] = None,
    ) -> ChangeInfo:
        """Fetch details for a single change/PR/MR by ID or number.

        Args:
            change_id: Gerrit change number, GitHub PR number, or GitLab MR IID.
            repo:      Required for GitHub/GitLab; optional for Gerrit.
        """
        raise NotImplementedError

    def get_change_from_url(self, url: str) -> ChangeInfo:
        """Fetch details for a change given its web URL.

        Parses the repo and change ID from the URL, then delegates to get_change().
        """
        raise NotImplementedError

    def post_feedback(
        self,
        change_info: ChangeInfo,
        comment: str,
        vote: Optional[int] = None,
        line_comments: Optional[list] = None,
    ) -> bool:
        """Post review feedback to the forge.

        Args:
            change_info:   The change to post feedback on.
            comment:       Overall review comment (summary text).
            vote:          Numeric vote: +1 approve, -1 reject, 0 neutral.
                           None means no vote (comment only).
            line_comments: Optional list of LineComment objects for inline comments.

        Returns:
            True on success, False on failure.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Shared HTTP helpers
    # ------------------------------------------------------------------

    def _http_get(self, url: str, headers: Optional[dict] = None) -> dict | list[dict]:
        """Perform a GET request and return parsed JSON."""
        req = urllib.request.Request(url, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # Include the response body when available — APIs often return
            # a JSON error message that explains the failure in detail.
            try:
                body = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                body = ""
            detail = f" — {body}" if body else ""
            raise RuntimeError(
                f"HTTP {exc.code} fetching {url}: {exc.reason}{detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Network error fetching {url}: {exc.reason}") from exc

    def _http_post(self, url: str, data: dict, headers: Optional[dict] = None) -> dict:
        """Perform a POST request with a JSON body and return parsed JSON response."""
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            try:
                body_txt = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                body_txt = ""
            detail = f" — {body_txt}" if body_txt else ""
            raise RuntimeError(
                f"HTTP {exc.code} posting to {url}: {exc.reason}{detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Network error posting to {url}: {exc.reason}") from exc


# ---------------------------------------------------------------------------
# Gerrit
# ---------------------------------------------------------------------------

class GerritClient(ForgeClient):
    """Gerrit REST API client."""

    def __init__(self, base_url: str, token_env: Optional[str] = None,
                 username_env: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self._token = os.environ.get(token_env) if token_env else None
        # username_env enables HTTP Basic auth (Gerrit username + HTTP password).
        # If set, the token is used as the HTTP password rather than as Bearer.
        self._username = os.environ.get(username_env) if username_env else None

    def _headers(self) -> dict:
        h = {"Accept": "application/json"}
        if self._username and self._token:
            # HTTP Basic auth: required for most self-hosted Gerrit instances
            creds = base64.b64encode(f"{self._username}:{self._token}".encode()).decode()
            h["Authorization"] = f"Basic {creds}"
        elif self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _strip_prefix(self, text: str) -> str:
        """Gerrit prepends )]}' to all JSON responses."""
        if text.startswith(")]}'"):
            text = text[4:]
        elif text.startswith(")]}"):
            text = text[3:]
        return text.lstrip("\n")

    def _http_get_gerrit(self, url: str) -> dict | list:
        req = urllib.request.Request(url, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(self._strip_prefix(raw))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Gerrit HTTP {exc.code} for {url}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Gerrit network error for {url}: {exc.reason}") from exc

    @staticmethod
    def _build_fetch_ref(change_number: str, patchset: int) -> str:
        last2 = str(change_number)[-2:].zfill(2)
        return f"refs/changes/{last2}/{change_number}/{patchset}"

    def _parse_change(self, data: dict) -> ChangeInfo:
        change_number = str(data.get("_number", ""))
        current_sha = data.get("current_revision", "")
        revisions = data.get("revisions", {})

        patchset = None
        git_ref = ""
        if current_sha and current_sha in revisions:
            rev = revisions[current_sha]
            patchset = rev.get("_number")
            git_ref = rev.get("ref", "")

        if not git_ref and change_number and patchset:
            git_ref = self._build_fetch_ref(change_number, patchset)

        repo = data.get("project", "")
        owner = data.get("owner", {})
        author = owner.get("name") or owner.get("username") or owner.get("email", "unknown")

        return ChangeInfo(
            change_id=change_number,
            repo_name=repo,
            title=data.get("subject", ""),
            branch=data.get("branch", ""),
            created_at=data.get("created", "").replace(" ", "T"),
            updated_at=data.get("updated", "").replace(" ", "T"),
            head_sha=current_sha,
            patchset=patchset,
            git_fetch_ref=git_ref,
            forge_url=(
                f"{self.base_url}/c/{repo}/+/{change_number}"
            ),
            author=author,
            forge_type="gerrit",
            description=data.get("commit_message", ""),
        )

    def list_open_changes(
        self,
        repo: str,
        since: Optional[str] = None,
        max_results: int = 50,
    ) -> list[ChangeInfo]:
        age_filter = ""
        if since:
            # Gerrit uses -age:Nd syntax; convert ISO date to days-ago estimate
            # Simpler: just request all open and filter by created_at below
            age_filter = "+-age:365d"

        # Build q separately — Gerrit needs :, +, / unencoded in its query syntax
        q = f"project:{repo}+status:open{age_filter}"
        other = urllib.parse.urlencode({
            "o": ["CURRENT_REVISION", "DETAILED_ACCOUNTS"],
            "n": max_results,
        }, doseq=True)
        url = f"{self.base_url}/changes/?q={q}&{other}"
        data = self._http_get_gerrit(url)

        changes = []
        for item in (data if isinstance(data, list) else [data]):
            try:
                ci = self._parse_change(item)
                if since and ci.created_at[:10] < since[:10]:
                    continue
                changes.append(ci)
            except Exception:
                continue
        return changes

    def get_change(self, change_id: str, repo: Optional[str] = None) -> ChangeInfo:
        params = urllib.parse.urlencode({"o": ["CURRENT_REVISION", "ALL_REVISIONS"]}, doseq=True)
        url = f"{self.base_url}/changes/{change_id}?{params}"
        data = self._http_get_gerrit(url)
        if isinstance(data, list):
            data = data[0]
        return self._parse_change(data)

    def get_change_from_url(self, url: str) -> ChangeInfo:
        # e.g. https://review.opendev.org/c/openstack/octavia/+/982567
        m = re.search(r'/c/.+/\+/(\d+)', url)
        if not m:
            m = re.search(r'(\d+)\s*$', url)
        if not m:
            raise ValueError(f"Cannot extract change number from URL: {url}")
        return self.get_change(m.group(1))

    def _http_post_gerrit(self, url: str, data: dict) -> dict:
        """POST to Gerrit, stripping the )]}' security prefix from the response."""
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        for k, v in self._headers().items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read().decode("utf-8")
                raw = self._strip_prefix(raw)
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            try:
                body_txt = exc.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                body_txt = ""
            detail = f" — {body_txt}" if body_txt else ""
            raise RuntimeError(
                f"HTTP {exc.code} posting to {url}: {exc.reason}{detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Network error posting to {url}: {exc.reason}") from exc

    def _gerrit_review_url(self, change_id: str) -> str:
        return f"{self.base_url}/a/changes/{change_id}/revisions/current/review"

    def _build_gerrit_comments(self, line_comments: list) -> dict:
        comments_by_file: dict = {}
        for lc in line_comments:
            entry = {"message": lc.message}
            if lc.line_end:
                entry["range"] = {
                    "start_line": lc.line,
                    "end_line": lc.line_end,
                    "start_character": 0,
                    "end_character": 0,
                }
            else:
                entry["line"] = lc.line
            comments_by_file.setdefault(lc.file_path, []).append(entry)
        return comments_by_file

    def post_feedback(
        self,
        change_info: ChangeInfo,
        comment: str,
        vote: Optional[int] = None,
        line_comments: Optional[list] = None,
    ) -> bool:
        url = self._gerrit_review_url(change_info.change_id)
        payload: dict = {
            "tag": "autogenerated:claude-review",
            "message": comment,
        }
        if vote is not None:
            payload["labels"] = {"Code-Review": vote}
        if line_comments:
            payload["comments"] = self._build_gerrit_comments(line_comments)

        try:
            self._http_post_gerrit(url, payload)
            return True
        except RuntimeError as exc:
            if "400" in str(exc) and line_comments:
                # A file referenced in line comments may not be in this revision's
                # diff. Fall back: post the overall comment + vote without any
                # inline comments.
                #
                # Per-file retry is intentionally avoided: each per-file request
                # creates a separate review entry in the Gerrit UI (showing only
                # "(N comments)" with no visible body), cluttering the change with
                # multiple empty-looking review rounds.
                print("⚠️  Inline comments rejected (likely stale file path) — "
                      "posting summary only")
                n = len(line_comments)
                print(f"   ℹ️  {n} inline comment(s) not posted; "
                      "they may reference files not in this revision's diff")
                base_payload = {k: v for k, v in payload.items() if k != "comments"}
                try:
                    self._http_post_gerrit(url, base_payload)
                    return True
                except RuntimeError as exc2:
                    print(f"⚠️  Gerrit feedback post failed: {exc2}")
                    return False
            print(f"⚠️  Gerrit feedback post failed: {exc}")
            return False


# ---------------------------------------------------------------------------
# GitHub
# ---------------------------------------------------------------------------

class GitHubClient(ForgeClient):
    """GitHub REST API client."""

    API = "https://api.github.com"

    def __init__(self, base_url: str = "https://api.github.com", token_env: Optional[str] = "GITHUB_TOKEN"):
        self._api = base_url.rstrip("/")
        self._token = os.environ.get(token_env or "GITHUB_TOKEN")

    def _headers(self) -> dict:
        h = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _get(self, path: str) -> dict | list:
        url = path if path.startswith("http") else f"{self._api}{path}"
        return self._http_get(url, self._headers())

    def _parse_pr(self, data: dict) -> ChangeInfo:
        pr_num = str(data["number"])
        repo_full = data["base"]["repo"]["full_name"]
        head_sha = data["head"]["sha"]
        return ChangeInfo(
            change_id=pr_num,
            repo_name=repo_full,
            title=data.get("title", ""),
            branch=data["base"]["ref"],
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            head_sha=head_sha,
            patchset=None,
            git_fetch_ref=f"refs/pull/{pr_num}/head",
            forge_url=data.get("html_url", ""),
            author=data.get("user", {}).get("login", "unknown"),
            forge_type="github",
            description=data.get("body") or "",
        )

    def list_open_changes(
        self,
        repo: str,
        since: Optional[str] = None,
        max_results: int = 50,
    ) -> list[ChangeInfo]:
        per_page = min(max_results, 100)
        prs = self._get(f"/repos/{repo}/pulls?state=open&per_page={per_page}&sort=updated&direction=desc")
        changes = []
        for pr in (prs if isinstance(prs, list) else []):
            try:
                ci = self._parse_pr(pr)
                if since and ci.created_at[:10] < since[:10]:
                    continue
                changes.append(ci)
                if len(changes) >= max_results:
                    break
            except Exception:
                continue
        return changes

    def get_change(self, change_id: str, repo: Optional[str] = None) -> ChangeInfo:
        if not repo:
            raise ValueError("repo is required for GitHubClient.get_change()")
        data = self._get(f"/repos/{repo}/pulls/{change_id}")
        return self._parse_pr(data)

    def get_change_from_url(self, url: str) -> ChangeInfo:
        # Matches github.com and GitHub Enterprise (github.company.com)
        m = re.search(r'github[^/]*/([^/]+/[^/]+)/pull/(\d+)', url)
        if not m:
            raise ValueError(f"Cannot parse GitHub PR URL: {url}")
        repo, pr = m.group(1), m.group(2)
        return self.get_change(pr, repo)

    def post_feedback(
        self,
        change_info: ChangeInfo,
        comment: str,
        vote: Optional[int] = None,
        line_comments: Optional[list] = None,
    ) -> bool:
        if vote is not None and vote > 0:
            event = "APPROVE"
        elif vote is not None and vote < 0:
            event = "REQUEST_CHANGES"
        else:
            event = "COMMENT"

        payload: dict = {
            "commit_id": change_info.head_sha,
            "body": comment,
            "event": event,
        }
        if line_comments:
            payload["comments"] = [
                {
                    "path": lc.file_path,
                    "line": lc.line,
                    "body": lc.message,
                }
                for lc in line_comments
            ]

        repo = change_info.repo_name
        pr = change_info.change_id
        url = f"{self._api}/repos/{repo}/pulls/{pr}/reviews"
        try:
            self._http_post(url, payload, self._headers())
            return True
        except RuntimeError as exc:
            print(f"⚠️  GitHub feedback post failed: {exc}")
            return False


# ---------------------------------------------------------------------------
# GitLab
# ---------------------------------------------------------------------------

class GitLabClient(ForgeClient):
    """GitLab REST API client."""

    def __init__(self, base_url: str = "https://gitlab.com", token_env: Optional[str] = "GITLAB_TOKEN"):
        self._base = base_url.rstrip("/")
        self._api = f"{self._base}/api/v4"
        self._token = os.environ.get(token_env or "GITLAB_TOKEN")

    def _headers(self) -> dict:
        h = {"Accept": "application/json"}
        if self._token:
            h["PRIVATE-TOKEN"] = self._token
        return h

    def _get(self, path: str) -> dict | list:
        url = path if path.startswith("http") else f"{self._api}{path}"
        return self._http_get(url, self._headers())

    @staticmethod
    def _encode_path(repo: str) -> str:
        return urllib.parse.quote(repo, safe="")

    def _parse_mr(self, data: dict, repo: str) -> ChangeInfo:
        mr_iid = str(data["iid"])
        head_sha = data.get("sha", "")
        return ChangeInfo(
            change_id=mr_iid,
            repo_name=repo,
            title=data.get("title", ""),
            branch=data.get("target_branch", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            head_sha=head_sha,
            patchset=None,
            git_fetch_ref=f"refs/merge-requests/{mr_iid}/head",
            forge_url=data.get("web_url", ""),
            author=data.get("author", {}).get("name") or data.get("author", {}).get("username", "unknown"),
            forge_type="gitlab",
            description=data.get("description") or "",
        )

    def list_open_changes(
        self,
        repo: str,
        since: Optional[str] = None,
        max_results: int = 50,
    ) -> list[ChangeInfo]:
        per_page = min(max_results, 100)
        path = f"/projects/{self._encode_path(repo)}/merge_requests"
        mrs = self._get(f"{path}?state=opened&per_page={per_page}&order_by=updated_at&sort=desc")
        changes = []
        for mr in (mrs if isinstance(mrs, list) else []):
            try:
                ci = self._parse_mr(mr, repo)
                if since and ci.created_at[:10] < since[:10]:
                    continue
                changes.append(ci)
                if len(changes) >= max_results:
                    break
            except Exception:
                continue
        return changes

    def get_change(self, change_id: str, repo: Optional[str] = None) -> ChangeInfo:
        if not repo:
            raise ValueError("repo is required for GitLabClient.get_change()")
        path = f"/projects/{self._encode_path(repo)}/merge_requests/{change_id}"
        data = self._get(path)
        return self._parse_mr(data, repo)

    def get_change_from_url(self, url: str) -> ChangeInfo:
        # https://gitlab.com/namespace/project/-/merge_requests/456
        m = re.search(r'gitlab[^/]*/([^/]+/[^/]+)/-/merge_requests/(\d+)', url)
        if not m:
            raise ValueError(f"Cannot parse GitLab MR URL: {url}")
        repo, mr = m.group(1), m.group(2)
        return self.get_change(mr, repo)

    def post_feedback(
        self,
        change_info: ChangeInfo,
        comment: str,
        vote: Optional[int] = None,
        line_comments: Optional[list] = None,
    ) -> bool:
        encoded = self._encode_path(change_info.repo_name)
        iid = change_info.change_id
        base_mr = f"{self._api}/projects/{encoded}/merge_requests/{iid}"
        success = True

        # Post the overall comment as a note
        try:
            self._http_post(f"{base_mr}/notes", {"body": comment}, self._headers())
        except RuntimeError as exc:
            print(f"⚠️  GitLab note post failed: {exc}")
            success = False

        # Post inline comments as discussions with position
        for lc in (line_comments or []):
            discussion_payload = {
                "body": lc.message,
                "position": {
                    "position_type": "text",
                    "base_sha": change_info.head_sha,
                    "start_sha": change_info.head_sha,
                    "head_sha": change_info.head_sha,
                    "new_path": lc.file_path,
                    "new_line": lc.line,
                },
            }
            try:
                self._http_post(f"{base_mr}/discussions", discussion_payload, self._headers())
            except RuntimeError as exc:
                print(f"⚠️  GitLab inline comment failed for {lc.file_path}:{lc.line}: {exc}")
                success = False

        # Handle voting via approve/unapprove
        if vote is not None:
            try:
                if vote > 0:
                    self._http_post(f"{base_mr}/approve", {}, self._headers())
                elif vote < 0:
                    self._http_post(f"{base_mr}/unapprove", {}, self._headers())
            except RuntimeError as exc:
                print(f"⚠️  GitLab vote failed: {exc}")
                success = False

        return success


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_forge_client(config: dict) -> ForgeClient:
    """Create the appropriate ForgeClient from an agent config dict.

    Reads config["forge"]["type"] (or infers from base_url).
    Falls back to Gerrit using config["gerrit"]["base_url"] for backward
    compatibility with existing config.json files that predate the forge section.
    """
    forge_cfg = config.get("forge", {})
    forge_type = forge_cfg.get("type") or config.get("forge_type", "")
    base_url = forge_cfg.get("base_url") or config.get("forge_base_url", "")
    token_env = forge_cfg.get("token_env") or config.get("forge_token_env")
    username_env = forge_cfg.get("username_env") or config.get("forge_username_env")

    # Backward compat: no forge section → use gerrit.base_url
    if not base_url:
        gerrit_cfg = config.get("gerrit", {})
        base_url = gerrit_cfg.get("base_url") or config.get("gerrit_base_url", "https://review.opendev.org")

    # Infer type from URL if not explicit
    if not forge_type:
        url_lower = base_url.lower()
        if "github" in url_lower:
            forge_type = "github"
        elif "gitlab" in url_lower:
            forge_type = "gitlab"
        else:
            forge_type = "gerrit"

    if forge_type == "github":
        return GitHubClient(base_url, token_env)
    if forge_type == "gitlab":
        return GitLabClient(base_url, token_env)
    return GerritClient(base_url, token_env, username_env)
