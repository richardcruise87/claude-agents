"""
Script generation and refinement functionality.

Generates reproduction scripts from triage reports and refines them using AI
after failures.
"""
from pathlib import Path
from typing import Dict
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
    return script, usage_dict


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
    return script, usage_dict


def extract_script_from_response(response: str) -> str:
    """
    Extract bash script from Claude's response.

    Handles markdown code blocks and plain text responses.

    Args:
        response: Response from Claude

    Returns:
        Extracted script content
    """
    import re

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
