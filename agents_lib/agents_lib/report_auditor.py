"""
Common report audit/validation utility shared by all agents.

Each agent defines its own AuditRule list and calls audit_report() to
validate AI-generated reports before saving or posting to the forge.
The devstack-test-agent uses this via a thin wrapper in report_validator.py.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple


@dataclass
class AuditRule:
    """A single validation rule for a report."""

    description: str
    check: Callable[[str], bool]  # receives report text; returns True if rule PASSES

    @classmethod
    def must_contain(cls, text: str) -> "AuditRule":
        """Rule: report must contain the given literal string."""
        return cls(
            description=f"Must contain: {text!r}",
            check=lambda content: text in content,
        )

    @classmethod
    def must_match(cls, pattern: str, description: str) -> "AuditRule":
        """Rule: report must match the given regex pattern (MULTILINE)."""
        compiled = re.compile(pattern, re.MULTILINE)
        return cls(
            description=description,
            check=lambda content: bool(compiled.search(content)),
        )

    @classmethod
    def must_start_with(cls, prefix: str) -> "AuditRule":
        """Rule: report must start with the given prefix (after stripping leading whitespace)."""
        return cls(
            description=f"Must start with: {prefix!r}",
            check=lambda content: content.lstrip().startswith(prefix),
        )

    @classmethod
    def must_contain_one_of(cls, options: List[str], description: str) -> "AuditRule":
        """Rule: report must contain at least one of the given strings."""
        return cls(
            description=description,
            check=lambda content: any(opt in content for opt in options),
        )


def audit_report(
    report_content: str,
    rules: List[AuditRule],
) -> Tuple[bool, List[str]]:
    """Validate a report against a list of rules.

    Args:
        report_content: The full text of the report to validate.
        rules:          List of AuditRule objects to check.

    Returns:
        (passed, failures) where:
            passed   — True if all rules pass.
            failures — List of human-readable failure descriptions (empty if passed).
    """
    failures = [rule.description for rule in rules if not rule.check(report_content)]
    return len(failures) == 0, failures


def audit_report_file(
    report_path: Path,
    rules: List[AuditRule],
) -> Tuple[bool, List[str]]:
    """Read a report file and validate it. Returns (passed, failures).

    Returns (False, ["File not found: ..."]) if the file doesn't exist.
    """
    if not report_path.exists():
        return False, [f"File not found: {report_path}"]
    content = report_path.read_text(encoding="utf-8")
    return audit_report(content, rules)


def format_audit_failures(failures: List[str]) -> str:
    """Format a list of audit failures into a human-readable string for logging."""
    if not failures:
        return "All audit rules passed."
    lines = [f"Report has {len(failures)} format issue(s):"]
    for f in failures:
        lines.append(f"  - {f}")
    return "\n".join(lines)


def build_audit_prompt(failures: List[str], save_path: Optional[str] = None) -> str:
    """Build a prompt asking the AI to fix the listed report issues."""
    path_note = f" at `{save_path}`" if save_path else ""
    lines = [
        f"The report you wrote{path_note} has {len(failures)} format issue(s) that must be fixed:",
    ]
    for i, f in enumerate(failures, 1):
        lines.append(f"  {i}. {f}")
    lines.extend([
        "",
        "Please re-write the report to fix these issues exactly.",
        "Do not add preamble or commentary — write the corrected report directly.",
    ])
    return "\n".join(lines)
