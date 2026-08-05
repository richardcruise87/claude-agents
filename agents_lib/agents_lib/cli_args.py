"""
Shared CLI argument parsing helpers for Claude Agents.

Provides:
  - HelpOnErrorParser   — ArgumentParser subclass that prints full --help on any
                          error, not just the short usage line.
  - add_bug_args()      — Launchpad bug targeting (--bug, --url, --output-dir,
                          --skip-tracking).
  - add_change_args()   — Forge change targeting (--change, --patchset, --url,
                          --output-dir, --skip-tracking).
  - add_jira_args()     — JIRA issue targeting (--issue, --url, --output-dir,
                          --skip-tracking).
  - add_post_args()     — External posting flags (--no-post, --post-only).
  - resolve_bug_target()     — Extract (bug_id, output_dir, skip_tracking) from
                               parsed args.
  - resolve_change_target()  — Extract (change_ref, patchset, output_dir,
                               skip_tracking) from parsed args.
  - resolve_jira_target()    — Extract (issue_key, output_dir, skip_tracking)
                               from parsed args.
  - confirm_reprocess()      — Prompt the user before re-processing a tracked
                               item (skipped when --skip-tracking is set).

URL validation
--------------
Launchpad bug URLs must have hostname ``bugs.launchpad.net`` or
``launchpad.net`` and contain a numeric bug ID in the path
(e.g. ``/bugs/2150752`` or ``/+bug/2150752``).

Forge (Gerrit/GitHub/GitLab) URLs are validated against the base URL stored in
``config["forge_base_url"]`` (or ``config.get("gerrit_base_url")`` as a
fallback), plus the well-known public hosts ``github.com`` and ``gitlab.com``.

JIRA URLs are validated against the hostname of ``config["jira"]["base_url"]``.

Mutual exclusion
----------------
``--bug`` and ``--url`` are mutually exclusive (bug agents).
``--change``/``--patchset`` and ``--url`` are mutually exclusive (forge agents).
``--issue`` and ``--url`` are mutually exclusive (JIRA agent).
``--patchset`` without ``--change`` raises an error.
``--post-only`` and ``--no-post`` are mutually exclusive.
"""

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


# ---------------------------------------------------------------------------
# HelpOnErrorParser
# ---------------------------------------------------------------------------

class HelpOnErrorParser(argparse.ArgumentParser):
    """ArgumentParser that prints the full --help text on any argument error."""

    def error(self, message: str) -> None:
        self.print_help(sys.stderr)
        self.exit(2, f"\nerror: {message}\n")


# ---------------------------------------------------------------------------
# Internal URL helpers
# ---------------------------------------------------------------------------

_LAUNCHPAD_HOSTS = {"bugs.launchpad.net", "launchpad.net"}
_PUBLIC_FORGE_HOSTS = {"github.com", "gitlab.com"}

_LP_BUG_RE = re.compile(r'/(?:bugs?|[+]bug)/(\d+)', re.IGNORECASE)


def _extract_launchpad_bug_id(url: str) -> str:
    """Return the bug number embedded in a Launchpad URL, or raise ValueError."""
    m = _LP_BUG_RE.search(url)
    if not m:
        raise ValueError(
            f"Cannot extract a bug number from URL: {url!r}\n"
            "Expected a path like /bugs/2150752 or /+bug/2150752"
        )
    return m.group(1)


def _forge_allowed_hosts(config: dict) -> set:
    """Build the set of valid hostname stems for forge URLs from config."""
    hosts = set(_PUBLIC_FORGE_HOSTS)
    for key in ("forge_base_url", "gerrit_base_url"):
        raw = config.get(key, "")
        if raw:
            parsed = urlparse(raw)
            if parsed.hostname:
                hosts.add(parsed.hostname.lower())
    return hosts


def _jira_allowed_hosts(config: dict) -> set:
    """Build the set of valid hostname stems for JIRA URLs from config."""
    raw = config.get("jira", {}).get("base_url", "")
    if raw:
        parsed = urlparse(raw)
        if parsed.hostname:
            return {parsed.hostname.lower()}
    return set()


def _extract_change_from_forge_url(url: str) -> str:
    """Parse a change/PR/MR number from a forge URL, or return the URL as-is.

    The forge client's ``get_change_from_url()`` will do the definitive parse
    at runtime; this is a lightweight pre-validation extract used for error
    messages and tracking lookups.
    """
    m = re.search(r'/(?:pull|merge_requests|c/.+/[+])/(\d+)', url)
    if m:
        return m.group(1)
    m = re.search(r'(\d+)\s*$', url)
    if m:
        return m.group(1)
    return url


