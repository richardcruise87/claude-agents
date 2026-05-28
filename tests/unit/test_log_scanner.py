"""Unit tests for scan_log_for_errors() and format_scan_results() in ci-failure-agent/log_scanner.py."""
import sys
from pathlib import Path

# The log_scanner module lives in ci-failure-agent/, not in agents_lib, so
# add its directory to sys.path before importing.
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "ci-failure-agent"))

from log_scanner import scan_log_for_errors, format_scan_results  # noqa: E402


# ── sample patterns matching the config defaults ───────────────────────────────
PATTERNS = [
    {"pattern": r"^\s*(FAIL|ERROR)\s+", "category": "test_failure"},
    {"pattern": r"Traceback \(most recent call last\)", "category": "traceback"},
    {"pattern": r"(timed? out|deadline exceeded)", "category": "timeout"},
    {"pattern": r"(No space left|Out of memory|Killed)", "category": "resource"},
    {"pattern": r"(ImportError|ModuleNotFoundError)", "category": "import_error"},
]


class TestScanLogForErrors:

    # ─── no matches ──────────────────────────────────────────────────────────

    def test_returns_empty_list_for_empty_log(self):
        assert scan_log_for_errors("", PATTERNS) == []

    def test_returns_empty_list_when_no_match(self):
        log = "Everything is fine.\nAll tests passed.\n"
        assert scan_log_for_errors(log, PATTERNS) == []

    def test_returns_empty_list_when_patterns_empty(self):
        log = "FAIL some.test.TestCase\nTraceback (most recent call last):\n"
        assert scan_log_for_errors(log, []) == []

    # ─── basic matches ───────────────────────────────────────────────────────

    def test_detects_test_failure_line(self):
        log = "FAIL  tests.unit.test_controller.TestController\n"
        results = scan_log_for_errors(log, PATTERNS)
        assert len(results) == 1
        category, line, lineno = results[0]
        assert category == "test_failure"
        assert "TestController" in line
        assert lineno == 1

    def test_detects_traceback(self):
        log = "some output\nTraceback (most recent call last):\n  File foo.py"
        results = scan_log_for_errors(log, PATTERNS)
        cats = [r[0] for r in results]
        assert "traceback" in cats

    def test_detects_timeout(self):
        log = "operation timed out after 30s\n"
        results = scan_log_for_errors(log, PATTERNS)
        assert results[0][0] == "timeout"

    def test_detects_import_error(self):
        log = "ImportError: cannot import name 'foo' from 'bar'\n"
        results = scan_log_for_errors(log, PATTERNS)
        assert results[0][0] == "import_error"

    def test_detects_resource_error(self):
        log = "No space left on device\n"
        results = scan_log_for_errors(log, PATTERNS)
        assert results[0][0] == "resource"

    # ─── line numbers ────────────────────────────────────────────────────────

    def test_reports_correct_line_numbers(self):
        log = "line 1\nline 2\nFAIL tests.SomeTest\nline 4\n"
        results = scan_log_for_errors(log, PATTERNS)
        assert results[0][2] == 3  # failure is on line 3

    # ─── one category per line ───────────────────────────────────────────────

    def test_assigns_only_one_category_per_line(self):
        # A line matching two patterns (e.g. "FAIL" and a timeout message)
        # should produce exactly one result for that line.
        log = "FAIL timed out waiting for result\n"
        results = scan_log_for_errors(log, PATTERNS)
        # Only one tuple returned (first matching pattern wins)
        assert len(results) == 1

    def test_multiple_lines_each_get_own_result(self):
        log = "FAIL one.test\nFAIL two.test\n"
        results = scan_log_for_errors(log, PATTERNS)
        assert len(results) == 2
        assert results[0][2] == 1
        assert results[1][2] == 2

    # ─── invalid patterns ────────────────────────────────────────────────────

    def test_skips_invalid_regex_silently(self):
        bad_patterns = [
            {"pattern": "[invalid", "category": "bad"},  # unclosed bracket
            {"pattern": r"FAIL", "category": "test_failure"},
        ]
        log = "FAIL some.test\n"
        results = scan_log_for_errors(log, bad_patterns)
        # Bad pattern skipped; good pattern still matches
        assert len(results) == 1
        assert results[0][0] == "test_failure"

    # ─── case insensitivity ──────────────────────────────────────────────────

    def test_patterns_are_case_insensitive(self):
        log = "importerror: no module named foo\n"
        results = scan_log_for_errors(log, PATTERNS)
        # Should match ImportError pattern regardless of case
        assert any(r[0] == "import_error" for r in results)


class TestFormatScanResults:

    # ─── empty input ─────────────────────────────────────────────────────────

    def test_returns_empty_string_for_empty_results(self):
        assert format_scan_results([], "my-job") == ""

    # ─── structure ───────────────────────────────────────────────────────────

    def test_includes_job_name_in_output(self):
        results = [("test_failure", "FAIL some.test", 5)]
        output = format_scan_results(results, "octavia-v2-dsvm-scenario")
        assert "octavia-v2-dsvm-scenario" in output

    def test_includes_category_label(self):
        results = [("timeout", "timed out after 30s", 10)]
        output = format_scan_results(results, "job")
        assert "timeout" in output

    def test_includes_line_number(self):
        results = [("test_failure", "FAIL SomeTest", 42)]
        output = format_scan_results(results, "job")
        assert "42" in output

    def test_includes_matched_line_snippet(self):
        results = [("test_failure", "FAIL octavia.tests.SomeTest", 1)]
        output = format_scan_results(results, "job")
        assert "octavia.tests.SomeTest" in output

    # ─── grouping & capping ──────────────────────────────────────────────────

    def test_groups_matches_by_category(self):
        results = [
            ("timeout", "timed out A", 1),
            ("timeout", "timed out B", 2),
            ("test_failure", "FAIL X", 3),
        ]
        output = format_scan_results(results, "job")
        # Both categories present
        assert "timeout" in output
        assert "test_failure" in output

    def test_caps_lines_per_category(self):
        results = [("timeout", f"timed out {i}", i) for i in range(10)]
        output = format_scan_results(results, "job", max_per_category=3)
        # Default cap is 3; only 3 individual lines should be shown
        shown = [line for line in output.splitlines()
                 if line.strip().startswith("- L")]
        assert len(shown) == 3

    def test_shows_overflow_count_when_capped(self):
        results = [("timeout", f"timed out {i}", i) for i in range(10)]
        output = format_scan_results(results, "job", max_per_category=3)
        # Should mention 7 more (10 - 3)
        assert "7" in output
        assert "more" in output.lower()

    def test_shows_match_count_in_header(self):
        results = [("test_failure", "FAIL X", 1), ("test_failure", "FAIL Y", 2)]
        output = format_scan_results(results, "job")
        # e.g. "test_failure (2 matches)"
        assert "2" in output

    # ─── long lines truncated ─────────────────────────────────────────────────

    def test_long_lines_truncated_in_output(self):
        long_line = "ERROR " + "x" * 200
        results = [("test_failure", long_line, 1)]
        output = format_scan_results(results, "job")
        # The shown snippet should be shorter than the full line
        assert len(output) < len(long_line) + 100
