"""
Unit tests for agents_lib.summariser.

Covers:
  - generate_summary(): happy path, missing report file, missing prompt file
  - print_summary(): stdout output format
  - needs_summary(): --print-summary, --post-summary, config flag, defaults
  - add_summary_args(): flags added, mutual exclusion
"""

import argparse
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents_lib.cli_args import HelpOnErrorParser, add_summary_args
from agents_lib.summariser import generate_summary, needs_summary, print_summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_args(**kwargs):
    defaults = {"print_summary": False, "post_summary": False}
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# generate_summary
# ---------------------------------------------------------------------------

class TestGenerateSummary:
    def test_returns_none_when_report_missing(self, tmp_path):
        prompt = tmp_path / "prompt.txt"
        prompt.write_text("Summarise: {report_content}", encoding="utf-8")
        missing = tmp_path / "nonexistent.md"
        result = generate_summary(missing, prompt, {})
        assert result is None

    def test_raises_when_prompt_missing(self, tmp_path):
        report = tmp_path / "report.md"
        report.write_text("# Report\nSome content", encoding="utf-8")
        missing_prompt = tmp_path / "no_such_prompt.txt"
        with pytest.raises(FileNotFoundError, match="Summary prompt not found"):
            generate_summary(report, missing_prompt, {})

    def _make_mock_client(self, mocker, text="Short summary"):
        mock_result = MagicMock()
        mock_result.text = text
        mock_client = MagicMock()
        mock_client.query = AsyncMock(return_value=mock_result)
        mocker.patch(
            "agents_lib.model_client.create_model_client",
            return_value=mock_client,
        )
        return mock_client

    def test_injects_report_content_into_prompt(self, tmp_path, mocker):
        report = tmp_path / "report.md"
        report.write_text("# Report\nHello world", encoding="utf-8")
        prompt = tmp_path / "prompt.txt"
        prompt.write_text("Summarise this: {report_content}", encoding="utf-8")

        mock_client = self._make_mock_client(mocker, "Short summary")
        result = generate_summary(report, prompt, {})

        assert result == "Short summary"
        call_kwargs = mock_client.query.call_args
        assert "Hello world" in call_kwargs.kwargs.get("prompt", "")
        assert call_kwargs.kwargs.get("tools") is None

    def test_truncates_long_reports(self, tmp_path, mocker):
        report = tmp_path / "report.md"
        long_content = "x" * 10000
        report.write_text(long_content, encoding="utf-8")
        prompt = tmp_path / "prompt.txt"
        prompt.write_text("Summary: {report_content}", encoding="utf-8")

        mock_client = self._make_mock_client(mocker, "Truncated summary")
        generate_summary(report, prompt, {})

        prompt_sent = mock_client.query.call_args.kwargs["prompt"]
        assert "truncated for summary" in prompt_sent

    def test_returns_stripped_text(self, tmp_path, mocker):
        report = tmp_path / "report.md"
        report.write_text("content", encoding="utf-8")
        prompt = tmp_path / "prompt.txt"
        prompt.write_text("{report_content}", encoding="utf-8")

        self._make_mock_client(mocker, "  Summary with whitespace  \n")
        result = generate_summary(report, prompt, {})
        assert result == "Summary with whitespace"

    def test_accepts_string_paths(self, tmp_path, mocker):
        report = tmp_path / "report.md"
        report.write_text("content", encoding="utf-8")
        prompt = tmp_path / "prompt.txt"
        prompt.write_text("{report_content}", encoding="utf-8")

        self._make_mock_client(mocker, "ok")
        result = generate_summary(str(report), str(prompt), {})
        assert result == "ok"


# ---------------------------------------------------------------------------
# print_summary
# ---------------------------------------------------------------------------

class TestPrintSummary:
    def test_prints_summary_text(self, capsys):
        print_summary("This is the summary.", report_path=None)
        captured = capsys.readouterr()
        assert "This is the summary." in captured.out

    def test_prints_separator_lines(self, capsys):
        print_summary("hello", report_path=None)
        captured = capsys.readouterr()
        assert "─" in captured.out
        assert "Summary" in captured.out

    def test_prints_report_path_when_given(self, capsys):
        print_summary("summary text", report_path="/tmp/report.md")
        captured = capsys.readouterr()
        assert "/tmp/report.md" in captured.out

    def test_no_report_path_omits_report_line(self, capsys):
        print_summary("summary text", report_path=None)
        captured = capsys.readouterr()
        assert "Report:" not in captured.out

    def test_accepts_path_object(self, capsys):
        print_summary("summary", report_path=Path("/tmp/report.md"))
        captured = capsys.readouterr()
        assert "/tmp/report.md" in captured.out


# ---------------------------------------------------------------------------
# needs_summary
# ---------------------------------------------------------------------------

class TestNeedsSummary:
    def test_false_by_default(self):
        args = _make_args()
        assert needs_summary(args, {}) is False

    def test_true_when_print_summary_flag(self):
        args = _make_args(print_summary=True)
        assert needs_summary(args, {}) is True

    def test_true_when_post_summary_flag(self):
        args = _make_args(post_summary=True)
        assert needs_summary(args, {}) is True

    def test_true_when_config_post_summary(self):
        args = _make_args()
        config = {"feedback": {"post_summary": True}}
        assert needs_summary(args, config) is True

    def test_false_when_config_post_summary_false(self):
        args = _make_args()
        config = {"feedback": {"post_summary": False}}
        assert needs_summary(args, config) is False

    def test_false_when_no_feedback_section(self):
        args = _make_args()
        assert needs_summary(args, {"other_key": True}) is False

    def test_missing_attribute_treated_as_false(self):
        args = argparse.Namespace()
        assert needs_summary(args, {}) is False


# ---------------------------------------------------------------------------
# add_summary_args
# ---------------------------------------------------------------------------

class TestAddSummaryArgs:
    def _make_parser(self):
        parser = HelpOnErrorParser()
        add_summary_args(parser)
        return parser

    def test_print_summary_flag(self):
        args = self._make_parser().parse_args(["--print-summary"])
        assert args.print_summary is True
        assert args.post_summary is False

    def test_post_summary_flag(self):
        args = self._make_parser().parse_args(["--post-summary"])
        assert args.post_summary is True
        assert args.print_summary is False

    def test_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            self._make_parser().parse_args(["--print-summary", "--post-summary"])

    def test_defaults_both_false(self):
        args = self._make_parser().parse_args([])
        assert args.print_summary is False
        assert args.post_summary is False

    def test_compatible_with_no_post(self):
        parser = HelpOnErrorParser()
        from agents_lib.cli_args import add_post_args  # noqa: PLC0415
        add_post_args(parser)
        add_summary_args(parser)
        args = parser.parse_args(["--no-post", "--print-summary"])
        assert args.no_post is True
        assert args.print_summary is True

    def test_compatible_with_post_only(self):
        parser = HelpOnErrorParser()
        from agents_lib.cli_args import add_post_args  # noqa: PLC0415
        add_post_args(parser)
        add_summary_args(parser)
        args = parser.parse_args(["--post-only", "--print-summary"])
        assert args.post_only is True
        assert args.print_summary is True