def _extract_jira_key(url: str) -> str:
    """Extract a JIRA issue key (e.g. PROJ-123) from a URL, or raise ValueError."""
    m = re.search(r'/browse/([A-Z][A-Z0-9_]+-\d+)', url)
    if not m:
        raise ValueError(
            f"Cannot extract a JIRA issue key from URL: {url!r}\n"
            "Expected a path like /browse/PROJ-123"
        )
    return m.group(1)


# ---------------------------------------------------------------------------
# Public URL validators (raise argparse.ArgumentTypeError on failure)
# ---------------------------------------------------------------------------

def validate_launchpad_url(url: str) -> str:
    """Validate that *url* points to a Launchpad bug and return it unchanged."""
    parsed = urlparse(url)
    if not parsed.scheme.startswith("http"):
        raise argparse.ArgumentTypeError(
            f"URL must start with http:// or https://: {url!r}"
        )
    host = (parsed.hostname or "").lower()
    if host not in _LAUNCHPAD_HOSTS:
        raise argparse.ArgumentTypeError(
            f"URL host {host!r} is not a recognised Launchpad host.\n"
            f"  Expected one of: {', '.join(sorted(_LAUNCHPAD_HOSTS))}\n"
            f"  Got: {url!r}"
        )
    try:
        _extract_launchpad_bug_id(url)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return url


def validate_forge_url(url: str, config: dict) -> str:
    """Validate that *url* points to a known forge host and return it unchanged."""
    parsed = urlparse(url)
    if not parsed.scheme.startswith("http"):
        raise argparse.ArgumentTypeError(
            f"URL must start with http:// or https://: {url!r}"
        )
    host = (parsed.hostname or "").lower()
    allowed = _forge_allowed_hosts(config)
    if host not in allowed:
        raise argparse.ArgumentTypeError(
            f"URL host {host!r} is not a recognised forge host.\n"
            f"  Expected one of: {', '.join(sorted(allowed))}\n"
            f"  Got: {url!r}"
        )
    return url


def validate_jira_url(url: str, config: dict) -> str:
    """Validate that *url* points to the configured JIRA instance and return it."""
    parsed = urlparse(url)
    if not parsed.scheme.startswith("http"):
        raise argparse.ArgumentTypeError(
            f"URL must start with http:// or https://: {url!r}"
        )
    host = (parsed.hostname or "").lower()
    allowed = _jira_allowed_hosts(config)
    if allowed and host not in allowed:
        raise argparse.ArgumentTypeError(
            f"URL host {host!r} does not match the configured JIRA instance.\n"
            f"  Expected: {', '.join(sorted(allowed))}\n"
            f"  Got: {url!r}"
        )
    try:
        _extract_jira_key(url)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc
    return url


# ---------------------------------------------------------------------------
# Argument group builders
# ---------------------------------------------------------------------------

def add_bug_args(  # pylint: disable=protected-access
    parser: argparse.ArgumentParser, config: dict
) -> argparse._MutuallyExclusiveGroup:
    """Add Launchpad bug-targeting arguments to *parser*.

    Adds:
      --bug N           Launchpad bug number
      --url URL         Full Launchpad bug URL (mutually exclusive with --bug)
      --output-dir DIR  Override the configured output directory
      --skip-tracking   Always process even if already in the tracking file

    Returns the mutually-exclusive group so callers can add extra args to it.
    """
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--bug",
        metavar="N",
        type=int,
        help="Launchpad bug number to target (e.g. --bug 2150752). "
             "If omitted, the agent processes the next item in the queue.",
    )
    group.add_argument(
        "--url",
        metavar="URL",
        type=validate_launchpad_url,
        help=(
            "Full Launchpad bug URL (e.g. https://bugs.launchpad.net/octavia/+bug/2150752). "
            "Cannot be used together with --bug."
        ),
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        default=None,
        help="Override the configured output directory for reports.",
    )
    parser.add_argument(
        "--skip-tracking",
        action="store_true",
        default=False,
        help="Process the target even if it already appears in the tracking file. "
             "Skips the re-process confirmation prompt.",
    )
    return group


