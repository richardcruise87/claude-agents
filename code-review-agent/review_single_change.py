#!/usr/bin/env python3
"""
Review a specific Octavia change from OpenDev.

Usage:
    python review_single_change.py <change_number>
    python review_single_change.py 912345
    python review_single_change.py https://review.opendev.org/c/openstack/octavia/+/912345
"""
import asyncio
import sys
import re
from datetime import datetime
from pathlib import Path
from claude_agent_sdk import query, ClaudeAgentOptions

# Add current directory to path to import config
sys.path.insert(0, str(Path(__file__).parent))
from config import load_config

# Load configuration
CONFIG = load_config()
DEVSTACK_PATH = CONFIG["devstack_path"]
REVIEWS_OUTPUT_DIR = CONFIG["reviews_output_dir"]
GERRIT_BASE_URL = CONFIG["gerrit_base_url"]


async def review_specific_change(change_url_or_number):
    """Review a specific change by URL or change number."""

    # Parse change number from URL or direct number
    if "review.opendev.org" in change_url_or_number:
        # Extract from URL like: https://review.opendev.org/c/openstack/octavia/+/912345
        match = re.search(r'/c/([^/]+/[^/]+)/\+/(\d+)', change_url_or_number)
        if not match:
            print(f"❌ Could not parse URL: {change_url_or_number}")
            return
        repo_name = match.group(1)
        change_number = match.group(2)
    else:
        # Assume it's just a change number - need to find which repo
        change_number = change_url_or_number.strip()
        print(f"🔍 Looking up change {change_number}...")

        # Fetch change details from Gerrit
        async for message in query(
            prompt=f"""
            Fetch the change details from Gerrit API:
            {GERRIT_BASE_URL}/changes/{change_number}

            Extract the project/repository name from the response.
            Return ONLY the repository name in format: openstack/project-name
            Note: Gerrit prepends ")]]}}'" to JSON - strip it.
            """,
            options=ClaudeAgentOptions(allowed_tools=["WebFetch"]),
        ):
            if hasattr(message, 'result'):
                # Extract repo name from result
                repo_name = None
                result_text = message.result.strip()

                # Try to find openstack/xxx pattern
                match = re.search(r'(openstack/[\w-]+)', result_text)
                if match:
                    repo_name = match.group(1)

                if not repo_name:
                    print(f"❌ Could not determine repository for change {change_number}")
                    print(f"Response: {message.result}")
                    return

    print(f"\n{'='*80}")
    print(f"📋 Change Details:")
    print(f"  Repository: {repo_name}")
    print(f"  Change Number: {change_number}")
    print(f"  URL: {GERRIT_BASE_URL}/c/{repo_name}/+/{change_number}")
    print(f"{'='*80}\n")

    # Create output directory
    output_dir = Path(REVIEWS_OUTPUT_DIR)
    output_dir.mkdir(exist_ok=True, parents=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    review_file = output_dir / f"review_{repo_name.replace('/', '_')}_{change_number}_{timestamp}.md"

    repo_path = Path(DEVSTACK_PATH) / repo_name.split('/')[-1]

    if not repo_path.exists():
        print(f"❌ Repository not found at: {repo_path}")
        print(f"   Please ensure DevStack is set up correctly.")
        return

    prompt = f"""
You are performing a comprehensive code review for an OpenStack Octavia change.

**Change Information:**
- Repository: {repo_name}
- Change Number: {change_number}
- Gerrit URL: {GERRIT_BASE_URL}/c/{repo_name}/+/{change_number}
- Local repo: {repo_path}

**Your Task:**
Perform a complete code review following these steps:

## Step 1: Get Current Branch
Save the current branch name so we can return to it later.

## Step 2: Fetch the Change
Fetch the specific patchset from Gerrit:
```bash
cd {repo_path}
git fetch {GERRIT_BASE_URL}/{repo_name} refs/changes/*/{change_number}/*
git checkout FETCH_HEAD
```

## Step 3: Analyze the Changes
- Run `git log -1 --pretty=full` to see the commit message
- Run `git show --stat` to see files changed
- Run `git diff HEAD~1` to see the actual changes
- Read the modified files to understand the changes deeply
- Identify:
  * Purpose of the change
  * Scope and impact
  * Any breaking changes
  * New features or bug fixes

## Step 4: Run Unit Tests
Execute unit tests and capture results:
```bash
cd {repo_path}
tox -e py3
```
If tox isn't available, try: `python -m pytest octavia/tests/unit` or similar.
Capture all output, failures, and warnings.

## Step 5: Run Functional Tests (if applicable)
Try to run functional tests:
```bash
tox -e functional
```
If not available, document that functional tests were skipped.

## Step 6: Code Quality Checks
Run linting/style checks:
```bash
tox -e pep8
```
or
```bash
flake8
```

## Step 7: Comprehensive Code Analysis
Analyze for:

### Code Quality
- **Style**: PEP 8 compliance, naming conventions, code organization
- **Readability**: Clear logic, appropriate comments, good variable names
- **Complexity**: Are functions too complex? Need refactoring?

### Correctness & Safety
- **Logic**: Are there logical errors or edge cases not handled?
- **Error Handling**: Proper exceptions, try/catch blocks, validation
- **Security**: Check for vulnerabilities (SQL injection, XSS, insecure defaults)
- **Concurrency**: Thread safety if applicable
- **Resource Management**: Proper cleanup, no memory leaks

### Testing
- **Test Coverage**: Are new/modified code paths tested?
- **Test Quality**: Are tests meaningful and not just for coverage?
- **Missing Tests**: What test scenarios are missing?

### Documentation
- **Docstrings**: Are they present and accurate?
- **Comments**: Explain complex logic?
- **Commit Message**: Clear, follows OpenStack format?
- **Release Notes**: Are they needed and included?

### OpenStack Specific
- **API Compatibility**: Breaking changes to APIs?
- **Database Migrations**: Are they needed and included?
- **Configuration**: New config options documented?
- **Deprecations**: Properly marked with warnings?

## Step 8: Prepare Testing Strategy
Document:
1. **Tests Executed**:
   - Unit tests results
   - Functional tests results
   - Linting results

2. **Recommended Additional Testing**:
   - Integration tests with other services
   - Upgrade/downgrade scenarios
   - Performance testing if relevant
   - Multi-node scenarios

3. **Manual Testing Steps**:
   - Step-by-step test procedures
   - Expected outcomes
   - Commands to verify

## Step 9: Generate Review Document
Create a comprehensive markdown review saved to: {review_file}

**Document Structure:**

```markdown
# Code Review: {repo_name} - Change #{change_number}

**Gerrit URL**: {GERRIT_BASE_URL}/c/{repo_name}/+/{change_number}
**Reviewed**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Reviewer**: Claude Code Review Agent (Vertex AI)

---

## Change Summary

[Brief description of what this change does]

**Files Modified**: [count]
**Lines Added**: [+count]
**Lines Removed**: [-count]

### Commit Message
```
[Full commit message]
```

### Purpose
[What problem does this solve? What feature does it add?]

### Scope
[What parts of the system are affected?]

---

## Test Results

### Unit Tests
```
[Full test output or summary]
```
**Status**: ✅ PASS / ❌ FAIL
**Details**: [Any failures, warnings, or notable output]

### Functional Tests
```
[Full test output or summary]
```
**Status**: ✅ PASS / ❌ FAIL / ⏭️ SKIPPED
**Details**: [Results or reason for skipping]

### Code Quality Checks (PEP8/Flake8)
```
[Linting output]
```
**Status**: ✅ PASS / ⚠️ WARNINGS / ❌ FAIL
**Issues**: [List any style violations]

---

## Code Analysis

### Overall Assessment
[High-level evaluation of code quality]

### Strengths
- [What's done well]
- [Good practices observed]
- [Positive aspects]

### Issues Found

#### Critical Issues 🔴
[Issues that MUST be fixed before merge]

1. **File**: `path/to/file.py:123`
   - **Issue**: [Description]
   - **Impact**: [Why this is critical]
   - **Suggestion**: [How to fix]

#### Major Issues 🟡
[Significant issues that should be addressed]

#### Minor Issues / Suggestions 🔵
[Nice-to-haves and minor improvements]

#### Nits 🟢
[Very minor style/formatting suggestions]

---

## Testing Strategy

### Tests Executed
1. ✅ Unit tests: `tox -e py3`
2. ✅ Functional tests: `tox -e functional`
3. ✅ Code style: `tox -e pep8`

### Recommended Additional Testing

1. **Integration Testing**:
   - [Specific scenarios to test]

2. **Performance Testing**:
   - [If relevant, what to measure]

3. **Upgrade Testing**:
   - [Test upgrade from previous version]

4. **Manual Testing**:
   ```bash
   # Step-by-step commands
   ```

### Test Coverage Gaps
- [Areas not covered by existing tests]
- [Suggested new test cases]

---

## Recommendations

### Required Changes (Must Fix) ⛔
1. [Critical issue that blocks merge]
2. [Another blocking issue]

### Suggested Improvements (Should Fix) ⚠️
1. [Improvement that would be good to address]
2. [Another suggestion]

### Questions for Author ❓
1. [Clarifying question about design choice]
2. [Question about edge case handling]

### Nice-to-Haves (Optional) 💡
1. [Enhancement for future consideration]

---

## Detailed Review Comments

### File: `octavia/path/to/file1.py`

**Line 45-52**:
- **Severity**: Major
- **Comment**: [Detailed explanation of issue]
- **Suggestion**:
  ```python
  # Proposed code improvement
  ```

**Line 78**:
- **Severity**: Minor
- **Comment**: [Minor suggestion]

### File: `octavia/path/to/file2.py`

[Additional file-specific comments]

---

## Security Analysis

[Any security considerations, vulnerabilities found, or security best practices]

---

## Performance Considerations

[Any performance impacts, optimizations suggested]

---

## Documentation Review

- **Docstrings**: ✅ Good / ⚠️ Needs Improvement / ❌ Missing
- **Code Comments**: ✅ Good / ⚠️ Needs Improvement / ❌ Missing
- **Commit Message**: ✅ Good / ⚠️ Needs Improvement / ❌ Missing
- **Release Notes**: ✅ Included / ⚠️ Needed / ⏭️ Not Applicable

---

## Final Verdict

**Overall Assessment**: [1-2 sentence summary]

**Recommendation**:
- ✅ **Approve** (Code is ready to merge)
- 🔄 **Request Changes** (Issues must be addressed)
- 💬 **Needs Discussion** (Architectural or design questions)
- 🔍 **Needs More Information** (Clarification needed)

**Confidence Level**: High / Medium / Low
[Explanation of confidence level]

---

## Next Steps

1. [Action item for author]
2. [Action item for reviewers]
3. [Any follow-up needed]

---

*Generated by Claude Code Review Agent*
*Powered by Vertex AI*
```

## Step 10: Return to Original Branch
Return to the original git branch:
```bash
cd {repo_path}
git checkout <original_branch>
```

**IMPORTANT**:
- Be thorough and professional
- Provide specific file:line references
- Give actionable suggestions with code examples
- Balance criticism with recognition of good work
- Consider OpenStack community standards
- DO NOT post to Gerrit - only save locally
"""

    print("🤖 Starting comprehensive code review...\n")

    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                allowed_tools=["Bash", "Read", "Write", "Grep", "Glob"],
            ),
        ):
            if hasattr(message, 'text'):
                print(f"  {message.text}")
            elif hasattr(message, 'result'):
                print(f"\n{'='*80}")
                print(f"✅ Review Complete!")
                print(f"{'='*80}")
                print(f"\n📄 Review Document: {review_file}")
                print(f"\nSummary:\n{message.result}")

    except Exception as e:
        print(f"\n❌ Error during review: {e}")
        import traceback
        traceback.print_exc()


def main():
    if len(sys.argv) < 2:
        print("Usage: python review_single_change.py <change_number_or_url>")
        print("\nExamples:")
        print("  python review_single_change.py 912345")
        print("  python review_single_change.py https://review.opendev.org/c/openstack/octavia/+/912345")
        sys.exit(1)

    change_input = sys.argv[1]
    asyncio.run(review_specific_change(change_input))


if __name__ == "__main__":
    main()
