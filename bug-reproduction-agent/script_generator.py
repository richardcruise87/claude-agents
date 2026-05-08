"""
Script generation and refinement functionality.

Generates reproduction scripts from triage reports and refines them using AI
after failures.
"""
import re
from pathlib import Path
from typing import Dict, Optional
from agents_lib import load_prompt_template, create_model_client
from triage_parser import TriageReport
from script_executor import ExecutionResult


async def generate_initial_script(
    triage: TriageReport,
    config: Dict
) -> tuple:
    """
    Generate initial reproduction script from triage report.

    Args:
        triage: Parsed triage report
        config: Configuration dictionary

    Returns:
        Tuple of (script, usage_dict) where usage_dict contains usage/cost info
    """
    devstack_config = config.get("devstack", {})
    openrc_file = devstack_config.get("openrc_file", "/opt/stack/devstack/openrc")
    devstack_path = devstack_config.get("path", "/opt/stack")

    # Load prompt template
    prompts_dir = Path(__file__).parent / "prompts"
    template = load_prompt_template("script_generation_prompt", prompts_dir)

    # Combine all bash blocks from triage
    reproduction_steps = "\n\n".join(triage.reproduction_steps)

    # Format prompt
    prompt = template.format(
        bug_number=triage.bug_number,
        bug_title=triage.bug_title,
        severity=triage.severity,
        root_cause=triage.root_cause_summary,
        reproduction_steps=reproduction_steps,
        openrc_file=openrc_file,
        devstack_path=devstack_path
    )

    # Use model client to generate script (no tools needed — text-only task)
    _client = create_model_client(config)
    _res = await _client.query(prompt=prompt)
    usage_dict = {
        'usage': _res.usage,
        'cost_usd': _res.cost_usd,
        'model': _res.model,
        'duration_ms': _res.duration_ms,
    }
    script = extract_script_from_response(_res.text)
    reasoning = extract_reasoning_from_response(_res.text)
    return script, reasoning, usage_dict


async def refine_script(
    previous_script: str,
    execution_result: ExecutionResult,
    attempt_number: int,
    triage: TriageReport,
    config: Dict
) -> tuple:
    """
    AI-powered script refinement after failure.

    Args:
        previous_script: Previous script that failed
        execution_result: Results from executing previous script
        attempt_number: Current attempt number (2 or 3)
        triage: Parsed triage report
        config: Configuration dictionary

    Returns:
        Tuple of (script, usage_dict) where usage_dict contains usage/cost info
    """
    # Load prompt template
    prompts_dir = Path(__file__).parent / "prompts"
    template = load_prompt_template("script_refinement_prompt", prompts_dir)

    max_attempts = config.get("reproduction", {}).get("max_attempts", 3)

    # Format prompt
    prompt = template.format(
        bug_number=triage.bug_number,
        bug_title=triage.bug_title,
        attempt_number=attempt_number,
        max_attempts=max_attempts,
        previous_script=previous_script,
        exit_code=execution_result.exit_code,
        stdout=execution_result.stdout[-5000:],  # Last 5000 chars
        stderr=execution_result.stderr[-2000:]  # Last 2000 chars
    )

    # Use model client to refine script (no tools needed — text-only task)
    _client = create_model_client(config)
    _res = await _client.query(prompt=prompt)
    usage_dict = {
        'usage': _res.usage,
        'cost_usd': _res.cost_usd,
        'model': _res.model,
        'duration_ms': _res.duration_ms,
    }
    script = extract_script_from_response(_res.text)
    reasoning = extract_reasoning_from_response(_res.text)
    return script, reasoning, usage_dict


def extract_reasoning_from_response(response: str) -> Optional[str]:
    """
    Extract the agent's plain-text reasoning from a script generation response.

    The response is expected to contain a brief explanation followed by a
    ```bash code block. This function returns the text that appears before
    the first code block, stripped of leading/trailing whitespace.

    Returns None if no meaningful reasoning text is found.
    """
    # Split on the first code fence
    parts = re.split(r'```(?:bash)?', response, maxsplit=1)
    if not parts:
        return None
    before_code = parts[0].strip()
    if len(before_code) < 20:  # Too short to be meaningful
        return None
    return before_code