def add_change_args(  # pylint: disable=protected-access
    parser: argparse.ArgumentParser, config: dict
) -> argparse._MutuallyExclusiveGroup:
    """Add forge change-targeting arguments to *parser*.

    Adds:
      --change N        Change / PR / MR number
      --patchset N      Patchset to target (Gerrit only; only valid with --change)
      --url URL         Full forge URL (mutually exclusive with --change/--patchset)
      --output-dir DIR  Override the configured output directory
      --skip-tracking   Always process even if already in the tracking file

    Returns the mutually-exclusive group so callers can add extra args to it.
    """
    def _forge_url_validator(url: str) -> str:
        return validate_forge_url(url, config)

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--change",
        metavar="N",
        help="Change / PR / MR number to target (e.g. --change 982567). "
             "If omitted, the agent processes the next item in the queue.",
    )
    group.add_argument(
        "--url",
        metavar="URL",
        type=_forge_url_validator,
        help=(
            "Full forge URL (e.g. https://review.opendev.org/c/openstack/octavia/+/982567). "
            "Cannot be used together with --change or --patchset."
        ),
    )
    parser.add_argument(
        "--patchset", "-p",
        metavar="N",
        type=int,
        default=None,
        help="Patchset number (Gerrit only). Only valid together with --change. "
             "If omitted, the latest patchset is used.",
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        default=None,
        help="Override the configured output directory for reports.",
    )
    parser.add_argument(
        "--skip-tracking",
        action="store_true",
        default=False,
        help="Process the target even if it already appears in the tracking file. "
             "Skips the re-process confirmation prompt.",
    )
    return group


def add_jira_args(  # pylint: disable=protected-access
    parser: argparse.ArgumentParser, config: dict
) -> argparse._MutuallyExclusiveGroup:
    """Add JIRA issue-targeting arguments to *parser*.

    Adds:
      --issue KEY       JIRA issue key (e.g. --issue PROJ-123)
      --url URL         Full JIRA issue URL (mutually exclusive with --issue)
      --output-dir DIR  Override the configured output directory
      --skip-tracking   Always process even if already in the tracking file

    Returns the mutually-exclusive group so callers can add extra args to it.
    """
    def _jira_url_validator(url: str) -> str:
        return validate_jira_url(url, config)

    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--issue",
        metavar="KEY",
        help="JIRA issue key to target (e.g. --issue PROJ-123). "
             "If omitted, the agent processes issues matching the configured JQL query.",
    )
    group.add_argument(
        "--url",
        metavar="URL",
        type=_jira_url_validator,
        help=(
            "Full JIRA issue URL (e.g. https://myco.atlassian.net/browse/PROJ-123). "
            "Cannot be used together with --issue."
        ),
    )
    parser.add_argument(
        "--output-dir",
        metavar="DIR",
        default=None,
        help="Override the configured output directory for reports.",
    )
    parser.add_argument(
        "--skip-tracking",
        action="store_true",
        default=False,
        help="Process the target even if it already appears in the tracking file. "
             "Skips the re-process confirmation prompt.",
    )
    return group


def add_post_args(  # pylint: disable=protected-access
    parser: argparse.ArgumentParser,
) -> argparse._MutuallyExclusiveGroup:
    """Add external posting control flags to *parser*.

    Adds (mutually exclusive):
      --no-post    Run the agent but suppress all external posting
                   (Launchpad, JIRA, forge) for this invocation.
      --post-only  Skip the agent run; find the latest saved report and
                   post it to the relevant external system.

    Returns the mutually-exclusive group.
    """
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--no-post",
        action="store_true",
        default=False,
        help="Run the agent but do not post results to any external system "
             "(Launchpad / JIRA / forge) for this invocation.",
    )
    group.add_argument(
        "--post-only",
        action="store_true",
        default=False,
        help="Skip the agent run; find the latest saved report for the target "
             "and post it to the relevant external system.",
    )
    return group


def add_summary_args(  # pylint: disable=protected-access
    parser: argparse.ArgumentParser,
) -> argparse._MutuallyExclusiveGroup:
    """Add summary output flags to *parser*.

    Adds (mutually exclusive):
      --print-summary  After the run, generate and print a short AI summary
                       of the output report to stdout.
      --post-summary   After the run, post only the AI-generated summary
                       (not the full report) to the relevant external system.
                       Implies --print-summary.

    Returns the mutually-exclusive group.
    """
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--print-summary",
        action="store_true",
        default=False,
        help="Generate and print a short AI summary of the output report to stdout.",
    )
    group.add_argument(
        "--post-summary",
        action="store_true",
        default=False,
        help=(
            "Post only the AI-generated summary (not the full report) to the "
            "relevant external system (forge / Launchpad / JIRA). "
            "Also prints the summary to stdout."
        ),
    )
    return group


