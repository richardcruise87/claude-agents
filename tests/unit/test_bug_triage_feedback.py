"""Unit tests for Launchpad feedback posting in bug-triage-agent."""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../bug-triage-agent'))

from bug_triage_agent import _launchpad_auth_header, _post_launchpad_comment, _post_bug_feedback


class TestLaunchpadAuthHeader:
    def _header(self):
        return _launchpad_auth_header(
            "POST", "https://api.launchpad.net/1.0/bugs/12345/messages",
            "my-app", "acc-token", "acc-secret",
        )

    def test_starts_with_oauth(self):
        assert self._header().startswith("OAuth ")

    def test_contains_consumer_key(self):
        assert "my-app" in self._header()

    def test_contains_access_token(self):
        assert "acc-token" in self._header()

    def test_contains_hmac_sha1_method(self):
        assert "HMAC-SHA1" in self._header()

    def test_contains_signature(self):
        assert "oauth_signature" in self._header()

    def test_different_nonces_each_call(self):
        h1 = self._header()
        h2 = self._header()
        # oauth_nonce should differ between calls
        nonce1 = [p for p in h1.split(", ") if "nonce" in p][0]
        nonce2 = [p for p in h2.split(", ") if "nonce" in p][0]
        assert nonce1 != nonce2


class TestPostLaunchpadComment:
    def test_returns_false_on_http_error(self, monkeypatch):
        import urllib.error
        import urllib.request

        def fake_urlopen(req, timeout=30):
            raise urllib.error.HTTPError(
                None, 401, "Unauthorized", {}, None
            )

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        result = _post_launchpad_comment(
            "12345", "Subject", "Body", "app", "tok", "sec"
        )
        assert result is False

    def test_returns_false_on_network_error(self, monkeypatch):
        import urllib.error
        import urllib.request

        def fake_urlopen(req, timeout=30):
            raise urllib.error.URLError("connection refused")

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        result = _post_launchpad_comment(
            "12345", "Subject", "Body", "app", "tok", "sec"
        )
        assert result is False

    def test_posts_to_correct_url(self, monkeypatch):
        import urllib.request

        captured = {}

        class FakeResponse:
            status = 201
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self): return b"{}"

        def fake_urlopen(req, timeout=30):
            captured["url"] = req.full_url
            captured["method"] = req.method
            return FakeResponse()

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        _post_launchpad_comment("99999", "Subj", "Body", "app", "tok", "sec")
        assert "bugs/99999/messages" in captured["url"]
        assert captured["method"] == "POST"

    def test_includes_subject_and_content(self, monkeypatch):
        import urllib.parse
        import urllib.request

        captured = {}

        class FakeResponse:
            status = 201
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self): return b"{}"

        def fake_urlopen(req, timeout=30):
            captured["body"] = req.data
            return FakeResponse()

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        _post_launchpad_comment("1", "My Subject", "My Content", "app", "tok", "sec")
        body_str = captured["body"].decode("utf-8")
        params = dict(urllib.parse.parse_qsl(body_str))
        assert params.get("subject") == "My Subject"
        assert params.get("content") == "My Content"


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

        def fake_post(*args, **kwargs):
            called.append(True)
            return True

        monkeypatch.setattr(
            "bug_triage_agent._post_launchpad_comment", fake_post
        )

        report = tmp_path / "report.md"
        report.write_text("# Report\n\nSome content.", encoding="utf-8")

        _post_bug_feedback(self._BUG_INFO, report, self._config(enabled=False))
        assert len(called) == 0

    def test_skips_when_credentials_missing(self, monkeypatch, tmp_path):
        monkeypatch.delenv("LP_CK", raising=False)
        monkeypatch.delenv("LP_AT", raising=False)
        monkeypatch.delenv("LP_ATS", raising=False)

        called = []

        def fake_post(*args, **kwargs):
            called.append(True)
            return True

        monkeypatch.setattr(
            "bug_triage_agent._post_launchpad_comment", fake_post
        )

        report = tmp_path / "report.md"
        report.write_text("# Report\n\nContent.", encoding="utf-8")

        _post_bug_feedback(self._BUG_INFO, report, self._config(enabled=True))
        assert len(called) == 0

    def test_calls_post_when_enabled_with_credentials(self, monkeypatch, tmp_path):
        monkeypatch.setenv("LP_CK", "consumer-key")
        monkeypatch.setenv("LP_AT", "access-token")
        monkeypatch.setenv("LP_ATS", "token-secret")

        posted = {}

        def fake_post(bug_id, subject, content, ck, at, ats):
            posted.update({"bug_id": bug_id, "subject": subject,
                           "consumer_key": ck, "access_token": at})
            return True

        monkeypatch.setattr(
            "bug_triage_agent._post_launchpad_comment", fake_post
        )

        report = tmp_path / "report.md"
        report.write_text("# Report\n\nThe bug is real.\n", encoding="utf-8")

        _post_bug_feedback(self._BUG_INFO, report, self._config(enabled=True))
        assert posted["bug_id"] == "12345"
        assert posted["consumer_key"] == "consumer-key"
        assert posted["access_token"] == "access-token"
        assert "AI Triage Report" in posted["subject"]
