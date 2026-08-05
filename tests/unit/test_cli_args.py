"""
Unit tests for agents_lib.cli_args.

Covers:
  - HelpOnErrorParser.error() prints help to stderr and exits 2
  - validate_launchpad_url(): valid/invalid hosts, valid/invalid paths
  - validate_forge_url(): valid/invalid hosts from config and public hosts
  - validate_jira_url(): valid/invalid hosts from config, valid/invalid paths
  - add_bug_args(): mutual exclusion, flags present, url validator wired
  - add_change_args(): mutual exclusion, --patchset requires --change
  - add_jira_args(): mutual exclusion, flags present
  - add_post_args(): mutually exclusive --no-post / --post-only
  - resolve_bug_target(): --bug, --url, --output-dir, --skip-tracking combos
  - resolve_change_target(): --change, --url, --patchset combos, output-dir
  - resolve_jira_target(): --issue, --url combos
  - confirm_reprocess(): y/n/EOF behaviour
"""
import argparse
from pathlib import Path

import pytest

from agents_lib.cli_args import (
    HelpOnErrorParser,
    add_bug_args,
    add_change_args,
    add_jira_args,
    add_post_args,
    confirm_reprocess,
    resolve_bug_target,
    resolve_change_target,
    resolve_jira_target,
    validate_forge_url,
    validate_jira_url,
    validate_launchpad_url,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LP_BUG = "https://bugs.launchpad.net/octavia/+bug/2150752"
_LP_BUG_ALT = "https://launchpad.net/bugs/2150752"
_GERRIT_URL = "https://review.opendev.org/c/openstack/octavia/+/982567"
_GITHUB_URL = "https://github.com/openstack/octavia/pull/42"
_GITLAB_URL = "https://gitlab.com/mygroup/myrepo/-/merge_requests/7"
_JIRA_URL = "https://myco.atlassian.net/browse/PROJ-123"

_GERRIT_CONFIG = {"forge_base_url": "https://review.opendev.org"}
_JIRA_CONFIG = {"jira": {"base_url": "https://myco.atlassian.net"}}
_EMPTY_CONFIG = {}


# ---------------------------------------------------------------------------
# HelpOnErrorParser
# ---------------------------------------------------------------------------

class TestHelpOnErrorParser:
    def test_error_prints_help_to_stderr(self, capsys):
        parser = HelpOnErrorParser(description="Test parser")
        parser.add_argument("--foo", required=True)
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args([])
        assert exc_info.value.code == 2
        captured = capsys.readouterr()
        assert "usage:" in captured.err.lower()
        assert "error:" in captured.err.lower()

    def test_help_flag_exits_0(self, capsys):
        parser = HelpOnErrorParser(description="Test parser")
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--help"])
        assert exc_info.value.code == 0

    def test_error_message_included_in_stderr(self, capsys):
        parser = HelpOnErrorParser()
        parser.add_argument("--num", type=int)
        with pytest.raises(SystemExit):
            parser.parse_args(["--num", "not-a-number"])
        captured = capsys.readouterr()
        assert "error:" in captured.err


# ---------------------------------------------------------------------------
# validate_launchpad_url
# ---------------------------------------------------------------------------

class TestValidateLaunchpadUrl:
    def test_valid_bugs_launchpad_net(self):
        assert validate_launchpad_url(_LP_BUG) == _LP_BUG

    def test_valid_launchpad_net_bugs(self):
        assert validate_launchpad_url(_LP_BUG_ALT) == _LP_BUG_ALT

    def test_invalid_host_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="not a recognised Launchpad host"):
            validate_launchpad_url("https://github.com/issues/1")

    def test_no_bug_number_in_path_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="Cannot extract a bug number"):
            validate_launchpad_url("https://bugs.launchpad.net/octavia/")

    def test_non_http_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="http"):
            validate_launchpad_url("ftp://bugs.launchpad.net/+bug/123")

    def test_http_accepted(self):
        url = "http://bugs.launchpad.net/+bug/9999"
        assert validate_launchpad_url(url) == url

    def test_numeric_bug_id_extracted_silently(self):
        url = "https://bugs.launchpad.net/octavia/+bug/42"
        assert validate_launchpad_url(url) == url


# ---------------------------------------------------------------------------
# validate_forge_url
# ---------------------------------------------------------------------------

