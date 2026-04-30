"""
Script execution functionality.

Safely executes reproduction scripts with timeout, cleanup, and error categorization.
"""
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


@dataclass
class ExecutionResult:
    """Results from script execution."""
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    execution_time: float
    timeout_exceeded: bool
    error_type: str  # "SUCCESS", "SCRIPT_FAILURE", "TIMEOUT", "ENVIRONMENT_ERROR"


def execute_script(
    script_content: str,
    timeout: int = 600,
    working_dir: Optional[Path] = None
) -> ExecutionResult:
    """
    Execute bash script with timeout and capture output.

    Args:
        script_content: Complete bash script content
        timeout: Maximum execution time in seconds (default: 600 = 10 min)
        working_dir: Working directory for execution (default: /tmp)

    Returns:
        ExecutionResult with execution details and categorized error type
    """
    if working_dir is None:
        working_dir = Path("/tmp")

    # Create temporary script file
    with tempfile.NamedTemporaryFile(
        mode='w',
        suffix='.sh',
        delete=False,
        dir=working_dir
    ) as script_file:
        script_file.write(script_content)
        script_path = Path(script_file.name)

    try:
        # Make script executable
        script_path.chmod(0o755)

        # Execute script
        start_time = time.time()
        try:
            result = subprocess.run(
                ["/bin/bash", str(script_path)],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=working_dir,
                check=False
            )
            timeout_exceeded = False
        except subprocess.TimeoutExpired as e:
            # Timeout exceeded
            execution_time = time.time() - start_time
            return ExecutionResult(
                success=False,
                exit_code=-1,
                stdout=e.stdout.decode() if e.stdout else "",
                stderr=e.stderr.decode() if e.stderr else "",
                execution_time=execution_time,
                timeout_exceeded=True,
                error_type="TIMEOUT"
            )

        execution_time = time.time() - start_time

        # Categorize result
        if result.returncode == 0:
            error_type = "SUCCESS"
            success = True
        else:
            # Analyze output to categorize failure
            error_type = analyze_execution_output(result.stdout, result.stderr, result.returncode)
            success = False

        return ExecutionResult(
            success=success,
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            execution_time=execution_time,
            timeout_exceeded=timeout_exceeded,
            error_type=error_type
        )

    finally:
        # Cleanup temporary script file
        try:
            script_path.unlink()
        except FileNotFoundError:
            pass


def analyze_execution_output(stdout: str, stderr: str, exit_code: int) -> str:
    """
    Categorize failure type based on output.

    Args:
        stdout: Standard output
        stderr: Standard error
        exit_code: Exit code

    Returns:
        Error type: "SUCCESS", "SCRIPT_FAILURE", "ENVIRONMENT_ERROR", "BUG_REPRODUCED"
    """
    combined_output = (stdout + "\n" + stderr).lower()

    # Exit code 0 means success
    if exit_code == 0:
        return "SUCCESS"

    # Check for environment/DevStack errors
    environment_indicators = [
        "connection refused",
        "service unavailable",
        "no such service",
        "systemctl",
        "authentication failed",
        "unauthorized",
        "endpoint not found",
        "503 service unavailable",
        "could not resolve host",
        "network is unreachable"
    ]

    for indicator in environment_indicators:
        if indicator in combined_output:
            return "ENVIRONMENT_ERROR"

    # Check for script syntax errors
    script_error_indicators = [
        "syntax error",
        "command not found",
        "no such file or directory",
        "permission denied",
        "bad substitution"
    ]

    for indicator in script_error_indicators:
        if indicator in combined_output:
            return "SCRIPT_FAILURE"

    # Check if the bug was actually reproduced (test failed as expected)
    bug_reproduction_indicators = [
        "mismatcherror",
        "assertion",
        "expected",
        "test failed",
        "failure"
    ]

    bug_reproduction_count = sum(
        1 for indicator in bug_reproduction_indicators
        if indicator in combined_output
    )

    # If multiple bug indicators, likely the bug was reproduced
    if bug_reproduction_count >= 2:
        return "BUG_REPRODUCED"

    # Default to script failure
    return "SCRIPT_FAILURE"


def format_execution_report(result: ExecutionResult, attempt_number: int) -> str:
    """
    Format execution results as markdown.

    Args:
        result: ExecutionResult object
        attempt_number: Attempt number (1, 2, 3)

    Returns:
        Formatted markdown string
    """
    lines = [f"### Attempt {attempt_number}", ""]

    # Status
    if result.success or result.error_type == "BUG_REPRODUCED":
        lines.append("**Status:** ✅ SUCCESS - Bug Reproduced")
    elif result.error_type == "TIMEOUT":
        lines.append("**Status:** ⏱️ TIMEOUT")
    elif result.error_type == "ENVIRONMENT_ERROR":
        lines.append("**Status:** ⚠️ ENVIRONMENT ERROR")
    else:
        lines.append("**Status:** ❌ SCRIPT FAILURE")

    lines.append(f"**Exit Code:** {result.exit_code}")
    lines.append(f"**Execution Time:** {result.execution_time:.1f}s")
    lines.append(f"**Error Type:** {result.error_type}")
    lines.append("")

    # Stdout
    if result.stdout:
        lines.append("**Standard Output:**")
        lines.append("```")
        # Limit output length
        stdout_lines = result.stdout.split('\n')
        if len(stdout_lines) > 100:
            lines.extend(stdout_lines[:50])
            lines.append(f"... ({len(stdout_lines) - 100} lines omitted) ...")
            lines.extend(stdout_lines[-50:])
        else:
            lines.append(result.stdout)
        lines.append("```")
        lines.append("")

    # Stderr
    if result.stderr:
        lines.append("**Standard Error:**")
        lines.append("```")
        # Limit output length
        stderr_lines = result.stderr.split('\n')
        if len(stderr_lines) > 50:
            lines.extend(stderr_lines[:25])
            lines.append(f"... ({len(stderr_lines) - 50} lines omitted) ...")
            lines.extend(stderr_lines[-25:])
        else:
            lines.append(result.stderr)
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    # Test the script executor

    print("Testing script executor...")
    print("")

    # Test 1: Simple successful script
    print("Test 1: Simple successful script")
    test_script_1 = """#!/bin/bash
set -euo pipefail
echo "Hello from test script"
echo "Testing stdout"
exit 0
"""
    result = execute_script(test_script_1, timeout=10)
    print(f"  Exit code: {result.exit_code}")
    print(f"  Error type: {result.error_type}")
    print(f"  Success: {result.success}")
    assert result.success and result.error_type == "SUCCESS"
    print("  ✅ Passed")
    print("")

    # Test 2: Script that fails
    print("Test 2: Script that fails")
    test_script_2 = """#!/bin/bash
set -euo pipefail
echo "This will fail"
exit 1
"""
    result = execute_script(test_script_2, timeout=10)
    print(f"  Exit code: {result.exit_code}")
    print(f"  Error type: {result.error_type}")
    print(f"  Success: {result.success}")
    assert not result.success and result.exit_code == 1
    print("  ✅ Passed")
    print("")

    # Test 3: Script with timeout
    print("Test 3: Script with timeout")
    test_script_3 = """#!/bin/bash
echo "Starting long sleep"
sleep 100
echo "This won't print"
"""
    result = execute_script(test_script_3, timeout=2)
    print(f"  Timeout exceeded: {result.timeout_exceeded}")
    print(f"  Error type: {result.error_type}")
    assert result.timeout_exceeded and result.error_type == "TIMEOUT"
    print("  ✅ Passed")
    print("")

    print("✅ All tests passed!")
