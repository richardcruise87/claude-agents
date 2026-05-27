"""Unit tests for devstack-test-agent/report_validator.py."""
import re
import pytest
from report_validator import validate_report, REQUIRED_SECTIONS

# Minimal valid report containing all required sections
_VALID_REPORT = """\
# DevStack Integration Testing

## Summary

### Change Info

- **Repository:** openstack/octavia
- **Change:** #988005
- **Patchset:** PS3
- **Test Date:** 2026-05-27 09:00:00 UTC

### Overview

This change adds a new feature.

### Test Results

**Overall Status:** ✅ PASS

| Test Name | Description | Result |
|-----------|-------------|--------|
| API smoke | Basic API check | ✅ PASS |

## Tests Performed

### Test 1: API smoke test

#### Summary

Verify the API responds correctly.

#### Procedure

1. Run `openstack loadbalancer list`

#### Results

```
+----+------+--------+
| id | name | status |
+----+------+--------+
```

#### Verdict

API is responding normally.

**Result:** ✅ PASS

## Test Results Summary

**Overall Status:** ✅ PASS
**Tests Passed:** 1/1
**Tests Failed:** 0

**Key Findings:**
- All tests passed.

**Issues Found:**
- None

## Cleanup Verification

All resources deleted.

**Cleanup Status:** ✅ Complete

## Service Status After Testing

All services active.

**Services:** ✅ All Active

---

END OF REPORT
"""


class TestValidateReport:
    def test_valid_report_returns_empty(self, tmp_path):
        f = tmp_path / "report.md"
        f.write_text(_VALID_REPORT, encoding="utf-8")
        assert validate_report(f) == []

    def test_missing_main_heading(self, tmp_path):
        content = _VALID_REPORT.replace("# DevStack Integration Testing\n", "")
        f = tmp_path / "report.md"
        f.write_text(content, encoding="utf-8")
        errors = validate_report(f)
        assert any("DevStack Integration Testing" in e for e in errors)

    def test_missing_summary_section(self, tmp_path):
        content = _VALID_REPORT.replace("## Summary\n", "")
        f = tmp_path / "report.md"
        f.write_text(content, encoding="utf-8")
        errors = validate_report(f)
        assert any("Summary" in e for e in errors)

    def test_missing_test_results_summary(self, tmp_path):
        content = _VALID_REPORT.replace("## Test Results Summary\n", "## REMOVED\n")
        f = tmp_path / "report.md"
        f.write_text(content, encoding="utf-8")
        errors = validate_report(f)
        assert any("Test Results Summary" in e for e in errors)

    def test_missing_overall_status(self, tmp_path):
        # Remove only the instance in the Test Results Summary section
        content = _VALID_REPORT.replace(
            "## Test Results Summary\n\n**Overall Status:**",
            "## Test Results Summary\n\nStatus: done",
        )
        # Also remove the one in Test Results sub-section under Summary
        content = content.replace("**Overall Status:** ✅ PASS\n\n| Test", "Status: PASS\n\n| Test")
        f = tmp_path / "report.md"
        f.write_text(content, encoding="utf-8")
        errors = validate_report(f)
        assert any("Overall Status" in e for e in errors)

    def test_missing_test_sections(self, tmp_path):
        # Replace numbered test headings so none match '### Test \d'
        content = re.sub(r'^### Test (\d)', r'#### Subtest \1', _VALID_REPORT, flags=re.MULTILINE)
        f = tmp_path / "report.md"
        f.write_text(content, encoding="utf-8")
        errors = validate_report(f)
        assert any("test section" in e.lower() for e in errors)

    def test_missing_end_of_report(self, tmp_path):
        content = _VALID_REPORT.replace("END OF REPORT\n", "")
        f = tmp_path / "report.md"
        f.write_text(content, encoding="utf-8")
        errors = validate_report(f)
        assert any("END OF REPORT" in e for e in errors)

    def test_multiple_errors_all_reported(self, tmp_path):
        # Remove main heading and END OF REPORT — both should appear in errors
        content = _VALID_REPORT.replace("# DevStack Integration Testing\n", "")
        content = content.replace("END OF REPORT\n", "")
        f = tmp_path / "report.md"
        f.write_text(content, encoding="utf-8")
        errors = validate_report(f)
        assert len(errors) >= 2
        assert any("DevStack Integration Testing" in e for e in errors)
        assert any("END OF REPORT" in e for e in errors)

    def test_nonexistent_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            validate_report(tmp_path / "nonexistent.md")

    def test_empty_file_returns_all_errors(self, tmp_path):
        f = tmp_path / "report.md"
        f.write_text("", encoding="utf-8")
        errors = validate_report(f)
        # All required sections should be missing from an empty file
        assert len(errors) == len(REQUIRED_SECTIONS) + 1  # +1 for test sections check

    def test_test_heading_variants_accepted(self, tmp_path):
        # '### Test 2: Something' should satisfy the test-section check
        content = _VALID_REPORT + "\n### Test 2: Another test\n\nExtra test.\n"
        f = tmp_path / "report.md"
        f.write_text(content, encoding="utf-8")
        assert validate_report(f) == []
