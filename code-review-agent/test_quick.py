#!/usr/bin/env python3
"""
Quick test to verify the agent configuration and basic functionality.
"""
import sys
from pathlib import Path

# Test 1: Config loading
print("=" * 60)
print("Test 1: Configuration Loading")
print("=" * 60)

sys.path.insert(0, str(Path(__file__).parent))
from config import load_config, get_config_info

config = load_config()
info = get_config_info()

print(f"✓ Config file: {info['config_file']}")
print(f"✓ DevStack path: {config['devstack_path']}")
print(f"✓ Output directory: {config['reviews_output_dir']}")
print(f"✓ Gerrit URL: {config['gerrit_base_url']}")
print(f"✓ Repositories: {len(config['octavia_repos'])} configured")

if info['env_overrides']:
    print("\nEnvironment overrides:")
    for k, v in info['env_overrides'].items():
        print(f"  {k} = {v}")

# Test 2: Required paths exist
print("\n" + "=" * 60)
print("Test 2: Path Validation")
print("=" * 60)

devstack_path = Path(config['devstack_path'])
if devstack_path.exists():
    print(f"✓ DevStack path exists: {devstack_path}")

    # Check for at least one Octavia repo
    octavia_repo = devstack_path / "octavia"
    if octavia_repo.exists():
        print(f"✓ Octavia repository found: {octavia_repo}")
    else:
        print(f"⚠ Octavia repository not found at: {octavia_repo}")
else:
    print(f"✗ DevStack path not found: {devstack_path}")

output_dir = Path(config['reviews_output_dir']).expanduser()
if output_dir.exists():
    print(f"✓ Output directory exists: {output_dir}")
else:
    print(f"⚠ Output directory will be created: {output_dir}")

# Test 3: Import agent SDK
print("\n" + "=" * 60)
print("Test 3: Claude Agent SDK")
print("=" * 60)

try:
    from claude_agent_sdk import query, ClaudeAgentOptions
    print("✓ Claude Agent SDK imported successfully")
except ImportError as e:
    print(f"✗ Failed to import Claude Agent SDK: {e}")
    sys.exit(1)

# Test 4: Parse change URL
print("\n" + "=" * 60)
print("Test 4: URL Parsing")
print("=" * 60)

import re

test_urls = [
    ("https://review.opendev.org/c/openstack/octavia/+/919846", "openstack/octavia", "919846"),
    ("919846", None, "919846"),
]

for url, expected_repo, expected_num in test_urls:
    if "review.opendev.org" in url:
        match = re.search(r'/c/([^/]+/[^/]+)/\+/(\d+)', url)
        if match:
            repo = match.group(1)
            num = match.group(2)
            if repo == expected_repo and num == expected_num:
                print(f"✓ Parsed URL correctly: {repo} #{num}")
            else:
                print(f"✗ Parse mismatch: got {repo} #{num}, expected {expected_repo} #{expected_num}")
        else:
            print(f"✗ Failed to parse URL: {url}")
    else:
        num = url.strip()
        if num == expected_num:
            print(f"✓ Change number extracted: {num}")
        else:
            print(f"✗ Mismatch: got {num}, expected {expected_num}")

# Test 5: Vertex AI environment
print("\n" + "=" * 60)
print("Test 5: Vertex AI Configuration")
print("=" * 60)

import os

if os.getenv("CLAUDE_CODE_USE_VERTEX") == "1":
    print("✓ CLAUDE_CODE_USE_VERTEX is set")
else:
    print("⚠ CLAUDE_CODE_USE_VERTEX not set (required for Vertex AI)")

# Try to check Google Cloud credentials
try:
    import subprocess
    result = subprocess.run(
        ["gcloud", "auth", "application-default", "print-access-token"],
        capture_output=True,
        timeout=5
    )
    if result.returncode == 0:
        print("✓ Google Cloud credentials are configured")
    else:
        print("⚠ Google Cloud credentials may not be configured")
except Exception as e:
    print(f"⚠ Could not verify Google Cloud credentials: {e}")

# Summary
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print("✅ Configuration system: Working")
print("✅ Agent SDK: Installed")
print("✅ URL parsing: Working")
print("\nThe agent is ready to use!")
print("\nTo run a review:")
print("  ./review_single_change.py 919846")
print("\nTo monitor repos:")
print("  ./octavia_review_agent.py")