def extract_script_changelog(script: str) -> Optional[str]:
    """
    Extract the changelog comment block from a refined reproduction script.

    Well-formed refinement scripts include a block like:
        # Attempt N changes vs Attempt N-1:
        #   - Added longer wait for LB ACTIVE
        #   - Changed member network to use correct subnet

    Returns the changelog text, or None if not found.
    """
    match = re.search(
        r'(#\s*Attempt\s+\d+\s+changes.*?)(?=\n[^#]|\Z)',
        script,
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return None
    # Strip leading # from each line for readability
    lines = match.group(1).splitlines()
    cleaned = [re.sub(r'^#\s?', '', ln) for ln in lines]
    return '\n'.join(cleaned).strip()


async def audit_reproduction(
    script: str,
    result: ExecutionResult,
    triage: TriageReport,
    config: Dict,
    reasoning: Optional[str] = None,
) -> bool:
    """
    Ask the AI to verify that the script output actually demonstrates the bug.

    Called when a script exits 0. A fast heuristic pre-check avoids an API
    call for obviously empty scripts (very short output + very fast execution).

    Returns:
        True if the AI confirms the bug was triggered, False otherwise.
    """
    # Check for the explicit marker emitted by well-formed scripts first —
    # this must come before the heuristic so a valid script that happens to
    # have short output (e.g. a quick API call that immediately hits the error)
    # is not incorrectly rejected.
    if "BUG REPRODUCED" in result.stdout.upper():
        return True

    # Fast heuristic: if the output is tiny and execution trivially fast,
    # the script almost certainly did nothing meaningful (e.g. empty script
    # that only ran the cleanup trap).
    if result.execution_time < 5.0 and len(result.stdout.strip()) < 150:
        print("   🔍 Audit: output too short and execution too fast — no bug evidence")
        return False

    # Otherwise ask the AI to evaluate the output.
    prompts_dir = Path(__file__).parent / "prompts"
    template = load_prompt_template("script_audit_prompt", prompts_dir)

    # Extract a hint about what the bug looks like from the root cause.
    root_cause = triage.root_cause_summary[:500] if triage.root_cause_summary else "See triage report."
    # Derive expected error from triage rather than hardcoding Octavia-specific types.
    expected_error = (
        f"Any error, exception, or unexpected failure related to: {triage.bug_title}. "
        f"Root cause: {root_cause[:200]}"
    )

    agent_reasoning_section = (
        f"\n## Agent's Stated Approach\n\n{reasoning}\n"
        if reasoning
        else ""
    )

    prompt = template.format(
        bug_number=triage.bug_number,
        bug_title=triage.bug_title,
        root_cause=root_cause,
        expected_error=expected_error,
        agent_reasoning=agent_reasoning_section,
        script=script[:3000],
        exit_code=result.exit_code,
        execution_time=result.execution_time,
        timeout_exceeded=result.timeout_exceeded,
        stdout=result.stdout[-3000:],
        stderr=result.stderr[-1000:],
    )

    try:
        _client = create_model_client(config)
        _res = await _client.query(prompt=prompt)
        first_line = _res.text.strip().splitlines()[0].strip().upper()
        confirmed = first_line.startswith("YES")
        verdict = "confirmed" if confirmed else "not confirmed"
        print(f"   🔍 Audit: bug reproduction {verdict} — {_res.text.strip()[:120]}")
        return confirmed
    except Exception as exc:
        # If the audit itself fails, err on the side of caution.
        print(f"   ⚠️ Audit failed ({exc}), treating exit-0 as unconfirmed")
        return False


def extract_script_from_response(response: str) -> str:
    """
    Extract bash script from Claude's response.

    Handles markdown code blocks and plain text responses.

    Args:
        response: Response from Claude

    Returns:
        Extracted script content
    """
    # Try to find bash code block
    pattern = r'```bash\n(.*?)\n```'
    match = re.search(pattern, response, re.DOTALL)
    if match:
        return match.group(1)

    # Try to find any code block
    pattern = r'```\n(.*?)\n```'
    match = re.search(pattern, response, re.DOTALL)
    if match:
        content = match.group(1)
        # Check if it starts with shebang
        if content.strip().startswith('#!/bin/bash'):
            return content

    # If no code block found, check if the response itself is a script
    if response.strip().startswith('#!/bin/bash'):
        return response

    # Last resort: wrap the response in a basic template
    return wrap_script_with_safety(response)


def wrap_script_with_safety(script_content: str) -> str:
    """
    Wrap script content with safety headers and cleanup.

    Args:
        script_content: Core script logic

    Returns:
        Complete script with safety wrapper
    """
    template = """#!/bin/bash
set -euo pipefail

# Cleanup trap - always executes on exit
trap cleanup EXIT
function cleanup() {{
    echo "=== Cleanup ==="
    # Delete test resources
    openstack loadbalancer delete --cascade test-backup-lb 2>/dev/null || true
    openstack server delete test-server1 test-server2 2>/dev/null || true
}}

{content}
"""
    return template.format(content=script_content)


def generate_fallback_script(triage: TriageReport, config: Dict) -> str:
    """
    Generate a simple fallback script when AI generation fails.

    Args:
        triage: Parsed triage report
        config: Configuration dictionary

    Returns:
        Basic reproduction script
    """
    devstack_config = config.get("devstack", {})
    openrc_file = devstack_config.get("openrc_file", "/opt/stack/devstack/openrc")

    # Combine bash blocks from triage
    commands = "\n\n".join(triage.reproduction_steps)

    script = f"""#!/bin/bash
set -euo pipefail

echo "=== Bug {triage.bug_number} Reproduction ==="
echo "Title: {triage.bug_title}"
echo ""

# Cleanup trap
trap cleanup EXIT
function cleanup() {{
    echo "=== Cleanup ==="
    # Cleanup will vary by bug - add specific cleanup here
}}

# Source OpenStack credentials
source {openrc_file}

# Reproduction commands from triage
{commands}

echo "=== Reproduction Complete ==="
"""
    return script


if __name__ == "__main__":
    # Test script extraction
    print("Testing script extraction...")

    # Test 1: Extract from code block
    test_response_1 = """Here's the script:

```bash
#!/bin/bash
echo "Test script"
exit 0
```

That should work!
"""
    script = extract_script_from_response(test_response_1)
    assert script.strip().startswith("#!/bin/bash")
    print("✓ Test 1: Code block extraction works")

    # Test 2: Plain script
    test_response_2 = """#!/bin/bash
echo "Direct script"
exit 0
"""
    script = extract_script_from_response(test_response_2)
    assert script.strip().startswith("#!/bin/bash")
    print("✓ Test 2: Direct script extraction works")

    # Test 3: Safety wrapper
    wrapped = wrap_script_with_safety("echo 'test'\nexit 0")
    assert "#!/bin/bash" in wrapped
    assert "set -euo pipefail" in wrapped
    assert "trap cleanup EXIT" in wrapped
    print("✓ Test 3: Safety wrapper works")

    print("\n✅ All tests passed!")
