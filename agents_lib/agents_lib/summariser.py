"""
Agent output summariser for Claude Agents.

Provides a second lightweight AI call that reads a completed agent report and
produces a short structured summary. The summary can be printed to stdout
(--print-summary) and/or posted to the relevant external system in place of
the full report (--post-summary / feedback.post_summary: true).

Public API
----------
generate_summary(report_path, prompt_path, config) -> str | None
    Read *report_path*, build a prompt from *prompt_path*, call the model,
    and return the summary text.  Returns None when the report file does not
    exist.

print_summary(summary, report_path)
    Print the summary to stdout in a formatted block.

needs_summary(args, config) -> bool
    Return True when summary generation is required for this invocation
    (either --print-summary, --post-summary, or feedback.post_summary in
    config).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import argparse

_SEPARATOR = "─" * 60
_MAX_REPORT_CHARS = 8000


def generate_summary(
    report_path: "Path | str",
    prompt_path: "Path | str",
    config: dict,
) -> "str | None":
    """Generate a short summary of an agent report.

    Reads the report at *report_path*, combines it with the summary prompt
    at *prompt_path*, and makes a single AI call (no tools) to produce a
    concise structured summary.

    Args:
        report_path:  Path to the completed agent report markdown file.
        prompt_path:  Path to the agent-specific summary prompt .txt file.
        config:       Agent config dict (used to create the model client).

    Returns:
        Summary text as a string, or None if the report file does not exist.
    """
    report_path = Path(report_path)
    prompt_path = Path(prompt_path)

    if not report_path.exists():
        return None

    report_content = report_path.read_text(encoding="utf-8")
    if len(report_content) > _MAX_REPORT_CHARS:
        report_content = report_content[:_MAX_REPORT_CHARS] + "\n\n...(truncated for summary)"

    if not prompt_path.exists():
        raise FileNotFoundError(
            f"Summary prompt not found: {prompt_path}"
        )
    prompt_template = prompt_path.read_text(encoding="utf-8")
    prompt = prompt_template.replace("{report_content}", report_content)

    from .model_client import create_model_client  # noqa: PLC0415

    client = create_model_client(config)

    async def _run() -> str:
        result = await client.query(prompt=prompt, tools=None)
        return result.text.strip()

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures  # noqa: PLC0415
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, _run())
                return future.result(timeout=120)
        return loop.run_until_complete(_run())
    except RuntimeError:
        return asyncio.run(_run())


def print_summary(summary: str, report_path: "Path | str | None" = None) -> None:
    """Print a formatted summary block to stdout.

    Args:
        summary:      The summary text to display.
        report_path:  Optional path to the source report (printed as a footer).
    """
    print(f"\n{_SEPARATOR}")
    print("Summary")
    print(_SEPARATOR)
    print(summary)
    print(_SEPARATOR)
    if report_path:
        print(f"Report: {report_path}")
    print()


def needs_summary(args: "argparse.Namespace", config: dict) -> bool:
    """Return True if summary generation is needed for this invocation.

    Checks --print-summary, --post-summary (CLI flags), and
    feedback.post_summary (config).
    """
    if getattr(args, "print_summary", False):
        return True
    if getattr(args, "post_summary", False):
        return True
    if config.get("feedback", {}).get("post_summary", False):
        return True
    return False
