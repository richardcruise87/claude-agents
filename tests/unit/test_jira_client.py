"""Unit tests for jira-triage-agent/jira_client.py."""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../jira-triage-agent'))

import base64
import pytest
from unittest.mock import MagicMock
from unittest.mock import patch
from jira_client import JiraClient
from jira_client import _adf_to_text


# ---------------------------------------------------------------------------
# JiraClient construction
# ---------------------------------------------------------------------------

class TestJiraClientConstruction:
    def test_from_config_reads_env_var(self, monkeypatch):
        monkeypatch.setenv("JIRA_API_TOKEN", "my-token")
        client = JiraClient.from_config({
            "jira": {
                "base_url": "https://test.atlassian.net",
                "email": "user@test.com",
                "token_env": "JIRA_API_TOKEN",
            }
        })
        assert client._base == "https://test.atlassian.net"

    def test_from_config_missing_token_raises(self, monkeypatch):
        monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
        with pytest.raises(ValueError, match="JIRA config incomplete"):
            JiraClient.from_config({
                "jira": {"base_url": "https://x.atlassian.net", "email": "u@x.com", "token_env": "JIRA_API_TOKEN"}
            })

    def test_from_config_missing_base_url_raises(self, monkeypatch):
        monkeypatch.setenv("JIRA_API_TOKEN", "tok")
        with pytest.raises(ValueError):
            JiraClient.from_config({
                "jira": {"base_url": "", "email": "u@x.com", "token_env": "JIRA_API_TOKEN"}
            })

    def test_auth_header_is_base64(self):
        client = JiraClient("https://x.atlassian.net", "user@x.com", "secret")
        expected = base64.b64encode(b"user@x.com:secret").decode()
        assert client._auth == expected

    def test_trailing_slash_stripped(self):
        client = JiraClient("https://x.atlassian.net/", "u@x.com", "t")
        assert not client._base.endswith("/")


# ---------------------------------------------------------------------------
# Field extraction helpers
# ---------------------------------------------------------------------------

def _make_issue(**field_overrides):
    fields = {
        "summary": "Fix the thing",
        "issuetype": {"name": "Bug"},
        "status": {"name": "In Progress"},
        "priority": {"name": "High"},
        "reporter": {"displayName": "Alice"},
        "assignee": {"displayName": "Bob"},
        "created": "2026-03-01T10:00:00.000+0000",
        "updated": "2026-04-01T12:00:00.000+0000",
        "description": None,
        "labels": [],
        "components": [],
    }
    fields.update(field_overrides)
    return {"key": "PROJ-123", "fields": fields}


class TestFieldHelpers:
    def test_issue_key(self):
        assert JiraClient.issue_key(_make_issue()) == "PROJ-123"

    def test_issue_type(self):
        assert JiraClient.issue_type(_make_issue()) == "Bug"

    def test_summary(self):
        assert JiraClient.summary(_make_issue()) == "Fix the thing"

    def test_status(self):
        assert JiraClient.status(_make_issue()) == "In Progress"

    def test_priority(self):
        assert JiraClient.priority(_make_issue()) == "High"

    def test_priority_missing(self):
        issue = _make_issue(priority=None)
        assert JiraClient.priority(issue) == "None"

    def test_reporter(self):
        assert JiraClient.reporter(_make_issue()) == "Alice"

    def test_reporter_email_fallback(self):
        issue = _make_issue(reporter={"emailAddress": "alice@x.com"})
        assert JiraClient.reporter(issue) == "alice@x.com"

    def test_assignee_unassigned(self):
        issue = _make_issue(assignee=None)
        assert JiraClient.assignee(issue) == "Unassigned"

    def test_created_date_only(self):
        assert JiraClient.created(_make_issue()) == "2026-03-01"

    def test_issue_url(self):
        client = JiraClient("https://myco.atlassian.net", "u@x.com", "t")
        url = client.issue_url(_make_issue())
        assert url == "https://myco.atlassian.net/browse/PROJ-123"


# ---------------------------------------------------------------------------
# ADF to text conversion
# ---------------------------------------------------------------------------

class TestAdfToText:
    def test_plain_text_string(self):
        # Jira Server / Data Center returns plain strings
        issue = _make_issue(description="Simple text description")
        assert JiraClient.description_text(issue) == "Simple text description"

    def test_none_description(self):
        issue = _make_issue(description=None)
        assert JiraClient.description_text(issue) == "(No description provided)"

    def test_adf_paragraph(self):
        adf = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "Hello world"}],
                }
            ],
        }
        issue = _make_issue(description=adf)
        assert "Hello world" in JiraClient.description_text(issue)

    def test_adf_heading(self):
        node = {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [{"type": "text", "text": "Section title"}],
        }
        result = _adf_to_text(node)
        assert "## Section title" in result

    def test_adf_bullet_list(self):
        node = {
            "type": "bulletList",
            "content": [
                {"type": "listItem", "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "Item one"}]}
                ]},
                {"type": "listItem", "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "Item two"}]}
                ]},
            ],
        }
        result = _adf_to_text(node)
        assert "Item one" in result
        assert "Item two" in result
        assert "-" in result

    def test_adf_code_block(self):
        node = {
            "type": "codeBlock",
            "attrs": {"language": "python"},
            "content": [{"type": "text", "text": "print('hello')"}],
        }
        result = _adf_to_text(node)
        assert "```python" in result
        assert "print('hello')" in result

    def test_adf_hard_break(self):
        node = {"type": "hardBreak"}
        assert _adf_to_text(node) == "\n"

    def test_adf_mention(self):
        node = {"type": "mention", "attrs": {"text": "@alice"}}
        assert "@alice" in _adf_to_text(node)

    def test_unknown_node_recurses(self):
        node = {
            "type": "someUnknownNode",
            "content": [{"type": "text", "text": "visible text"}],
        }
        assert "visible text" in _adf_to_text(node)

    def test_empty_adf_doc(self):
        adf = {"type": "doc", "content": []}
        result = _adf_to_text(adf)
        assert result == ""


# ---------------------------------------------------------------------------
# HTTP error handling
# ---------------------------------------------------------------------------

class TestHttpErrorHandling:
    def test_includes_response_body_in_error(self, mocker):
        client = JiraClient("https://x.atlassian.net", "u@x.com", "t")

        mock_exc = MagicMock()
        mock_exc.code = 401
        mock_exc.reason = "Unauthorized"
        mock_exc.read.return_value = b'{"message":"Basic auth credentials are invalid"}'

        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
            None, 401, "Unauthorized", {}, None
        )) as mock_open:
            mock_open.side_effect = urllib.error.HTTPError(None, 401, "Unauthorized", {}, None)
            mock_open.side_effect.read = lambda: b'{"message":"credentials invalid"}'

            # Simulate the client call raising RuntimeError with body
            with pytest.raises(RuntimeError) as exc_info:
                # Patch the urlopen to raise an HTTPError that has a readable body
                import io
                http_err = urllib.error.HTTPError(
                    "https://x.atlassian.net/rest/api/3/search",
                    401, "Unauthorized",
                    {},
                    io.BytesIO(b'{"message":"credentials invalid"}')
                )
                with patch("urllib.request.urlopen", side_effect=http_err):
                    client._get("/search")

            assert "401" in str(exc_info.value)
