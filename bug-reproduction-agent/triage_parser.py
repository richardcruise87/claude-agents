"""
Triage report parsing functionality.

Parses markdown triage reports to extract bug metadata, reproduction steps,
and bash code blocks for script generation.
"""
import re
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class TriageReport:
    """Structured representation of a triage report."""
    bug_number: str
    bug_title: str
    severity: str
    validation_status: str
    reproduction_steps: List[str]  # Extracted bash commands
    prerequisites: str
    expected_behavior: str
    actual_behavior: str
    root_cause_summary: str
    triage_file: Path


def parse_triage_file(triage_path: Path) -> TriageReport:
    """
    Parse markdown triage report into structured data.

    Args:
        triage_path: Path to triage markdown file

    Returns:
        TriageReport object with extracted data

    Raises:
        FileNotFoundError: If triage file doesn't exist
        ValueError: If required fields are missing
    """
    if not triage_path.exists():
        raise FileNotFoundError(f"Triage file not found: {triage_path}")

    with open(triage_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract bug metadata from header
    metadata = extract_bug_metadata(content)

    # Extract reproduction steps from Step 7
    reproduction_steps = extract_bash_blocks(content, "Step 7: DevStack Reproduction Strategy")

    # Extract prerequisites
    prerequisites = extract_section_text(content, "### Prerequisites")

    # Extract root cause from Step 1
    root_cause = extract_section_text(content, "### Root Cause Analysis")

    # Extract expected/actual from Step 1
    expected = extract_section_text(content, "### Expected vs Actual Behavior")

    return TriageReport(
        bug_number=metadata.get("bug_number", ""),
        bug_title=metadata.get("bug_title", ""),
        severity=metadata.get("severity", "UNKNOWN"),
        validation_status=metadata.get("validation_status", ""),
        reproduction_steps=reproduction_steps,
        prerequisites=prerequisites,
        expected_behavior=expected,
        actual_behavior=expected,  # Same section contains both
        root_cause_summary=root_cause,
        triage_file=triage_path
    )


def extract_bug_metadata(markdown: str) -> Dict:
    """
    Extract bug metadata from triage report header.

    Args:
        markdown: Full markdown content

    Returns:
        Dictionary with bug_number, bug_title, severity, validation_status
    """
    metadata = {}

    # Extract bug number
    match = re.search(r'\*\*Bug ID:\*\*\s*(\d+)', markdown)
    if match:
        metadata["bug_number"] = match.group(1)

    # Extract bug title
    match = re.search(r'\*\*Title:\*\*\s*(.+)', markdown)
    if match:
        metadata["bug_title"] = match.group(1).strip()

    # Extract severity from Executive Summary
    match = re.search(r'\*\*Severity:\*\*\s*\*\*(\w+)\*\*', markdown)
    if match:
        metadata["severity"] = match.group(1)

    # Extract validation status
    match = re.search(r'\*\*Validation Status:\*\*\s*[✅❌⚠️]*\s*\*\*(.+?)\*\*', markdown)
    if match:
        metadata["validation_status"] = match.group(1).strip()

    return metadata


def extract_bash_blocks(markdown: str, section_name: str) -> List[str]:
    """
    Extract bash code blocks from a specific section.

    Args:
        markdown: Full markdown content
        section_name: Section header to search for (e.g., "Step 7: DevStack Reproduction Strategy")

    Returns:
        List of bash code block contents
    """
    bash_blocks = []

    # Find the section (look for ## followed by the section name)
    section_pattern = rf'##\s+{re.escape(section_name)}(.*?)(?=\n##\s+Step|\n##\s+[A-Z]|$)'
    section_match = re.search(section_pattern, markdown, re.DOTALL)

    if not section_match:
        return bash_blocks

    section_content = section_match.group(1)

    # Extract bash code blocks (```bash ... ``` or ```... ```)
    # Handle both ```bash and plain ``` blocks
    code_block_pattern = r'```(?:bash)?\n(.*?)\n```'
    for match in re.finditer(code_block_pattern, section_content, re.DOTALL):
        code = match.group(1).strip()
        if code and not code.startswith('#'):  # Skip if only comments
            bash_blocks.append(code)
        elif code:  # Include even if starts with comment
            bash_blocks.append(code)

    return bash_blocks


def extract_section_text(markdown: str, section_header: str) -> str:
    """
    Extract text from a specific section.

    Args:
        markdown: Full markdown content
        section_header: Section header (e.g., "### Prerequisites" or "Root Cause Analysis")

    Returns:
        Section text content (without code blocks)
    """
    # Try with ### header first
    section_pattern = rf'###\s+{re.escape(section_header)}(.*?)(?=\n###|\n##|$)'
    section_match = re.search(section_pattern, markdown, re.DOTALL)

    # If not found, try without the ### prefix (user might pass just the title)
    if not section_match:
        section_pattern = rf'###\s+.*?{re.escape(section_header)}(.*?)(?=\n###|\n##|$)'
        section_match = re.search(section_pattern, markdown, re.DOTALL)

    if not section_match:
        return ""

    section_content = section_match.group(1).strip()

    # Remove code blocks for cleaner text
    section_content = re.sub(r'```.*?```', '', section_content, flags=re.DOTALL)

    return section_content


def get_triage_timestamp(triage_path: Path) -> str:
    """
    Extract timestamp from triage filename.

    Format: bug_<number>_<title>_<YYYYMMDD_HHMMSS>_<seq>.md

    Args:
        triage_path: Path to triage file

    Returns:
        ISO timestamp string
    """
    filename = triage_path.stem
    parts = filename.split('_')

    # Find timestamp parts (format: YYYYMMDD_HHMMSS)
    for i, part in enumerate(parts):
        if len(part) == 8 and part.isdigit():  # YYYYMMDD
            if i + 1 < len(parts) and len(parts[i + 1]) == 6 and parts[i + 1].isdigit():  # HHMMSS
                date_str = part  # YYYYMMDD
                time_str = parts[i + 1]  # HHMMSS
                # Convert to ISO format: YYYY-MM-DDTHH:MM:SS
                iso_timestamp = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}T{time_str[:2]}:{time_str[2:4]}:{time_str[4:6]}"
                return iso_timestamp

    # Fallback: use file modification time
    import datetime
    mtime = triage_path.stat().st_mtime
    return datetime.datetime.fromtimestamp(mtime).isoformat()


