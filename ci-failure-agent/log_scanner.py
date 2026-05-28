"""
CI log error scanner.

Scans pre-fetched job log content against a configurable list of patterns,
giving the AI a structured head-start on failure classification rather than
asking it to re-scan the same text manually.

Patterns are loaded from config["log_scan_patterns"] so they can be tuned
per deployment without touching code.
"""

import re
from typing import Dict, List, Tuple


def scan_log_for_errors(
    log_text: str,
    patterns: List[Dict],
) -> List[Tuple[str, str, int]]:
    """Scan log text and return matched lines with their categories.

    Args:
        log_text:  Full or truncated job log content.
        patterns:  List of dicts from config, each with keys:
                     "pattern"  — regex string
                     "category" — label string (e.g. "timeout", "test_failure")

    Returns:
        List of (category, matched_line, line_number) tuples, one per match.
        Empty list when patterns is empty or no matches found.
    """
    results: List[Tuple[str, str, int]] = []
    compiled = []
    for spec in patterns:
        try:
            compiled.append((re.compile(spec["pattern"], re.IGNORECASE), spec["category"]))
        except re.error:
            pass  # skip bad patterns silently

    for lineno, line in enumerate(log_text.splitlines(), start=1):
        for regex, category in compiled:
            if regex.search(line):
                results.append((category, line.rstrip(), lineno))
                break  # one category per line

    return results


def format_scan_results(
    scan_results: List[Tuple[str, str, int]],
    job_name: str,
    max_per_category: int = 3,
) -> str:
    """Format scan results as a compact markdown block for the prompt.

    Args:
        scan_results:     Output of scan_log_for_errors().
        job_name:         Name of the job (used in the header).
        max_per_category: Max matched lines to show per category.

    Returns:
        Markdown string, or empty string when no matches.
    """
    if not scan_results:
        return ""

    # Group by category
    by_category: Dict[str, List[Tuple[str, int]]] = {}
    for category, line, lineno in scan_results:
        by_category.setdefault(category, []).append((line, lineno))

    lines = [f"**Pre-scan matches for `{job_name}`:**"]
    for category, matches in sorted(by_category.items()):
        lines.append(f"- `{category}` ({len(matches)} match{'es' if len(matches) != 1 else ''})")
        for line_text, lineno in matches[:max_per_category]:
            snippet = line_text.strip()[:120]
            lines.append(f"  - L{lineno}: `{snippet}`")
        if len(matches) > max_per_category:
            lines.append(f"  - … and {len(matches) - max_per_category} more")

    return "\n".join(lines)
