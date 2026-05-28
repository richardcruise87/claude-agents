"""Unit tests for git_fetch_and_checkout_ref() in agents_lib.git_info."""
import subprocess
from agents_lib.git_info import git_fetch_and_checkout_ref

MODULE = "agents_lib.git_info"


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


class TestGitFetchAndCheckoutRef:
    """Tests for the fetch-with-retry helper used by the DevStack test agent."""

    # ------------------------------------------------------------------ success

    def test_returns_true_sha_on_full_success(self, tmp_path, mocker):
        sha = "a" * 40
        mock_run = mocker.patch(f"{MODULE}.subprocess.run")
        # fetch → checkout → rev-parse
        mock_run.side_effect = [
            _completed(0),
            _completed(0),
            _completed(0, stdout=sha + "\n"),
        ]
        ok, msg, returned_sha = git_fetch_and_checkout_ref(
            tmp_path, "https://review.example.com/repo", "refs/changes/12/123/1"
        )
        assert ok is True
        assert returned_sha == sha
        assert sha[:12] in msg

    def test_sha_in_returned_message_is_truncated(self, tmp_path, mocker):
        sha = "deadbeef" * 5
        mock_run = mocker.patch(f"{MODULE}.subprocess.run")
        mock_run.side_effect = [
            _completed(0),
            _completed(0),
            _completed(0, stdout=sha + "\n"),
        ]
        _, msg, _ = git_fetch_and_checkout_ref(
            tmp_path, "https://example.com", "refs/heads/main"
        )
        assert sha[:12] in msg
        assert sha not in msg  # full 40-char SHA not shown

    # ------------------------------------------------------------------ fetch fails

    def test_returns_false_when_fetch_fails(self, tmp_path, mocker):
        mock_run = mocker.patch(f"{MODULE}.subprocess.run")
        mock_run.return_value = _completed(1, stderr="not a git repository")
        mocker.patch(f"{MODULE}.time.sleep")

        ok, msg, sha = git_fetch_and_checkout_ref(
            tmp_path, "https://example.com", "refs/changes/12/123/1", max_retries=1
        )
        assert ok is False
        assert sha == ""
        assert "failed" in msg.lower()

    def test_retries_on_fetch_failure(self, tmp_path, mocker):
        mock_run = mocker.patch(f"{MODULE}.subprocess.run")
        sha = "b" * 40
        # first fetch fails, second succeeds
        mock_run.side_effect = [
            _completed(1, stderr="temporary error"),
            _completed(0),               # fetch retry
            _completed(0),               # checkout
            _completed(0, stdout=sha),   # rev-parse
        ]
        mock_sleep = mocker.patch(f"{MODULE}.time.sleep")

        ok, _, returned_sha = git_fetch_and_checkout_ref(
            tmp_path, "https://example.com", "refs/changes/12/123/1", max_retries=2
        )
        assert ok is True
        assert returned_sha == sha
        mock_sleep.assert_called_once()  # slept once between attempts

    def test_gives_up_after_max_retries(self, tmp_path, mocker):
        mock_run = mocker.patch(f"{MODULE}.subprocess.run")
        mock_run.return_value = _completed(1, stderr="connection refused")
        mocker.patch(f"{MODULE}.time.sleep")

        ok, _, sha = git_fetch_and_checkout_ref(
            tmp_path, "https://example.com", "refs/changes/12/123/1", max_retries=3
        )
        assert ok is False
        assert sha == ""
        assert mock_run.call_count == 3  # tried exactly max_retries times

    def test_backoff_delay_increases_with_attempt(self, tmp_path, mocker):
        mock_run = mocker.patch(f"{MODULE}.subprocess.run")
        mock_run.return_value = _completed(1, stderr="error")
        mock_sleep = mocker.patch(f"{MODULE}.time.sleep")

        git_fetch_and_checkout_ref(
            tmp_path, "https://example.com", "refs/changes/12/123/1", max_retries=3
        )
        sleep_calls = [c.args[0] for c in mock_sleep.call_args_list]
        # Each sleep should be longer than the previous one
        assert len(sleep_calls) == 2  # sleeps between attempts 1-2 and 2-3
        assert sleep_calls[1] > sleep_calls[0]

    # ------------------------------------------------------------------ checkout fails

    def test_returns_false_when_checkout_fails(self, tmp_path, mocker):
        mock_run = mocker.patch(f"{MODULE}.subprocess.run")
        mock_run.side_effect = [
            _completed(0),                           # fetch OK
            _completed(1, stderr="detached HEAD"),   # checkout fails
        ]
        ok, msg, sha = git_fetch_and_checkout_ref(
            tmp_path, "https://example.com", "refs/changes/12/123/1", max_retries=1
        )
        assert ok is False
        assert sha == ""
        assert "FETCH_HEAD" in msg or "failed" in msg.lower()

    # ------------------------------------------------------------------ rev-parse fails

    def test_returns_false_when_rev_parse_fails(self, tmp_path, mocker):
        mock_run = mocker.patch(f"{MODULE}.subprocess.run")
        mock_run.side_effect = [
            _completed(0),   # fetch
            _completed(0),   # checkout
            _completed(1),   # rev-parse fails
        ]
        ok, msg, sha = git_fetch_and_checkout_ref(
            tmp_path, "https://example.com", "refs/changes/12/123/1", max_retries=1
        )
        assert ok is False
        assert sha == ""

    # ------------------------------------------------------------------ exceptions

    def test_returns_false_on_timeout_expired(self, tmp_path, mocker):
        mocker.patch(
            f"{MODULE}.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=120),
        )
        mocker.patch(f"{MODULE}.time.sleep")

        ok, msg, sha = git_fetch_and_checkout_ref(
            tmp_path, "https://example.com", "refs/changes/12/123/1", max_retries=1
        )
        assert ok is False
        assert sha == ""
        assert msg  # non-empty error message

    def test_returns_false_on_file_not_found(self, tmp_path, mocker):
        mocker.patch(
            f"{MODULE}.subprocess.run",
            side_effect=FileNotFoundError("git not found"),
        )
        mocker.patch(f"{MODULE}.time.sleep")

        ok, msg, sha = git_fetch_and_checkout_ref(
            tmp_path, "https://example.com", "refs/changes/12/123/1", max_retries=1
        )
        assert ok is False
        assert sha == ""

    def test_returns_false_on_git_not_found(self, tmp_path, mocker):
        """FileNotFoundError (git not in PATH) → clean (False, msg, '') — never raises."""
        mocker.patch(
            f"{MODULE}.subprocess.run",
            side_effect=FileNotFoundError("git not found"),
        )
        mocker.patch(f"{MODULE}.time.sleep")

        ok, msg, sha = git_fetch_and_checkout_ref(
            tmp_path, "https://example.com", "refs/changes/12/123/1", max_retries=1
        )
        assert ok is False
        assert sha == ""
        assert msg  # descriptive, non-empty