if __name__ == "__main__":
    # Test the parsing functionality
    import sys

    if len(sys.argv) > 1:
        # Test with actual triage file
        triage_file = Path(sys.argv[1])
        if triage_file.exists():
            print(f"Parsing: {triage_file}")
            try:
                triage = parse_triage_file(triage_file)
                print(f"\n✓ Bug Number: {triage.bug_number}")
                print(f"✓ Bug Title: {triage.bug_title}")
                print(f"✓ Severity: {triage.severity}")
                print(f"✓ Validation: {triage.validation_status}")
                print(f"✓ Reproduction Steps: {len(triage.reproduction_steps)} bash blocks found")
                for i, step in enumerate(triage.reproduction_steps, 1):
                    lines = step.split('\n')
                    print(f"\n  Block {i} ({len(lines)} lines):")
                    print(f"  First line: {lines[0][:80]}...")
                print(f"\n✓ Prerequisites: {len(triage.prerequisites)} characters")
                print(f"✓ Root Cause: {len(triage.root_cause_summary)} characters")
                print("\n✅ Parsing successful!")
            except Exception as e:
                print(f"\n✗ Error: {e}")
                sys.exit(1)
        else:
            print(f"File not found: {triage_file}")
            sys.exit(1)
    else:
        print("Usage: python3 triage_parser.py <triage_file.md>")
        print("\nTest with sample content:")

        # Create test content
        test_content = """# Octavia Bug Triage Report

**Bug ID:** 12345
**Title:** Test bug
**Severity:** HIGH
**Validation Status:** ✅ **VALID BUG**

## Executive Summary

**Severity:** **HIGH**

## Step 1: Bug Analysis

### Root Cause Analysis
This is the root cause.

### Expected vs Actual Behavior
Expected: Works
Actual: Doesn't work

## Step 7: DevStack Reproduction Strategy

### Prerequisites

**DevStack Setup:**
```bash
# Ensure DevStack is running
cd /opt/stack/devstack
```

### Step-by-Step Reproduction

```bash
# Create load balancer
openstack loadbalancer create --name test-lb
```

```bash
# Create listener
openstack loadbalancer listener create test-listener
```
"""
        metadata = extract_bug_metadata(test_content)
        print(f"✓ Metadata: {metadata}")

        bash_blocks = extract_bash_blocks(test_content, "Step 7: DevStack Reproduction Strategy")
        print(f"✓ Bash blocks: {len(bash_blocks)} found")
        for i, block in enumerate(bash_blocks, 1):
            print(f"  Block {i}: {block[:50]}...")

        print("\n✅ Test parsing successful!")
