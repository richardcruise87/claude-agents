"""
Reproduction report generation functionality.

Generates comprehensive markdown reports with attempts, results, and analysis.
"""
from datetime import datetime
from typing import List, Optional
from pathlib import Path
from triage_parser import TriageReport
from script_executor import ExecutionResult, format_execution_report
from devstack_health import DevStackHealth, format_health_report


def generate_report(
    triage: TriageReport,
    health: DevStackHealth,
    attempts: List[tuple],  # List of (script, ExecutionResult, usage_dict)
    final_status: str,
    final_script_path: Optional[Path] = None,
    total_usage: Optional[dict] = None
) -> str:
    """
    Generate comprehensive reproduction report.

    Args:
        triage: Parsed triage report
        health: DevStack health check results
        attempts: List of (script_content, ExecutionResult, usage_dict) tuples
        final_status: Final status (REPRODUCED, NOT_REPRODUCED, ENVIRONMENT_ERROR)
        final_script_path: Path to final successful script (if reproduced)
        total_usage: Combined usage information across all attempts

    Returns:
        Complete markdown report as string
    """
    lines = []

    # Header
    lines.append("# Bug Reproduction Report")
    lines.append("")
    lines.append(f"**Bug ID:** {triage.bug_number}")
    lines.append(f"**Title:** {triage.bug_title}")

    # Status
    if final_status == "REPRODUCED":
        lines.append("**Status:** ✅ REPRODUCED")
    elif final_status == "NOT_REPRODUCED":
        lines.append("**Status:** ❌ NOT REPRODUCED")
    elif final_status == "ENVIRONMENT_ERROR":
        lines.append("**Status:** ⚠️ ENVIRONMENT ERROR")
    else:
        lines.append(f"**Status:** ❓ {final_status}")

    lines.append(f"**Attempts:** {len(attempts)}/{len(attempts)}")
    lines.append(f"**Reproduction Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Triage File:** {triage.triage_file.name}")
    lines.append("")

    # Executive Summary
    lines.append("## Executive Summary")
    lines.append("")
    lines.append(generate_executive_summary(triage, attempts, final_status))
    lines.append("")

    # Triage Summary
    lines.append("## Triage Summary")
    lines.append("")
    lines.append(f"**Severity:** {triage.severity}")
    lines.append(f"**Validation:** {triage.validation_status}")
    lines.append("")
    if triage.root_cause_summary:
        lines.append("### Root Cause (from Triage)")
        lines.append("")
        # Truncate if too long
        root_cause = triage.root_cause_summary
        if len(root_cause) > 1000:
            root_cause = root_cause[:1000] + "..."
        lines.append(root_cause)
        lines.append("")

    # DevStack Health Check
    lines.append(format_health_report(health))
    lines.append("")

    # Reproduction Attempts
    lines.append("## Reproduction Attempts")
    lines.append("")

    for i, attempt_data in enumerate(attempts, 1):
        # Handle both old format (script, result) and new format (script, result, usage_dict)
        if len(attempt_data) == 3:
            script, result, usage_dict = attempt_data
        else:
            script, result = attempt_data
            usage_dict = None

        lines.append(format_execution_report(result, i))
        lines.append("")

        # Add usage info for this attempt if available
        if usage_dict and (usage_dict.get('usage') or usage_dict.get('cost_usd') is not None):
            from agents_lib import format_usage_info
            attempt_usage = format_usage_info(
                usage_data=usage_dict.get('usage'),
                cost_usd=usage_dict.get('cost_usd'),
                model=usage_dict.get('model'),
                duration_ms=usage_dict.get('duration_ms')
            )
            # Use smaller heading for attempt-specific usage
            attempt_usage = attempt_usage.replace("## Token Usage & Cost", f"### Token Usage (Attempt {i})")
            lines.append(attempt_usage)
            lines.append("")

        lines.append("**Script Used:**")
        lines.append("```bash")
        lines.append(script)
        lines.append("```")
        lines.append("")
        lines.append("---")
        lines.append("")

    # Root Cause Analysis (if reproduced)
    if final_status == "REPRODUCED":
        lines.append("## Root Cause Analysis")
        lines.append("")
        lines.append(generate_root_cause_analysis(triage, attempts))
        lines.append("")

    # Final Reproduction Script (if successful)
    if final_status == "REPRODUCED" and final_script_path:
        lines.append("## Final Reproduction Script")
        lines.append("")
        lines.append(f"**Location:** `{final_script_path}`")
        lines.append("")
        # Include the successful script
        successful_script = None
        for script, result in attempts:
            if result.success or result.error_type == "BUG_REPRODUCED":
                successful_script = script
                break
        if successful_script:
            lines.append("```bash")
            lines.append(successful_script)
            lines.append("```")
            lines.append("")

    # Recommendations
    lines.append("## Recommendations")
    lines.append("")
    lines.append(generate_recommendations(triage, attempts, final_status))
    lines.append("")

    # Total usage across all attempts
    if total_usage:
        from agents_lib import format_usage_info
        lines.append("---")
        lines.append("")
        total_usage_section = format_usage_info(
            usage_data=total_usage.get('usage'),
            cost_usd=total_usage.get('cost_usd'),
            model=total_usage.get('model'),
            duration_ms=total_usage.get('duration_ms')
        )
        total_usage_section = total_usage_section.replace("## Token Usage & Cost", "## Total Token Usage & Cost")
        lines.append(total_usage_section)
        lines.append("")

    # Footer
    lines.append("---")
    lines.append("")
    lines.append("*Generated by Octavia Bug Reproduction Agent*")
    lines.append("")

    return "\n".join(lines)


