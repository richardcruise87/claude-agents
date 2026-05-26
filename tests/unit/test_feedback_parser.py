"""Unit tests for devstack-test-agent/feedback_parser.py."""
from feedback_parser import (
    parse_feedback,
    validate_test_names,
    read_devstack_feedback,
    process_feedback,
)


VALID_OCTAVIA = "octavia_tempest_plugin.tests.api.v2.test_load_balancer.LoadBalancerScenarioTest.test_lb_crd"
VALID_TEMPEST = "tempest.api.network.test_networks.NetworksTest.test_create_delete_network"


class TestParseFeedback:
    def test_rerun_all_sentinel(self):
        rerun, names = parse_feedback("Re-run all tests\n")
        assert rerun is True
        assert names == []

    def test_rerun_all_case_insensitive(self):
        rerun, names = parse_feedback("RE-RUN ALL TESTS")
        assert rerun is True

    def test_rerun_all_with_comment_lines(self):
        rerun, names = parse_feedback("# a comment\nRe-run all tests")
        assert rerun is True
        assert names == []

    def test_run_test_prefix_extracted(self):
        raw = f"Run test: {VALID_OCTAVIA}"
        rerun, names = parse_feedback(raw)
        assert rerun is False
        assert names == [VALID_OCTAVIA]

    def test_run_tests_plural_prefix(self):
        raw = f"Run tests: {VALID_OCTAVIA}"
        rerun, names = parse_feedback(raw)
        assert names == [VALID_OCTAVIA]

    def test_bare_octavia_name_extracted(self):
        rerun, names = parse_feedback(VALID_OCTAVIA)
        assert rerun is False
        assert VALID_OCTAVIA in names

    def test_bare_tempest_name_extracted(self):
        rerun, names = parse_feedback(VALID_TEMPEST)
        assert VALID_TEMPEST in names

    def test_comment_lines_ignored(self):
        raw = f"# ignore this\n{VALID_OCTAVIA}"
        _, names = parse_feedback(raw)
        assert "# ignore this" not in names
        assert VALID_OCTAVIA in names

    def test_blank_lines_ignored(self):
        raw = f"\n\n{VALID_OCTAVIA}\n\n"
        _, names = parse_feedback(raw)
        assert names == [VALID_OCTAVIA]

    def test_unknown_lines_ignored(self):
        raw = f"some random text that is not a test name\n{VALID_OCTAVIA}"
        _, names = parse_feedback(raw)
        assert VALID_OCTAVIA in names
        assert len(names) == 1  # the random text is ignored

    def test_multiple_run_test_lines(self):
        raw = f"Run test: {VALID_OCTAVIA}\nRun test: {VALID_TEMPEST}"
        _, names = parse_feedback(raw)
        assert VALID_OCTAVIA in names
        assert VALID_TEMPEST in names
        assert len(names) == 2

    def test_empty_input_returns_no_tests(self):
        rerun, names = parse_feedback("")
        assert rerun is False
        assert names == []


class TestValidateTestNames:
    def test_valid_octavia_name_accepted(self):
        valid, rejected = validate_test_names([VALID_OCTAVIA])
        assert VALID_OCTAVIA in valid
        assert rejected == []

    def test_valid_tempest_name_accepted(self):
        valid, rejected = validate_test_names([VALID_TEMPEST])
        assert VALID_TEMPEST in valid
        assert rejected == []

    def test_semicolon_rejected(self):
        _, rejected = validate_test_names(["octavia.foo; rm -rf /"])
        assert len(rejected) == 1

    def test_pipe_rejected(self):
        _, rejected = validate_test_names(["octavia.foo|bar"])
        assert len(rejected) == 1

    def test_dollar_sign_rejected(self):
        _, rejected = validate_test_names(["octavia.foo$HOME"])
        assert len(rejected) == 1

    def test_backtick_rejected(self):
        _, rejected = validate_test_names(["octavia.foo`whoami`"])
        assert len(rejected) == 1

    def test_ampersand_rejected(self):
        _, rejected = validate_test_names(["octavia.foo&bar"])
        assert len(rejected) == 1

    def test_wrong_prefix_rejected(self):
        _, rejected = validate_test_names(["unittest.mock.MagicMock"])
        assert len(rejected) == 1

    def test_spaces_rejected(self):
        _, rejected = validate_test_names(["octavia foo bar"])
        assert len(rejected) == 1

    def test_empty_string_rejected(self):
        _, rejected = validate_test_names([""])
        assert len(rejected) == 1

    def test_mixed_valid_and_invalid(self):
        valid, rejected = validate_test_names([VALID_OCTAVIA, "bad;input"])
        assert VALID_OCTAVIA in valid
        assert len(rejected) == 1

    def test_empty_list_returns_empty(self):
        valid, rejected = validate_test_names([])
        assert valid == []
        assert rejected == []


class TestReadDevstackFeedback:
    def test_returns_none_when_no_file(self, tmp_path):
        result = read_devstack_feedback("982567", 3, tmp_path)
        assert result is None

    def test_returns_content_and_deletes_file(self, tmp_path):
        f = tmp_path / "devstack_test_982567_ps3_feedback.txt"
        f.write_text("Re-run all tests", encoding="utf-8")
        result = read_devstack_feedback("982567", 3, tmp_path)
        assert result == "Re-run all tests"
        assert not f.exists()

    def test_returns_none_for_whitespace_only(self, tmp_path):
        f = tmp_path / "devstack_test_982567_ps3_feedback.txt"
        f.write_text("   \n", encoding="utf-8")
        result = read_devstack_feedback("982567", 3, tmp_path)
        assert result is None
        assert not f.exists()

    def test_correct_filename_pattern(self, tmp_path):
        # File with correct name is picked up; wrong name is ignored
        wrong = tmp_path / "devstack_test_982567_ps99_feedback.txt"
        wrong.write_text("wrong patchset", encoding="utf-8")
        result = read_devstack_feedback("982567", 3, tmp_path)
        assert result is None  # ps3 file doesn't exist
        assert wrong.exists()  # ps99 file was not consumed


class TestProcessFeedback:
    def test_no_file_returns_none(self, tmp_path):
        assert process_feedback("982567", 3, tmp_path) is None

    def test_rerun_all_returns_true_empty_list(self, tmp_path):
        f = tmp_path / "devstack_test_982567_ps3_feedback.txt"
        f.write_text("Re-run all tests", encoding="utf-8")
        result = process_feedback("982567", 3, tmp_path)
        assert result == (True, [])

    def test_valid_tests_returned(self, tmp_path):
        f = tmp_path / "devstack_test_982567_ps3_feedback.txt"
        f.write_text(f"Run test: {VALID_OCTAVIA}", encoding="utf-8")
        result = process_feedback("982567", 3, tmp_path)
        assert result is not None
        rerun, names = result
        assert rerun is False
        assert VALID_OCTAVIA in names

    def test_all_invalid_returns_empty_valid_list(self, tmp_path):
        f = tmp_path / "devstack_test_982567_ps3_feedback.txt"
        f.write_text("Run test: bad;injection", encoding="utf-8")
        rerun, names = process_feedback("982567", 3, tmp_path)
        assert rerun is False
        assert names == []

    def test_mixed_returns_only_valid(self, tmp_path):
        f = tmp_path / "devstack_test_982567_ps3_feedback.txt"
        f.write_text(f"Run test: {VALID_OCTAVIA}\nRun test: bad;injection", encoding="utf-8")
        rerun, names = process_feedback("982567", 3, tmp_path)
        assert rerun is False
        assert VALID_OCTAVIA in names
        assert len(names) == 1
