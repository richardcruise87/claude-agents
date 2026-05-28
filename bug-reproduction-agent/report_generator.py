"""
Reproduction report generation functionality.

Builds each report section as a string, then uses agents_lib.build_report()
to fill the report_template.md with those sections.  Missing sections receive
the default "Agent provided no data".
"""
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from triage_parser import TriageReport
from script_executor import format_execution_report
from agents_lib import (
    DevStackHealth,
    format_health_report,
    format_usage_info,
    build_report,
    ReportSection,
)
from script_generator import extract_script_changelog

_TEMPLATE_PATH = Path(__file__).parent / "report_template.md"

_SECTION_DEFS = [
    ReportSection("executive_summary"),
    ReportSection("root_cause_from_triage", default="_No root cause summary in triage._"),
    ReportSection("devstack_health"),
    ReportSection("reproduction_attempts", default="_No attempts were made._"),
    ReportSection("root_cause_analysis", default="_Not applicable._"),
    ReportSection("how_reproduced", default="_Not applicable._"),
    ReportSection("final_script", default="_No successful script._"),
    ReportSection("recommendations"),
    ReportSection("usage_info", default="_No usage data available._"),
]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_report(
    triage: TriageReport,
    health: DevStackHealth,
    attempts: List[tuple],  # List of (script, ExecutionResult, usage_dict)
    final_status: str,
    final_script_path: Optional[Path] = None,
    total_usage: Optional[dict] = None,
    reasonings: Optional[List[Optional[str]]] = None,
) -> str:
    """Generate comprehensive reproduction report.

    Args:
        triage:            Parsed triage report.
        health:            DevStack health check results.
        attempts:          List of (script_content, ExecutionResult, usage_dict).
        final_status:      "REPRODUCED", "NOT_REPRODUCED", or "ENVIRONMENT_ERROR".
        final_script_path: Path to the successful script (if reproduced).
        total_usage:       Combined token usage across all attempts.
        reasonings:        AI reasoning text per attempt.

    Returns:
        Complete markdown report string.
    """
    reasonings = reasonings or []

    # Metadata filled by Python
    status_map = {
        "REPRODUCED": "✅ REPRODUCED",
        "NOT_REPRODUCED": "❌ NOT REPRODUCED",
        "ENVIRONMENT_ERROR": "⚠️ ENVIRONMENT ERROR",
    }
    status_line = status_map.get(final_status, f"❓ {final_status}")

    if _TEMPLATE_PATH.exists():
        template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    else:
        template = (
            "# Bug Reproduction Report\n\n**Bug ID:** {BUG_NUMBER}\n"
            "**Title:** {BUG_TITLE}\n**Status:** {STATUS_LINE}\n\n"
            + "\n\n".join(
                f"## {s.name.replace('_', ' ').title()}\n\n{{{{SECTION:{s.name}}}}}"
                for s in _SECTION_DEFS
            )
        )

    # Fill {UPPERCASE} metadata placeholders
    template = template.replace("{BUG_NUMBER}", triage.bug_number)
    template = template.replace("{BUG_TITLE}", triage.bug_title)
    template = template.replace("{STATUS_LINE}", status_line)
    template = template.replace("{ATTEMPTS}", f"{len(attempts)}")
    template = template.replace("{DATE}", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    template = template.replace("{TRIAGE_FILE}", triage.triage_file.name)
    template = template.replace("{SEVERITY}", triage.severity)
    template = template.replace("{VALIDATION_STATUS}", triage.validation_status)

    # Build each analysis section
    sections = {}

    sections["executive_summary"] = _build_executive_summary(triage, attempts, final_status)

    if triage.root_cause_summary:
        root_cause = triage.root_cause_summary
        if len(root_cause) > 1000:
            root_cause = root_cause[:1000] + "..."
        sections["root_cause_from_triage"] = root_cause

    sections["devstack_health"] = format_health_report(health)

    if attempts:
        sections["reproduction_attempts"] = _build_attempts_section(attempts, reasonings)

    if final_status == "REPRODUCED":
        sections["root_cause_analysis"] = _build_root_cause_analysis(triage, attempts)
        sections["how_reproduced"] = _build_how_reproduced(attempts, reasonings)

    if final_status == "REPRODUCED" and final_script_path:
        sections["final_script"] = _build_final_script_section(attempts, final_script_path)

    sections["recommendations"] = _build_recommendations(triage, attempts, final_status)

    if total_usage:
        usage_text = format_usage_info(
            usage_data=total_usage.get("usage"),
            cost_usd=total_usage.get("cost_usd"),
            model=total_usage.get("model"),
            duration_ms=total_usage.get("duration_ms"),
        )
        sections["usage_info"] = usage_text.replace(
            "## Token Usage & Cost", "## Total Token Usage & Cost"
        )

    return build_report(template, sections, _SECTION_DEFS)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _build_executive_summary(
    triage: TriageReport,
    attempts: List[tuple],
    final_status: str,
) -> str:
    if final_status == "REPRODUCED":
        return (
            f"Bug #{triage.bug_number} ({triage.bug_title}) was **successfully reproduced** "
            f"in {len(attempts)} attempt(s). The reproduction script is saved alongside this "
            f"report."
        )
    if final_status == "ENVIRONMENT_ERROR":
        return (
            f"Reproduction of bug #{triage.bug_number} was aborted due to a **DevStack "
            f"environment error**. The agent will retry when the environment is healthy."
        )
    if final_status == "NOT_REPRODUCED":
        if not attempts:
            return (
                f"Bug #{triage.bug_number} could not be processed — no reproduction attempts "
                f"were made."
            )
        return (
            f"Bug #{triage.bug_number} ({triage.bug_title}) could **not be reproduced** "
            f"after {len(attempts)} attempt(s). The issue may require additional context "
            f"or a different reproduction approach."
        )
    # Unknown status — return a safe fallback rather than silently using NOT_REPRODUCED message.
    return (
        f"Bug #{triage.bug_number} reproduction completed with status: {final_status}. "
        f"Attempts: {len(attempts)}."
    )


def _build_attempts_section(
    attempts: List[tuple],
    reasonings: List[Optional[str]],
) -> str:
    lines = []
    for i, attempt_data in enumerate(attempts, 1):
        if len(attempt_data) == 3:
            script, result, usage_dict = attempt_data
        else:
            script, result = attempt_data
            usage_dict = None

        reasoning = reasonings[i - 1] if i <= len(reasonings) else None

        label = "Agent's Approach" if i == 1 else "Agent's Analysis"
        if reasoning:
            lines.append(f"#### {label} (Attempt {i})\n\n{reasoning}\n")

        if i > 1:
            changelog = extract_script_changelog(script)
            if changelog:
                lines.append(f"#### Changes vs Previous Attempt\n\n{changelog}\n")

        lines.append(format_execution_report(result, i))

        if usage_dict and (usage_dict.get("usage") or usage_dict.get("cost_usd") is not None):
            attempt_usage = format_usage_info(
                usage_data=usage_dict.get("usage"),
                cost_usd=usage_dict.get("cost_usd"),
                model=usage_dict.get("model"),
                duration_ms=usage_dict.get("duration_ms"),
            ).replace("## Token Usage & Cost", f"### Token Usage (Attempt {i})")
            lines.append(attempt_usage)

        lines.append("**Script Used:**\n```bash\n" + script + "\n```\n\n---\n")

    return "\n".join(lines)


def _build_root_cause_analysis(triage: TriageReport, attempts: List[tuple]) -> str:
    lines = [
        "The bug was confirmed in the DevStack environment, consistent with the triage "
        "report's root cause analysis.",
        "",
        f"**Bug:** #{triage.bug_number} — {triage.bug_title}",
        f"**Severity:** {triage.severity}",
    ]
    if triage.root_cause_summary:
        lines += ["", "**Triage root cause:**", triage.root_cause_summary[:500]]
    return "\n".join(lines)


def _build_how_reproduced(
    attempts: List[tuple],
    reasonings: List[Optional[str]],
) -> str:
    final_reasoning = next((r for r in reversed(reasonings) if r), None)
    suffix = "See the agent's final analysis below." if final_reasoning else ""
    lines = [
        f"The bug was confirmed after {len(attempts)} attempt(s). {suffix}".strip()
    ]
    if final_reasoning:
        lines += ["", final_reasoning]
    final_script = attempts[-1][0] if attempts else ""
    final_changelog = extract_script_changelog(final_script)
    if final_changelog and len(attempts) > 1:
        lines += ["", "**Key changes that made reproduction possible:**", "", final_changelog]
    return "\n".join(lines)


def _build_final_script_section(
    attempts: List[tuple],
    final_script_path: Path,
) -> str:
    lines = [f"**Location:** `{final_script_path}`", ""]
    successful_script = None
    for script, result, *_ in attempts:
        if result.success or result.error_type == "BUG_REPRODUCED":
            successful_script = script
            break
    if successful_script:
        lines += ["```bash", successful_script, "```"]
    return "\n".join(lines)


def _build_recommendations(
    triage: TriageReport,
    attempts: List[tuple],
    final_status: str,
) -> str:
    if final_status == "REPRODUCED":
        return "\n".join([
            "1. **Review the reproduction script** — it demonstrates the exact steps to "
            "trigger the bug.",
            "2. **Attach the script to the Launchpad bug** — helps developers reproduce "
            "locally.",
            "3. **Fix the root cause** identified in the triage report.",
            "4. **Add a regression test** that fails before the fix and passes after.",
        ])
    if final_status == "ENVIRONMENT_ERROR":
        return "\n".join([
            "1. **Check the DevStack environment** — services may need to be restarted.",
            "2. **Verify network connectivity** to the DevStack deployment.",
            "3. **The agent will retry automatically** on the next healthy run.",
        ])
    return "\n".join([
        "1. **Review the reproduction steps** in the original triage report.",
        "2. **Check if additional environment setup** is required.",
        "3. **Consider refining the triage** reproduction strategy with more detail.",
        "4. **Manually attempt reproduction** using the final script as a starting point.",
    ])