class TestValidateForgeUrl:
    def test_gerrit_url_with_config(self):
        assert validate_forge_url(_GERRIT_URL, _GERRIT_CONFIG) == _GERRIT_URL

    def test_github_url_always_accepted(self):
        assert validate_forge_url(_GITHUB_URL, _EMPTY_CONFIG) == _GITHUB_URL

    def test_gitlab_url_always_accepted(self):
        assert validate_forge_url(_GITLAB_URL, _EMPTY_CONFIG) == _GITLAB_URL

    def test_unknown_host_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="not a recognised forge host"):
            validate_forge_url("https://bitbucket.org/x/y/pull-requests/1", _GERRIT_CONFIG)

    def test_launchpad_url_rejected(self):
        with pytest.raises(argparse.ArgumentTypeError):
            validate_forge_url(_LP_BUG, _GERRIT_CONFIG)

    def test_non_http_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="http"):
            validate_forge_url("ftp://review.opendev.org/x", _GERRIT_CONFIG)

    def test_gerrit_base_url_from_fallback_key(self):
        config = {"gerrit_base_url": "https://review.opendev.org"}
        assert validate_forge_url(_GERRIT_URL, config) == _GERRIT_URL


# ---------------------------------------------------------------------------
# validate_jira_url
# ---------------------------------------------------------------------------

class TestValidateJiraUrl:
    def test_valid_jira_url(self):
        assert validate_jira_url(_JIRA_URL, _JIRA_CONFIG) == _JIRA_URL

    def test_wrong_host_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="does not match the configured JIRA"):
            validate_jira_url("https://other.atlassian.net/browse/PROJ-1", _JIRA_CONFIG)

    def test_no_issue_key_in_path_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="Cannot extract a JIRA issue key"):
            validate_jira_url("https://myco.atlassian.net/projects/PROJ", _JIRA_CONFIG)

    def test_empty_jira_config_skips_host_check(self):
        url = "https://anyhost.example.com/browse/FOO-99"
        assert validate_jira_url(url, _EMPTY_CONFIG) == url

    def test_non_http_raises(self):
        with pytest.raises(argparse.ArgumentTypeError, match="http"):
            validate_jira_url("ftp://myco.atlassian.net/browse/PROJ-1", _JIRA_CONFIG)


# ---------------------------------------------------------------------------
# add_bug_args
# ---------------------------------------------------------------------------

class TestAddBugArgs:
    def _make_parser(self, config=None):
        parser = HelpOnErrorParser()
        add_bug_args(parser, config or _EMPTY_CONFIG)
        return parser

    def test_bug_flag_parsed(self):
        args = self._make_parser().parse_args(["--bug", "2150752"])
        assert args.bug == 2150752

    def test_url_flag_parsed(self):
        args = self._make_parser().parse_args(["--url", _LP_BUG])
        assert args.url == _LP_BUG

    def test_bug_and_url_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            self._make_parser().parse_args(["--bug", "1", "--url", _LP_BUG])

    def test_output_dir_flag(self):
        args = self._make_parser().parse_args(["--output-dir", "/tmp/out"])
        assert args.output_dir == "/tmp/out"

    def test_skip_tracking_flag(self):
        args = self._make_parser().parse_args(["--skip-tracking"])
        assert args.skip_tracking is True

    def test_no_args_defaults(self):
        args = self._make_parser().parse_args([])
        assert args.bug is None
        assert args.url is None
        assert args.output_dir is None
        assert args.skip_tracking is False

    def test_url_validated_strict(self):
        with pytest.raises(SystemExit):
            self._make_parser().parse_args(["--url", "https://github.com/x/y"])


# ---------------------------------------------------------------------------
# add_change_args
# ---------------------------------------------------------------------------

class TestAddChangeArgs:
    def _make_parser(self, config=None):
        parser = HelpOnErrorParser()
        add_change_args(parser, config or _GERRIT_CONFIG)
        return parser

    def test_change_flag_parsed(self):
        args = self._make_parser().parse_args(["--change", "982567"])
        assert args.change == "982567"

    def test_url_flag_parsed(self):
        args = self._make_parser().parse_args(["--url", _GERRIT_URL])
        assert args.url == _GERRIT_URL

    def test_change_and_url_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            self._make_parser().parse_args(["--change", "1", "--url", _GERRIT_URL])

    def test_patchset_flag(self):
        args = self._make_parser().parse_args(["--change", "982567", "--patchset", "3"])
        assert args.patchset == 3

    def test_patchset_short_flag(self):
        args = self._make_parser().parse_args(["--change", "982567", "-p", "2"])
        assert args.patchset == 2

    def test_output_dir(self):
        args = self._make_parser().parse_args(["--output-dir", "/tmp/r"])
        assert args.output_dir == "/tmp/r"

    def test_skip_tracking(self):
        args = self._make_parser().parse_args(["--change", "1", "--skip-tracking"])
        assert args.skip_tracking is True

    def test_url_validated_against_config(self):
        with pytest.raises(SystemExit):
            self._make_parser().parse_args(["--url", _LP_BUG])


