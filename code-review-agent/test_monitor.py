#!/usr/bin/env python3
"""
Simple test for the monitoring agent
"""
import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

# Test import
try:
    from config import load_config
    print("✓ Config module imported")

    CONFIG = load_config()
    print(f"✓ Configuration loaded")
    print(f"  - Repos: {len(CONFIG['octavia_repos'])}")
    print(f"  - Output: {CONFIG['reviews_output_dir']}")
    print(f"  - DevStack: {CONFIG['devstack_path']}")

except Exception as e:
    print(f"✗ Error importing config: {e}")
    sys.exit(1)

# Test basic structure
try:
    print("\n✓ Basic imports successful")
    print("\nTo run the full monitoring agent:")
    print("  ./octavia_review_agent.py")
    print("\nNote: The monitoring agent makes API calls and can take time.")
    print("      It will review up to 3 changes per repository.")

except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)
