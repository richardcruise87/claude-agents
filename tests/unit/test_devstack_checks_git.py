"""Unit tests for git_stash_save and git_stash_pop in agents_lib.devstack_checks."""
import subprocess
from agents_lib.devstack_checks import git_stash_save, git_stash_pop


class TestGitStashSave:
    def test_returns_false_when_no_local_changes(self, tmp_path, mocker):
        mock_run = mocker.patch("agents_lib.devstack_checks.subprocess.run")
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="No local changes to save\n", stderr=""
        )
        assert git_stash_save(tmp_path) is False

    def test_returns_true_when_stash_created(self, tmp_path, mocker):
        mock_run = mocker.patch("agents_lib.devstack_checks.subprocess.run")
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="Saved working directory and index state On main: claude-agents auto-stash\n",
            stderr="",
        )
        assert git_stash_save(tmp_path) is True

    def test_returns_false_on_nonzero_exit(self, tmp_path, mocker):
        mock_run = mocker.patch("agents_lib.devstack_checks.subprocess.run")
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="not a git repository"
        )
        assert git_stash_save(tmp_path) is False

    def test_returns_false_on_timeout(self, tmp_path, mocker):
        mocker.patch(
            "agents_lib.devstack_checks.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=10),
        )
        assert git_stash_save(tmp_path) is False

    def test_returns_false_on_file_not_found(self, tmp_path, mocker):
        mocker.patch(
            "agents_lib.devstack_checks.subprocess.run",
            side_effect=FileNotFoundError("git not found"),
        )
        assert git_stash_save(tmp_path) is False

    def test_custom_message_passed_to_git(self, tmp_path, mocker):
        mock_run = mocker.patch("agents_lib.devstack_checks.subprocess.run")
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="Saved working directory and index state On main: my-message\n",
            stderr="",
        )
        git_stash_save(tmp_path, message="my-message")
        call_args = mock_run.call_args[0][0]
        assert "-m" in call_args
        assert "my-message" in call_args

    def test_default_message_used_when_not_specified(self, tmp_path, mocker):
        mock_run = mocker.patch("agents_lib.devstack_checks.subprocess.run")
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="Saved working directory and index state\n",
            stderr="",
        )
        git_stash_save(tmp_path)
        call_args = mock_run.call_args[0][0]
        assert "claude-agents auto-stash" in call_args


class TestGitStashPop:
    def test_returns_true_and_message_on_success(self, tmp_path, mocker):
        mock_run = mocker.patch("agents_lib.devstack_checks.subprocess.run")
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="Already up to date!\nDropped refs/stash@{0}\n",
            stderr="",
        )
        ok, msg = git_stash_pop(tmp_path)
        assert ok is True
        assert "Stash popped successfully" in msg

    def test_returns_false_with_stderr_on_failure(self, tmp_path, mocker):
        mock_run = mocker.patch("agents_lib.devstack_checks.subprocess.run")
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout="",
            stderr="No stash entries found.",
        )
        ok, msg = git_stash_pop(tmp_path)
        assert ok is False
        assert "No stash entries found" in msg

    def test_returns_false_on_timeout(self, tmp_path, mocker):
        mocker.patch(
            "agents_lib.devstack_checks.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="git", timeout=15),
        )
        ok, msg = git_stash_pop(tmp_path)
        assert ok is False
        assert msg  # message is non-empty

    def test_returns_false_on_file_not_found(self, tmp_path, mocker):
        mocker.patch(
            "agents_lib.devstack_checks.subprocess.run",
            side_effect=FileNotFoundError("git not found"),
        )
        ok, msg = git_stash_pop(tmp_path)
        assert ok is False
        assert msg  # message is non-empty
