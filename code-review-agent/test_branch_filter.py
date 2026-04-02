#!/usr/bin/env python3
"""Test branch filtering logic."""

import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))
from octavia_review_agent import matches_wildcard, should_review_branch


def test_matches_wildcard():
    """Test wildcard matching."""
    print("Testing wildcard matching...")

    # Exact matches
    assert matches_wildcard("master", "master") == True
    assert matches_wildcard("main", "main") == True
    assert matches_wildcard("master", "main") == False

    # Wildcard at end
    assert matches_wildcard("stable/2024.1", "stable/*") == True
    assert matches_wildcard("stable/2024.2", "stable/*") == True
    assert matches_wildcard("master", "stable/*") == False

    # Match all
    assert matches_wildcard("master", "*") == True
    assert matches_wildcard("feature/foo", "*") == True
    assert matches_wildcard("stable/2024.1", "*") == True

    # Wildcard in middle
    assert matches_wildcard("feature/foo/bar", "feature/*/bar") == True
    assert matches_wildcard("feature/baz/bar", "feature/*/bar") == True
    assert matches_wildcard("feature/foo/baz", "feature/*/bar") == False

    print("✓ All wildcard matching tests passed")


def test_should_review_branch():
    """Test branch filtering logic."""
    print("\nTesting branch filtering logic...")

    # Test 1: Default (no filters) - allow all
    assert should_review_branch("master", [], []) == True
    assert should_review_branch("feature/x", [], []) == True
    print("✓ Test 1: No filters - all allowed")

    # Test 2: Exclude all, include master
    assert should_review_branch("master", ["*"], ["master"]) == True
    assert should_review_branch("main", ["*"], ["master"]) == False
    assert should_review_branch("feature/x", ["*"], ["master"]) == False
    print("✓ Test 2: Exclude all, include master - only master allowed")

    # Test 3: Exclude all, include master and main
    assert should_review_branch("master", ["*"], ["master", "main"]) == True
    assert should_review_branch("main", ["*"], ["master", "main"]) == True
    assert should_review_branch("feature/x", ["*"], ["master", "main"]) == False
    print("✓ Test 3: Exclude all, include master+main - only master and main allowed")

    # Test 4: Exclude stable branches
    assert should_review_branch("stable/2024.1", ["stable/*"], []) == False
    assert should_review_branch("stable/2024.2", ["stable/*"], []) == False
    assert should_review_branch("master", ["stable/*"], []) == True
    assert should_review_branch("feature/x", ["stable/*"], []) == True
    print("✓ Test 4: Exclude stable/* - stable branches excluded")

    # Test 5: Include only master and main (typical config)
    assert should_review_branch("master", [], ["master", "main"]) == True
    assert should_review_branch("main", [], ["master", "main"]) == True
    assert should_review_branch("feature/x", [], ["master", "main"]) == False
    assert should_review_branch("stable/2024.1", [], ["master", "main"]) == False
    print("✓ Test 5: Include only master+main - only those allowed")

    # Test 6: Exclude stable, include all
    assert should_review_branch("master", ["stable/*"], ["*"]) == True
    assert should_review_branch("feature/x", ["stable/*"], ["*"]) == True
    assert should_review_branch("stable/2024.1", ["stable/*"], ["*"]) == True  # Include overrides exclude
    print("✓ Test 6: Exclude stable/*, include * - include overrides exclude")

    # Test 7: Exclude feature and bugfix, no includes
    assert should_review_branch("master", ["feature/*", "bugfix/*"], []) == True
    assert should_review_branch("feature/test", ["feature/*", "bugfix/*"], []) == False
    assert should_review_branch("bugfix/123", ["feature/*", "bugfix/*"], []) == False
    print("✓ Test 7: Exclude feature/* and bugfix/* - those excluded")

    # Test 8: Complex pattern - exclude all, include stable and master
    assert should_review_branch("master", ["*"], ["master", "stable/*"]) == True
    assert should_review_branch("stable/2024.1", ["*"], ["master", "stable/*"]) == True
    assert should_review_branch("feature/x", ["*"], ["master", "stable/*"]) == False
    print("✓ Test 8: Exclude all, include master+stable/* - only master and stable allowed")

    print("\n✅ All branch filtering tests passed!")


if __name__ == "__main__":
    test_matches_wildcard()
    test_should_review_branch()
    print("\n" + "="*60)
    print("✅ All tests passed!")
    print("="*60)
