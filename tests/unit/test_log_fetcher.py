"""Unit tests for fetch_log_section() in agents_lib.log_fetcher."""
import gzip
import io
import urllib.error
from unittest.mock import MagicMock
import pytest
from agents_lib.log_fetcher import fetch_log_section, _tail

MODULE = "agents_lib.log_fetcher"


def _make_response(body: bytes, url: str = "http://example.com/log"):
    """Return a mock context-manager response that yields body bytes."""
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="http://x", code=code, msg="err", hdrs=None, fp=None
    )


class TestTail:
    """Unit tests for the internal _tail() helper."""

    def test_returns_text_unchanged_when_short(self):
        text = "line1\nline2\nline3"
        assert _tail(text, 10) == text

    def test_truncates_to_last_n_lines(self):
        text = "\n".join(f"line{i}" for i in range(20))
        result = _tail(text, 5)
        lines = result.splitlines()
        # Last 5 of 20 lines → lines 15..19
        assert "line19" in lines
        assert "line15" in lines
        assert "line14" not in result  # first line before the kept window

    def test_adds_omission_note_when_truncated(self):
        text = "\n".join(f"line{i}" for i in range(20))
        result = _tail(text, 5)
        assert "omitted" in result.lower() or "..." in result

    def test_omission_note_states_dropped_count(self):
        lines = [f"line{i}" for i in range(20)]
        result = _tail("\n".join(lines), 5)
        assert "15" in result  # 20 - 5 dropped lines

    def test_exact_n_lines_not_truncated(self):
        text = "\n".join(f"line{i}" for i in range(5))
        result = _tail(text, 5)
        assert "omitted" not in result.lower()
        assert result == text


class TestFetchLogSection:
    """Tests for fetch_log_section(), mocking urllib.request.urlopen."""

    # ----------------------------------------------------------- plain text success

    def test_returns_true_and_content_on_200(self, mocker):
        body = b"line1\nline2\nline3\n"
        mocker.patch(f"{MODULE}.urllib.request.urlopen",
                     return_value=_make_response(body))
        ok, content = fetch_log_section("http://logs.example.com/job-output.txt")
        assert ok is True
        assert "line1" in content
        assert "line3" in content

    def test_plain_url_tried_before_gz(self, mocker):
        """Plain URL is the first attempt; .gz fallback is second."""
        body = b"success content\n"
        mock_open = mocker.patch(f"{MODULE}.urllib.request.urlopen",
                                 return_value=_make_response(body))
        fetch_log_section("http://example.com/job-output.txt")
        first_url = mock_open.call_args_list[0][0][0].full_url
        assert first_url == "http://example.com/job-output.txt"

    # ----------------------------------------------------------- tail truncation

    def test_truncates_to_tail_lines(self, mocker):
        many_lines = "\n".join(f"line{i}" for i in range(1000))
        mocker.patch(f"{MODULE}.urllib.request.urlopen",
                     return_value=_make_response(many_lines.encode()))
        _, content = fetch_log_section("http://example.com/log.txt", tail_lines=10)
        kept = [l for l in content.splitlines() if l.startswith("line")]
        assert len(kept) == 10
        assert "line999" in content

    def test_adds_truncation_note_when_lines_dropped(self, mocker):
        many_lines = "\n".join(f"line{i}" for i in range(600))
        mocker.patch(f"{MODULE}.urllib.request.urlopen",
                     return_value=_make_response(many_lines.encode()))
        _, content = fetch_log_section("http://example.com/log.txt", tail_lines=500)
        assert "omitted" in content.lower() or "..." in content

    def test_no_truncation_note_when_within_limit(self, mocker):
        short = b"line1\nline2\n"
        mocker.patch(f"{MODULE}.urllib.request.urlopen",
                     return_value=_make_response(short))
        _, content = fetch_log_section("http://example.com/log.txt", tail_lines=500)
        assert "omitted" not in content.lower()

    # ----------------------------------------------------------- gzip support

    def test_decompresses_gz_url(self, mocker):
        raw_text = "compressed log content\nline2\n"
        gz_body = gzip.compress(raw_text.encode())
        mocker.patch(f"{MODULE}.urllib.request.urlopen",
                     return_value=_make_response(gz_body))
        ok, content = fetch_log_section("http://example.com/job-output.txt.gz")
        assert ok is True
        assert "compressed log content" in content

    def test_gz_url_not_doubled(self, mocker):
        """A URL that already ends in .gz should not get a second .gz appended."""
        gz_body = gzip.compress(b"data\n")
        mock_open = mocker.patch(f"{MODULE}.urllib.request.urlopen",
                                 return_value=_make_response(gz_body))
        fetch_log_section("http://example.com/log.txt.gz")
        for call in mock_open.call_args_list:
            url = call[0][0].full_url
            assert not url.endswith(".gz.gz"), f"URL doubled: {url}"

    # ----------------------------------------------------------- 404 fallback to .gz

    def test_falls_back_to_gz_on_404(self, mocker):
        gz_content = gzip.compress(b"fallback content\n")

        def side_effect(req, timeout=None):
            if req.full_url.endswith(".gz"):
                return _make_response(gz_content, req.full_url)
            raise _http_error(404)

        mocker.patch(f"{MODULE}.urllib.request.urlopen", side_effect=side_effect)
        ok, content = fetch_log_section(
            "http://example.com/job-output.txt", retries=1
        )
        assert ok is True
        assert "fallback content" in content

    def test_plain_non_404_error_retried_not_cascaded(self, mocker):
        """A 503 on the plain URL should be retried, not immediately cascade to .gz."""
        calls = []

        def side_effect(req, timeout=None):
            calls.append(req.full_url)
            raise _http_error(503)

        mocker.patch(f"{MODULE}.urllib.request.urlopen", side_effect=side_effect)
        mocker.patch(f"{MODULE}.time.sleep")
        fetch_log_section("http://example.com/job-output.txt", retries=2)

        plain_calls = [u for u in calls if not u.endswith(".gz")]
        gz_calls = [u for u in calls if u.endswith(".gz")]
        assert len(plain_calls) == 2   # retried twice on plain URL
        assert len(gz_calls) == 2      # then tried .gz variant twice

    # ----------------------------------------------------------- all-fail behaviour

    def test_returns_false_when_all_urls_fail(self, mocker):
        mocker.patch(f"{MODULE}.urllib.request.urlopen",
                     side_effect=_http_error(503))
        mocker.patch(f"{MODULE}.time.sleep")
        ok, msg = fetch_log_section("http://example.com/log.txt", retries=1)
        assert ok is False
        assert msg  # descriptive error string

    def test_returns_false_on_url_error(self, mocker):
        mocker.patch(
            f"{MODULE}.urllib.request.urlopen",
            side_effect=urllib.error.URLError("Name or service not known"),
        )
        mocker.patch(f"{MODULE}.time.sleep")
        ok, msg = fetch_log_section("http://bad.example.com/log.txt", retries=1)
        assert ok is False
        assert msg

    def test_does_not_raise(self, mocker):
        """fetch_log_section must never propagate exceptions."""
        mocker.patch(f"{MODULE}.urllib.request.urlopen",
                     side_effect=RuntimeError("unexpected"))
        mocker.patch(f"{MODULE}.time.sleep")
        result = fetch_log_section("http://example.com/log.txt", retries=1)
        assert result[0] is False