# ---------------------------------------------------------------------------
# Post-parse resolution helpers
# ---------------------------------------------------------------------------

def resolve_bug_target(args: argparse.Namespace, config: dict) -> tuple:
    """Return ``(bug_id, output_dir, skip_tracking)`` from parsed *args*.

    *bug_id* is a string (e.g. ``"2150752"``) or ``None`` (monitoring mode).
    *output_dir* is the resolved :class:`~pathlib.Path` (overridden or from config).
    *skip_tracking* is a bool.
    """
    bug_id = None
    if getattr(args, "bug", None):
        bug_id = str(args.bug)
    elif getattr(args, "url", None):
        try:
            bug_id = _extract_launchpad_bug_id(args.url)
        except ValueError as exc:
            raise SystemExit(f"error: {exc}") from exc

    output_dir = _resolve_output_dir(
        getattr(args, "output_dir", None),
        config.get("triages_output_dir") or config.get("reproductions_output_dir")
        or config.get("proposals_output_dir") or config.get("verifications_output_dir", ""),
    )
    skip_tracking = bool(getattr(args, "skip_tracking", False))
    return bug_id, output_dir, skip_tracking


def resolve_change_target(args: argparse.Namespace, config: dict) -> tuple:
    """Return ``(change_ref, patchset, output_dir, skip_tracking)`` from parsed *args*.

    Raises ``SystemExit`` if ``--patchset`` is used without ``--change``.

    *change_ref* is a string (change number or full URL) or ``None``.
    *patchset* is an ``int`` or ``None``.
    *output_dir* is the resolved :class:`~pathlib.Path`.
    *skip_tracking* is a bool.
    """
    patchset = getattr(args, "patchset", None)
    change_ref = None

    if getattr(args, "change", None):
        change_ref = str(args.change)
    elif getattr(args, "url", None):
        if patchset:
            raise SystemExit(
                "error: --patchset cannot be used with --url; "
                "embed the patchset in the URL or use --change instead."
            )
        change_ref = args.url
    elif patchset:
        raise SystemExit(
            "error: --patchset requires --change."
        )

    cfg_output = (
        config.get("reviews_output_dir") or config.get("reviews_directory", "")
    )
    output_dir = _resolve_output_dir(getattr(args, "output_dir", None), cfg_output)
    skip_tracking = bool(getattr(args, "skip_tracking", False))
    return change_ref, patchset, output_dir, skip_tracking


def resolve_jira_target(args: argparse.Namespace, config: dict) -> tuple:
    """Return ``(issue_key, output_dir, skip_tracking)`` from parsed *args*.

    *issue_key* is a string (e.g. ``"PROJ-123"``) or ``None`` (monitoring mode).
    """
    issue_key = None
    if getattr(args, "issue", None):
        issue_key = args.issue
    elif getattr(args, "url", None):
        try:
            issue_key = _extract_jira_key(args.url)
        except ValueError as exc:
            raise SystemExit(f"error: {exc}") from exc

    cfg_output = config.get("triages_dir") or config.get("plans_dir", "")
    output_dir = _resolve_output_dir(getattr(args, "output_dir", None), cfg_output)
    skip_tracking = bool(getattr(args, "skip_tracking", False))
    return issue_key, output_dir, skip_tracking


def _resolve_output_dir(cli_override: "str | None", config_value: str) -> Path:
    """Return the output directory as a Path, preferring the CLI override."""
    raw = cli_override if cli_override else config_value
    return Path(raw).expanduser() if raw else Path(".")


# ---------------------------------------------------------------------------
# Confirmation helper
# ---------------------------------------------------------------------------

def confirm_reprocess(entity_type: str, identifier: str) -> bool:
    """Prompt the user to confirm re-processing an already-tracked item.

    Returns ``True`` if the user confirms, ``False`` if they decline.
    Should be called only when ``--skip-tracking`` is *not* set.

    *entity_type* is a short label like ``"bug"``, ``"change"``, or ``"issue"``.
    *identifier* is the human-readable ID (bug number, change number, etc.).
    """
    print(
        f"\n⚠️  {entity_type.capitalize()} #{identifier} has already been processed "
        f"and is recorded in the tracking file."
    )
    print("   Re-processing will create a new report.")
    try:
        answer = input("   Proceed anyway? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("y", "yes")
