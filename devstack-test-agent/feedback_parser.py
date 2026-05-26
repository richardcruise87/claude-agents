"""
Parse and validate DevStack test feedback files.

Feedback files let users request re-runs or specific test cases for a change
that has already been tested.  Lines beginning with '#' are treated as comments
and ignored.

Feedback file path:
    {reviews_directory}/devstack_test_{change_number}_ps{patchset}_feedback.txt

Supported content formats::

    # Re-run the full test suite:
    Re-run all tests

    # Request specific tests via prefix:
    Run test: octavia_tempest_plugin.tests.api.v2.test_load_balancer.LoadBalancerScenarioTest.test_lb_crd

    # Or bare test names (one per line):
    octavia_tempest_plugin.tests.api.v2.test_listener.ListenerScenarioTest.test_listener_crd
    tempest.api.network.test_networks.NetworksTest.test_create_delete_network
"""
import re
import logging
from pathlib import Path
from typing import List, Optional, Tuple

from agents_lib import read_feedback_file

logger = logging.getLogger(__name__)

# Characters that are dangerous in shell contexts
_SHELL_INJECTION_CHARS = re.compile(r'[;|&$`\\<>()\n\r]')

# A valid Python dotted-path test name: letters, digits, underscores, dots only
_TEST_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_][a-zA-Z0-9_.]*$')

# Allowed test name prefixes (compared case-insensitively for the sentinel only;
# test names themselves are compared as-is so casing is preserved)
_ALLOWED_PREFIXES = ("octavia", "tempest")

# Re-run-all sentinel (matched case-insensitively anywhere in a non-comment line)
_RERUN_ALL_SENTINEL = "re-run all tests"

# Pattern for explicit "Run test: <name>" lines
_RUN_TEST_PREFIX = re.compile(r'^run\s+test[s]?\s*:\s*(.+)', re.IGNORECASE)


def _feedback_path(change_number: str, patchset: int, reviews_dir: Path) -> Path:
    """Return the expected feedback file path for a given change/patchset."""
    return reviews_dir / f"devstack_test_{change_number}_ps{patchset}_feedback.txt"


def has_devstack_feedback(change_number: str, patchset: int, reviews_dir: Path) -> bool:
    """Return True if a feedback file exists for this change/patchset.

    Does NOT consume (delete) the file — use read_devstack_feedback() for that.
    """
    return _feedback_path(change_number, patchset, reviews_dir).exists()


def read_devstack_feedback(
    change_number: str,
    patchset: int,
    reviews_dir: Path,
) -> Optional[str]:
    """Read and consume the feedback file for a given change/patchset.

    Returns raw file text, or None if no feedback file exists.
    The file is deleted after reading (consumed-once semantics).
    """
    return read_feedback_file(_feedback_path(change_number, patchset, reviews_dir))


def parse_feedback(raw_text: str) -> Tuple[bool, List[str]]:
    """Parse raw feedback text into (rerun_all, test_names).

    Returns:
        (True, [])      — user requested a full re-run
        (False, names)  — list of specific test names extracted from content
    """
    test_names: List[str] = []

    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue

        # Sentinel check (case-insensitive)
        if _RERUN_ALL_SENTINEL in stripped.lower():
            return (True, [])

        # Explicit "Run test: <name>" prefix
        m = _RUN_TEST_PREFIX.match(stripped)
        if m:
            test_names.append(m.group(1).strip())
            continue

        # Bare test name starting with an allowed prefix
        if stripped.startswith(_ALLOWED_PREFIXES):
            test_names.append(stripped)

    return (False, test_names)


def validate_test_names(raw_names: List[str]) -> Tuple[List[str], List[str]]:
    """Validate a list of candidate test names.

    A name is valid when:
    1. It contains no shell injection characters.
    2. It matches the Python dotted-path pattern (letters, digits, underscores, dots).
    3. It starts with an allowed prefix ('octavia' or 'tempest').

    Returns:
        (valid_names, rejected_names)
    """
    valid: List[str] = []
    rejected: List[str] = []

    for name in raw_names:
        if not name:
            rejected.append(f"{name!r} (empty string)")
        elif _SHELL_INJECTION_CHARS.search(name):
            rejected.append(f"{name!r} (shell injection characters)")
        elif not name.startswith(_ALLOWED_PREFIXES):
            rejected.append(f"{name!r} (must start with 'octavia' or 'tempest')")
        elif not _TEST_NAME_PATTERN.match(name):
            rejected.append(f"{name!r} (invalid test name format — use dotted Python path)")
        else:
            valid.append(name)

    return (valid, rejected)


def process_feedback(
    change_number: str,
    patchset: int,
    reviews_dir: Path,
) -> Optional[Tuple[bool, List[str]]]:
    """High-level entry point: read, parse, and validate feedback in one call.

    Returns:
        None                  — no feedback file exists
        (True, [])            — re-run all tests
        (False, valid_names)  — run only these specific tests (may be empty if
                                all names were rejected, caller should log and skip)
    """
    raw = read_devstack_feedback(change_number, patchset, reviews_dir)
    if raw is None:
        return None

    rerun_all, raw_names = parse_feedback(raw)
    if rerun_all:
        logger.info("Feedback: full re-run requested for change %s ps%s", change_number, patchset)
        return (True, [])

    valid, rejected = validate_test_names(raw_names)
    if rejected:
        rejected_str = "; ".join(rejected)
        msg = f"Feedback for #{change_number} ps{patchset} — {len(rejected)} test name(s) rejected: {rejected_str}"
        logger.warning(msg)
        print(f"   ⚠️  {msg}")
    if valid:
        logger.info(
            "Feedback: running %d specific test(s) for change %s ps%s",
            len(valid), change_number, patchset,
        )
    return (False, valid)