# ---------------------------------------------------------------------------
# add_jira_args
# ---------------------------------------------------------------------------

class TestAddJiraArgs:
    def _make_parser(self, config=None):
        parser = HelpOnErrorParser()
        add_jira_args(parser, config or _JIRA_CONFIG)
        return parser

    def test_issue_flag(self):
        args = self._make_parser().parse_args(["--issue", "PROJ-123"])
        assert args.issue == "PROJ-123"

    def test_url_flag(self):
        args = self._make_parser().parse_args(["--url", _JIRA_URL])
        assert args.url == _JIRA_URL

    def test_issue_and_url_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            self._make_parser().parse_args(["--issue", "PROJ-1", "--url", _JIRA_URL])

    def test_output_dir(self):
        args = self._make_parser().parse_args(["--output-dir", "/tmp/j"])
        assert args.output_dir == "/tmp/j"

    def test_skip_tracking(self):
        args = self._make_parser().parse_args(["--skip-tracking"])
        assert args.skip_tracking is True

    def test_url_validated(self):
        with pytest.raises(SystemExit):
            self._make_parser().parse_args(["--url", "https://wrong.example.com/browse/X-1"])


# ---------------------------------------------------------------------------
# add_post_args
# ---------------------------------------------------------------------------

class TestAddPostArgs:
    def _make_parser(self):
        parser = HelpOnErrorParser()
        add_post_args(parser)
        return parser

    def test_no_post_flag(self):
        args = self._make_parser().parse_args(["--no-post"])
        assert args.no_post is True
        assert args.post_only is False

    def test_post_only_flag(self):
        args = self._make_parser().parse_args(["--post-only"])
        assert args.post_only is True
        assert args.no_post is False

    def test_no_post_and_post_only_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            self._make_parser().parse_args(["--no-post", "--post-only"])

    def test_defaults(self):
        args = self._make_parser().parse_args([])
        assert args.no_post is False
        assert args.post_only is False


# ---------------------------------------------------------------------------
# resolve_bug_target
# ---------------------------------------------------------------------------

class TestResolveBugTarget:
    def _make_args(self, bug=None, url=None, output_dir=None, skip_tracking=False):
        ns = argparse.Namespace(
            bug=bug, url=url, output_dir=output_dir, skip_tracking=skip_tracking
        )
        return ns

    def test_bug_number_returned_as_string(self):
        args = self._make_args(bug=2150752)
        bug_id, _, _ = resolve_bug_target(args, {"triages_output_dir": "/tmp/t"})
        assert bug_id == "2150752"

    def test_url_extracts_bug_id(self):
        args = self._make_args(url=_LP_BUG)
        bug_id, _, _ = resolve_bug_target(args, {"triages_output_dir": "/tmp/t"})
        assert bug_id == "2150752"

    def test_url_alt_format_extracts_bug_id(self):
        args = self._make_args(url=_LP_BUG_ALT)
        bug_id, _, _ = resolve_bug_target(args, {"triages_output_dir": "/tmp/t"})
        assert bug_id == "2150752"

    def test_no_args_returns_none_bug_id(self):
        args = self._make_args()
        bug_id, _, _ = resolve_bug_target(args, {"triages_output_dir": "/tmp/t"})
        assert bug_id is None

    def test_output_dir_override_applied(self):
        args = self._make_args(output_dir="/tmp/custom")
        _, output_dir, _ = resolve_bug_target(args, {"triages_output_dir": "/tmp/default"})
        assert output_dir == Path("/tmp/custom")

    def test_output_dir_falls_back_to_config(self):
        args = self._make_args()
        _, output_dir, _ = resolve_bug_target(args, {"triages_output_dir": "/tmp/fromconfig"})
        assert output_dir == Path("/tmp/fromconfig")

    def test_skip_tracking_propagated(self):
        args = self._make_args(skip_tracking=True)
        _, _, skip = resolve_bug_target(args, {})
        assert skip is True

    def test_skip_tracking_false_by_default(self):
        args = self._make_args()
        _, _, skip = resolve_bug_target(args, {})
        assert skip is False


# ---------------------------------------------------------------------------
# resolve_change_target
# ---------------------------------------------------------------------------

