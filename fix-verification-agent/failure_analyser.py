"""
AI-powered failure analysis for the Fix Verification Agent.

After a verification script fails, this module asks the model to classify
the failure as FIX_FAILURE, ENVIRONMENTAL, or INCONCLUSIVE and explain its
reasoning. Only ENVIRONMENTAL failures trigger a retry.
"""
from dataclasses import dataclass

from agents_lib import create_model_client
from prompts import get_failure_analysis_prompt


@dataclass
class FailureAnalysis:
    """Result of an AI failure analysis."""
    cause: str           # "FIX_FAILURE" | "ENVIRONMENTAL" | "INCONCLUSIVE"
    explanation: str     # Plain-text reasoning from the model
    should_retry: bool   # True only for ENVIRONMENTAL failures


async def analyse_failure(
    exit_code: int,
    execution_time: float,
    timeout_exceeded: bool,
    stdout: str,
    stderr: str,
    bug_number: str,
    bug_title: str,
    root_cause: str,
    patch_description: str,
    config: dict,
    context_section: str = "",
) -> FailureAnalysis:
    """
    Classify a verification failure using the AI model.

    Returns a FailureAnalysis with the cause and whether to retry.
    Falls back to INCONCLUSIVE (no retry) if the model call fails.
    """
    # Fast path: explicit reproduction marker means the bug still fires.
    if "BUG REPRODUCED" in stdout.upper():
        return FailureAnalysis(
            cause="FIX_FAILURE",
            explanation=(
                "The reproduction script's 'BUG REPRODUCED' marker was found in "
                "the output, confirming the bug still triggers after the patch."
            ),
            should_retry=False,
        )

    # Fast path: obvious environment indicators without AI call.
    combined = (stdout + "\n" + stderr).lower()
    env_fast = [
        "connection refused", "503 service unavailable",
        "could not resolve host", "network is unreachable",
        "authentication failed", "unauthorized", "keystone",
    ]
    if timeout_exceeded or any(kw in combined for kw in env_fast):
        reason = "Script timed out" if timeout_exceeded else "Environment indicator detected in output"
        return FailureAnalysis(
            cause="ENVIRONMENTAL",
            explanation=f"{reason} — this is likely an infrastructure issue unrelated to the fix.",
            should_retry=True,
        )

    # AI analysis for ambiguous cases.
    # Prepend cross-run context so the analyser benefits from accumulated learnings.
    prompt = get_failure_analysis_prompt(
        bug_number=bug_number,
        bug_title=bug_title,
        root_cause=root_cause,
        patch_description=patch_description,
        exit_code=exit_code,
        execution_time=execution_time,
        timeout_exceeded=timeout_exceeded,
        stdout=stdout,
        stderr=stderr,
    )

    if context_section:
        prompt = context_section + "\n\n---\n\n" + prompt

    try:
        client = create_model_client(config)
        result = await client.query(prompt=prompt)
        return _parse_analysis(result.text)
    except Exception as exc:  # pylint: disable=broad-except
        print(f"   ⚠️  Failure analysis call failed: {exc}")
        return FailureAnalysis(
            cause="INCONCLUSIVE",
            explanation=f"Analysis could not be completed: {exc}. Treating as no-retry.",
            should_retry=False,
        )


def _parse_analysis(response_text: str) -> FailureAnalysis:
    """Parse the model's classification response."""
    lines = response_text.strip().splitlines()
    if not lines:
        return FailureAnalysis(
            cause="INCONCLUSIVE",
            explanation="Empty response from model.",
            should_retry=False,
        )

    first = lines[0].strip().upper()
    explanation = "\n".join(lines[1:]).strip()

    if "FIX_FAILURE" in first:
        return FailureAnalysis(cause="FIX_FAILURE", explanation=explanation, should_retry=False)
    if "ENVIRONMENTAL" in first:
        return FailureAnalysis(cause="ENVIRONMENTAL", explanation=explanation, should_retry=True)
    return FailureAnalysis(cause="INCONCLUSIVE", explanation=explanation, should_retry=False)


def format_analysis_section(
    attempt_number: int,
    analysis: FailureAnalysis,
    decision: str,
) -> str:
    """Format a failure analysis as a markdown section for the report."""
    cause_emoji = {
        "FIX_FAILURE": "❌",
        "ENVIRONMENTAL": "⚠️",
        "INCONCLUSIVE": "❓",
    }.get(analysis.cause, "❓")

    lines = [
        f"#### Failure Analysis (Attempt {attempt_number})",
        "",
        f"**Cause:** {cause_emoji} {analysis.cause}",
        "",
        analysis.explanation,
        "",
        f"**Decision:** {decision}",
        "",
    ]
    return "\n".join(lines)


def format_verification_result(
    status: str,
    attempts: int,
    patch_description: str,
    analyses: list,
) -> str:
    """Generate the final verification summary section."""
    emoji = {"RESOLVED": "✅", "NOT_RESOLVED": "❌", "ENVIRONMENTAL_ERROR": "⚠️"}.get(status, "❓")

    lines = [
        "## Verification Summary",
        "",
        f"**Status:** {emoji} {status}",
        f"**Attempts:** {attempts}",
        f"**Patch:** {patch_description}",
        "",
    ]

    if status == "RESOLVED":
        lines += [
            "The proposed fix was applied and the reproduction script confirmed "
            "the bug no longer triggers. The fix is a candidate for acceptance.",
            "",
        ]
    elif status == "NOT_RESOLVED":
        last = analyses[-1] if analyses else None
        lines += [
            "The proposed fix was applied but the bug still triggers (or the "
            "patch introduced a different failure). The fix requires revision.",
            "",
        ]
        if last:
            lines += [f"**Final analysis:** {last.explanation}", ""]
    elif status == "ENVIRONMENTAL_ERROR":
        lines += [
            "All verification attempts failed due to infrastructure issues "
            "unrelated to the fix. **This is not a verdict on the fix.** "
            "Re-run when the DevStack environment is healthy.",
            "",
            "```bash",
            "octavia-verify-fix --bug <bug_number>",
            "```",
            "",
        ]

    return "\n".join(lines)