def generate_executive_summary(
    triage: TriageReport,
    attempts: List[tuple],
    final_status: str
) -> str:
    """Generate executive summary section."""
    if final_status == "REPRODUCED":
        return """The bug **{triage.bug_title}** (#{triage.bug_number}) was **successfully reproduced**
in {len(attempts)} attempt(s). The reproduction confirms the issue identified in the triage report.

The bug was reproduced using
{'the triage reproduction steps' if len(attempts) == 1 else 'refined reproduction scripts'}.
Execution took {last_result.execution_time:.1f} seconds on the final attempt.
"""

    elif final_status == "NOT_REPRODUCED":
        return """The bug **{triage.bug_title}** (#{triage.bug_number}) could **not be reproduced**
after {len(attempts)} attempt(s).

This could indicate:
- The bug is environment-specific or requires specific conditions not met in this DevStack
- The bug is intermittent/timing-dependent (race condition)
- The bug has been fixed but triage wasn't updated
- The reproduction steps in the triage are incomplete or incorrect

Manual investigation is recommended.
"""

    elif final_status == "ENVIRONMENT_ERROR":
        return """Reproduction of bug **{triage.bug_title}** (#{triage.bug_number}) was **aborted**
due to DevStack environment issues.

The reproduction environment is not healthy and needs to be fixed before attempting reproduction.
See the DevStack Health Check section below for details.
"""

    else:
        return """Reproduction of bug **{triage.bug_title}** (#{triage.bug_number}) completed with
status: **{final_status}** after {len(attempts)} attempt(s).
"""


def generate_root_cause_analysis(
    triage: TriageReport,
    attempts: List[tuple]
) -> str:
    """Generate root cause analysis for reproduced bugs."""
    analysis = []

    analysis.append("The bug was successfully reproduced, confirming the issue described in the triage report.")
    analysis.append("")
    analysis.append("### Confirmed Behavior")
    analysis.append("")
    analysis.append(f"- **Bug:** {triage.bug_title}")
    analysis.append(f"- **Severity:** {triage.severity}")
    analysis.append("")

    if triage.root_cause_summary:
        analysis.append("### Root Cause (from Triage)")
        analysis.append("")
        analysis.append(triage.root_cause_summary[:500])
        if len(triage.root_cause_summary) > 500:
            analysis.append("...")
        analysis.append("")

    analysis.append("### Reproduction Details")
    analysis.append("")
    analysis.append(f"- Successfully reproduced after {len(attempts)} attempt(s)")
    analysis.append("- The reproduction script can be used for CI testing and validation of fixes")
    analysis.append("- Developers can use this script to verify their fix resolves the issue")

    return "\n".join(analysis)


