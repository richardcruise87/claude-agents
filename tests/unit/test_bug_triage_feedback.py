"""Unit tests for Launchpad feedback posting.

The handcrafted OAuth implementation has been replaced by launchpadlib
(agents_lib.launchpad_client). Tests now cover the new implementation and
the _post_bug_feedback helper in bug-triage-agent.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../bug-triage-agent'))

from bug_triage_agent import _post_bug_feedback
from agents_lib.launchpad_client import post_launchpad_comment, get_launchpad_bug_comments


class TestPostLaunchpadComment:
    """Tests for agents_lib.launchpad_client.post_launchpad_comment."""

    def test_returns_false_when_launchpadlib_missing(self, monkeypatch):
        """Missing launchpadlib should return False gracefully."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "launchpadlib.launchpad":
                raise ImportError("No module named 'launchpadlib'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        result = post_launchpad_comment("12345", "Subj", "Body", "ck", "at", "sec")
        assert result is False

    def test_returns_false_on_api_error(self, monkeypatch):
        """Errors from launchpadlib should return False, not raise."""
        # Patch at the point launchpadlib is imported
        class FakeLaunchpad:
            def __init__(self, *a, **k):
                raise RuntimeError("connection refused")

        class FakeCredentials:
            def __init__(self, *a, **k): pass
            access_token = None

        class FakeAccessToken:
            def __init__(self, *a): pass

        import types
        fake_mod = types.ModuleType("launchpadlib.launchpad")
        fake_mod.Launchpad = FakeLaunchpad
        fake_creds_mod = types.ModuleType("launchpadlib.credentials")
        fake_creds_mod.Credentials = FakeCredentials
        fake_creds_mod.AccessToken = FakeAccessToken

        monkeypatch.setitem(sys.modules, "launchpadlib.launchpad", fake_mod)
        monkeypatch.setitem(sys.modules, "launchpadlib.credentials", fake_creds_mod)

        result = post_launchpad_comment("12345", "Subj", "Body", "ck", "at", "sec")
        assert result is False


class TestGetLaunchpadBugComments:
    """Tests for agents_lib.launchpad_client.get_launchpad_bug_comments."""

    def test_returns_empty_on_network_error(self, monkeypatch):
        import urllib.request
        import urllib.error

        def fail(*a, **k):
            raise urllib.error.URLError("network error")

        monkeypatch.setattr(urllib.request, "urlopen", fail)
        result = get_launchpad_bug_comments("12345")
        assert result == []

    def test_filters_by_since_iso(self, monkeypatch):
        import json
        import urllib.request

        entries = [
            {"date_created": "2026-01-01T10:00:00", "content": "old", "owner_link": "a"},
            {"date_created": "2026-06-01T10:00:00", "content": "new", "owner_link": "b"},
        ]

        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self): return json.dumps({"entries": entries}).encode()

        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResp())
        result = get_launchpad_bug_comments("12345", since_iso="2026-03-01T00:00:00")
        assert len(result) == 1
        assert result[0]["content"] == "new"

    def test_returns_all_when_no_since(self, monkeypatch):
        import urllib.request
        import json

        entries = [
            {"date_created": "2026-01-01T10:00:00", "content": "a", "owner_link": "x"},
            {"date_created": "2026-06-01T10:00:00", "content": "b", "owner_link": "y"},
        ]

        class FakeResp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self): return json.dumps({"entries": entries}).encode()

        monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: FakeResp())
        result = get_launchpad_bug_comments("12345")
        assert len(result) == 2


class TestPostBugFeedback:
    _BUG_INFO = {"number": "12345", "title": "Test bug", "status": "New",
                 "importance": "Medium", "date_last_updated": "2026-04-01"}

    def _config(self, enabled=True):
        return {
            "feedback_enabled": enabled,
            "feedback_consumer_key_env": "LP_CK",
            "feedback_access_token_env": "LP_AT",
            "feedback_access_token_secret_env": "LP_ATS",
            "model": "claude-sonnet-4-6",
        }

    def test_skips_when_disabled(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LP_CK", "ck")
        monkeypatch.setenv("LP_AT", "at")
        monkeypatch.setenv("LP_ATS", "ats")

        called = []
        # Patch the name as imported into bug_triage_agent
        monkeypatch.setattr("bug_triage_agent.post_launchpad_comment",
                            lambda *a, **k: called.append(True) or True)

        report = tmp_path / "report.md"
        report.write_text("# Report\n\nSome content.", encoding="utf-8")
        _post_bug_feedback(self._BUG_INFO, report, self._config(enabled=False))
        assert len(called) == 0

    def test_skips_when_credentials_missing(self, monkeypatch, tmp_path):
        monkeypatch.delenv("LP_CK", raising=False)
        monkeypatch.delenv("LP_AT", raising=False)
        monkeypatch.delenv("LP_ATS", raising=False)

        called = []
        monkeypatch.setattr("bug_triage_agent.post_launchpad_comment",
                            lambda *a, **k: called.append(True) or True)

        report = tmp_path / "report.md"
        report.write_text("# Report\n\nContent.", encoding="utf-8")
        _post_bug_feedback(self._BUG_INFO, report, self._config(enabled=True))
        assert len(called) == 0

    def test_calls_post_when_enabled_with_credentials(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LP_CK", "consumer-key")
        monkeypatch.setenv("LP_AT", "access-token")
        monkeypatch.setenv("LP_ATS", "token-secret")

        posted = {}

        def fake_post(bug_id, subject, content, consumer_key, access_token, token_secret):
            posted.update({"bug_id": bug_id, "subject": subject,
                           "consumer_key": consumer_key, "access_token": access_token})
            return True

        monkeypatch.setattr("bug_triage_agent.post_launchpad_comment", fake_post)

        report = tmp_path / "report.md"
        report.write_text("# Report\n\nThe bug is real.\n", encoding="utf-8")
        _post_bug_feedback(self._BUG_INFO, report, self._config(enabled=True))
        assert posted["bug_id"] == "12345"
        assert posted["consumer_key"] == "consumer-key"
        assert posted["access_token"] == "access-token"
        assert "AI Triage Report" in posted["subject"]