class TestResolveChangeTarget:
    def _make_args(self, change=None, url=None, patchset=None,
                   output_dir=None, skip_tracking=False):
        return argparse.Namespace(
            change=change, url=url, patchset=patchset,
            output_dir=output_dir, skip_tracking=skip_tracking,
        )

    def test_change_number_returned(self):
        args = self._make_args(change="982567")
        ref, ps, _, _ = resolve_change_target(args, {"reviews_output_dir": "/tmp/r"})
        assert ref == "982567"
        assert ps is None

    def test_url_returned_as_change_ref(self):
        args = self._make_args(url=_GERRIT_URL)
        ref, ps, _, _ = resolve_change_target(args, {"reviews_output_dir": "/tmp/r"})
        assert ref == _GERRIT_URL
        assert ps is None

    def test_patchset_with_change(self):
        args = self._make_args(change="982567", patchset=3)
        ref, ps, _, _ = resolve_change_target(args, {})
        assert ref == "982567"
        assert ps == 3

    def test_patchset_without_change_raises(self):
        args = self._make_args(patchset=2)
        with pytest.raises(SystemExit, match="requires --change"):
            resolve_change_target(args, {})

    def test_patchset_with_url_raises(self):
        args = self._make_args(url=_GERRIT_URL, patchset=2)
        with pytest.raises(SystemExit, match="cannot be used with --url"):
            resolve_change_target(args, {})

    def test_no_args_returns_none(self):
        args = self._make_args()
        ref, ps, _, _ = resolve_change_target(args, {})
        assert ref is None
        assert ps is None

    def test_output_dir_override(self):
        args = self._make_args(output_dir="/tmp/out")
        _, _, output_dir, _ = resolve_change_target(args, {"reviews_output_dir": "/tmp/default"})
        assert output_dir == Path("/tmp/out")

    def test_output_dir_from_config(self):
        args = self._make_args()
        _, _, output_dir, _ = resolve_change_target(args, {"reviews_output_dir": "/tmp/cfg"})
        assert output_dir == Path("/tmp/cfg")

    def test_skip_tracking_propagated(self):
        args = self._make_args(skip_tracking=True)
        _, _, _, skip = resolve_change_target(args, {})
        assert skip is True


# ---------------------------------------------------------------------------
# resolve_jira_target
# ---------------------------------------------------------------------------

class TestResolveJiraTarget:
    def _make_args(self, issue=None, url=None, output_dir=None, skip_tracking=False):
        return argparse.Namespace(
            issue=issue, url=url, output_dir=output_dir, skip_tracking=skip_tracking
        )

    def test_issue_key_returned(self):
        args = self._make_args(issue="PROJ-123")
        key, _, _ = resolve_jira_target(args, {"triages_dir": "/tmp/j"})
        assert key == "PROJ-123"

    def test_url_extracts_issue_key(self):
        args = self._make_args(url=_JIRA_URL)
        key, _, _ = resolve_jira_target(args, {})
        assert key == "PROJ-123"

    def test_no_args_returns_none(self):
        args = self._make_args()
        key, _, _ = resolve_jira_target(args, {})
        assert key is None

    def test_output_dir_override(self):
        args = self._make_args(output_dir="/tmp/custom")
        _, output_dir, _ = resolve_jira_target(args, {"triages_dir": "/tmp/def"})
        assert output_dir == Path("/tmp/custom")

    def test_output_dir_from_config(self):
        args = self._make_args()
        _, output_dir, _ = resolve_jira_target(args, {"triages_dir": "/tmp/cfgdir"})
        assert output_dir == Path("/tmp/cfgdir")

    def test_skip_tracking_propagated(self):
        args = self._make_args(skip_tracking=True)
        _, _, skip = resolve_jira_target(args, {})
        assert skip is True


# ---------------------------------------------------------------------------
# confirm_reprocess
# ---------------------------------------------------------------------------

class TestConfirmReprocess:
    def test_yes_returns_true(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "y")
        assert confirm_reprocess("bug", "2150752") is True

    def test_yes_full_word_returns_true(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "yes")
        assert confirm_reprocess("bug", "2150752") is True

    def test_no_returns_false(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "n")
        assert confirm_reprocess("bug", "2150752") is False

    def test_empty_returns_false(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "")
        assert confirm_reprocess("bug", "2150752") is False

    def test_eof_returns_false(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError))
        assert confirm_reprocess("issue", "PROJ-1") is False

    def test_keyboard_interrupt_returns_false(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(KeyboardInterrupt))
        assert confirm_reprocess("change", "982567") is False

    def test_message_mentions_entity(self, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", lambda _: "n")
        confirm_reprocess("bug", "9999")
        captured = capsys.readouterr()
        assert "9999" in captured.out
        assert "Bug" in captured.out
