"""Prompt templates for the fix proposal agent."""
from pathlib import Path
from typing import Optional

from agents_lib import load_agent_prompt

_PROMPTS_DIR = Path(__file__).parent


def get_fix_proposal_prompt(
    bug_number: str,
    bug_title: str,
    triage_file: Path,
    repro_file: Optional[Path],
    repo_path: str,
    proposals_output_dir: str,
    sequence: int,
    feedback: Optional[str] = None,
    provider: str = "anthropic",
) -> str:
    """Return the formatted fix proposal prompt.

    Args:
        bug_number:           Launchpad bug number.
        bug_title:            Bug title.
        triage_file:          Path to the triage report markdown file.
        repro_file:           Path to the reproduction report markdown (or None).
        repo_path:            Path to the relevant source repository in DevStack.
        proposals_output_dir: Directory where the proposal file should be written.
        sequence:             Proposal sequence number (1 = first, 2+ = refinement).
        feedback:             Developer feedback text for refinement runs (or None).
        provider:             AI provider name for provider-specific prompt selection.
    """
    template = load_agent_prompt(
        "fix_proposal",
        provider=provider,
        prompts_dir=_PROMPTS_DIR,
        save_path=proposals_output_dir,
    )

    sequence_note = ""
    if sequence > 1:
        sequence_note = (
            f"\n**NOTE**: This is proposal revision #{sequence}. "
            f"The developer has reviewed the previous proposal and provided feedback.\n"
        )

    feedback_section = ""
    if feedback:
        feedback_section = f"""

## Developer Feedback on Previous Proposal

The developer has reviewed proposal #{sequence - 1} and provided the following feedback.
Address all points raised before generating the revised proposal.

```
{feedback}
```

"""

    repro_section = (
        f"**Reproduction Report**: {repro_file}"
        if repro_file and repro_file.exists()
        else "**Reproduction Report**: Not available — work from triage only."
    )

    formatted = template
    formatted = formatted.replace("{bug_number}", bug_number)
    formatted = formatted.replace("{bug_title}", bug_title)
    formatted = formatted.replace("{triage_file}", str(triage_file))
    formatted = formatted.replace("{repro_section}", repro_section)
    formatted = formatted.replace("{repo_path}", repo_path)
    formatted = formatted.replace("{proposals_output_dir}", proposals_output_dir)
    formatted = formatted.replace("{sequence}", str(sequence))
    formatted = formatted.replace("{sequence_note}", sequence_note)
    formatted = formatted.replace("{feedback_section}", feedback_section)

    return formatted
