"""
Validate DevStack test report format.

Checks that a results file written by the AI agent contains all sections
required for forge comment extraction and human review.

Standalone usage:
    python3 report_validator.py path/to/report.md
"""
import re
import sys
from pathlib import Path
from typing import List

# Each tuple: (text that must appear in the report, error message if absent)
REQUIRED_SECTIONS = [
    (
        "# DevStack Integration Testing",
        "Missing main heading '# DevStack Integration Testing'",
    ),
    (
        "## Summary",
        "Missing '## Summary' section",
    ),
    (
        "## Test Results Summary",
        "Missing '## Test Results Summary' section "
        "(required for automated forge comment extraction)",
    ),
    (
        "**Overall Status:**",
        "Missing '**Overall Status:**' line in Test Results Summary",
    ),
    (
        "END OF REPORT",
        "Missing 'END OF REPORT' footer "
        "(signals the report was not truncated mid-write)",
    ),
]


def validate_report(report_path: Path) -> List[str]:
    """Return a list of format errors; an empty list means the report is valid.

    Args:
        report_path: Path to the AI-generated results file.

    Returns:
        List of human-readable error strings. Empty → valid.

    Raises:
        FileNotFoundError: If report_path does not exist.
    """
    content = report_path.read_text(encoding="utf-8")

    errors = [msg for pattern, msg in REQUIRED_SECTIONS if pattern not in content]

    # Match '### Test 1:', '### Test 2:', etc. but not '### Test Results'
    if not re.search(r'^### Test \d', content, re.MULTILINE):
        errors.append(
            "No individual test sections found "
            "(expected at least one '### Test 1: Name' heading)"
        )

    return errors


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: python3 {sys.argv[0]} <report.md>", file=sys.stderr)
        sys.exit(2)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Error: file not found: {path}", file=sys.stderr)
        sys.exit(2)

    issues = validate_report(path)
    if issues:
        print(f"Report has {len(issues)} format issue(s):")
        for issue in issues:
            print(f"  - {issue}")
        sys.exit(1)
    else:
        print("Report is valid.")
        sys.exit(0)