def generate_recommendations(
    triage: TriageReport,
    attempts: List[tuple],
    final_status: str
) -> str:
    """Generate recommendations section."""
    recommendations = []

    if final_status == "REPRODUCED":
        recommendations.append("**Next Steps:**")
        recommendations.append("")
        recommendations.append("1. ✅ Use the reproduction script to validate any proposed fixes")
        recommendations.append("2. ✅ Add the reproduction script to CI test suite to prevent regressions")
        recommendations.append("3. ✅ Review the triage report for proposed fix strategies")
        recommendations.append("4. ✅ Implement the fix and verify with this reproduction script")
        recommendations.append("5. ✅ Update bug status on Launchpad once fixed")

    elif final_status == "NOT_REPRODUCED":
        recommendations.append("**Next Steps:**")
        recommendations.append("")
        recommendations.append("1. 🔍 Review the triage reproduction steps for accuracy")
        recommendations.append("2. 🔍 Check if the bug requires specific timing or load conditions")
        recommendations.append("3. 🔍 Verify DevStack configuration matches the bug environment")
        recommendations.append("4. 🔍 Try manual reproduction following the triage steps exactly")
        recommendations.append("5. 🔍 Check if the bug has been fixed in recent commits")
        recommendations.append("6. 🔍 Consider if the bug is intermittent (run multiple times)")

    elif final_status == "ENVIRONMENT_ERROR":
        recommendations.append("**Required Actions:**")
        recommendations.append("")
        recommendations.append("1. ⚠️ Fix DevStack environment issues (see Health Check section)")
        recommendations.append("2. ⚠️ Restart required services that are down")
        recommendations.append("3. ⚠️ Verify OpenStack API connectivity")
        recommendations.append("4. ⚠️ Ensure sufficient disk space")
        recommendations.append("5. ⚠️ Re-run reproduction after environment is healthy")

    return "\n".join(recommendations)


if __name__ == "__main__":
    # Test report generation
    from dataclasses import dataclass
    from devstack_health import DevStackHealth

    print("Testing report generation...")

    # Create mock triage
    @dataclass
    class MockTriage:
        bug_number: str = "12345"
        bug_title: str = "Test bug"
        severity: str = "HIGH"
        validation_status: str = "VALID BUG"
        root_cause_summary: str = "This is a test root cause"
        triage_file: Path = Path("test.md")

    # Create mock health
    health = DevStackHealth(
        all_healthy=True,
        service_status={"devstack@o-api.service": True},
        api_reachable=True,
        disk_space_gb=50.0,
        errors=[]
    )

    # Create mock attempt
    result = ExecutionResult(
        success=True,
        exit_code=0,
        stdout="Test output",
        stderr="",
        execution_time=10.5,
        timeout_exceeded=False,
        error_type="SUCCESS"
    )

    script = "#!/bin/bash\necho 'test'\nexit 0"
    attempts = [(script, result)]

    # Generate report
    report = generate_report(
        MockTriage(),
        health,
        attempts,
        "REPRODUCED",
        Path("/tmp/script.sh")
    )

    # Verify report contains key sections
    assert "# Bug Reproduction Report" in report
    assert "## Executive Summary" in report
    assert "## DevStack Health Check" in report
    assert "## Reproduction Attempts" in report
    assert "## Root Cause Analysis" in report
    assert "## Recommendations" in report

    print("✓ Report structure validated")
    print(f"✓ Report length: {len(report)} characters")
    print("\n✅ Report generation test passed!")
