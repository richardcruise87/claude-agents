#!/usr/bin/env python3
"""
Review a specific Octavia change from OpenDev.

Usage:
    python review_single_change.py <change_number> [patchset]
    python review_single_change.py 912345
    python review_single_change.py 912345 2
    python review_single_change.py https://review.opendev.org/c/openstack/octavia/+/912345
    python review_single_change.py https://review.opendev.org/c/openstack/octavia/+/912345 3
"""
import asyncio
import sys
import re
import argparse
from datetime import datetime
from pathlib import Path
from claude_agent_sdk import query, ClaudeAgentOptions

# Add current directory to path to import config
sys.path.insert(0, str(Path(__file__).parent))
from config import load_config
from patchset_tracker import (
    prepare_review_context,
    create_review_filename,
    extract_patchset_from_review
)

# Load configuration
CONFIG = load_config()
DEVSTACK_PATH = CONFIG["devstack_path"]
REVIEWS_OUTPUT_DIR = CONFIG["reviews_output_dir"]
GERRIT_BASE_URL = CONFIG["gerrit_base_url"]


async def review_specific_change(change_url_or_number, requested_patchset=None):
    """
    Review a specific change by URL or change number.

    Args:
        change_url_or_number: Change number or Gerrit URL
        requested_patchset: Optional specific patchset number to review (e.g., 2)
                          If None, reviews the latest patchset
    """

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

    # Fetch patchset number from Gerrit
    if requested_patchset:
        print(f"🔍 Fetching patchset {requested_patchset} information from Gerrit...")
        current_patchset = requested_patchset
        # Construct the ref for the specific patchset
        # Format: refs/changes/NN/NNNN/P where last NN are last 2 digits of change
        last_two = str(change_number)[-2:]
        patchset_ref = f"refs/changes/{last_two}/{change_number}/{requested_patchset}"
        print(f"✓ Patchset: {current_patchset} (requested)")
        print(f"✓ Ref: {patchset_ref}")
    else:
        print("🔍 Fetching latest patchset information from Gerrit...")
        current_patchset = None
        patchset_ref = None

        async for message in query(
            prompt=f"""
            Fetch the change details from Gerrit API:
            {GERRIT_BASE_URL}/changes/{change_number}?o=CURRENT_REVISION&o=ALL_REVISIONS

            Extract:
            1. The current revision number (latest patchset number)
            2. The git ref for fetching (refs/changes/.../...)
            3. All available patchset numbers

            Return as JSON with keys: patchset_number, ref, all_patchsets
            Note: Gerrit prepends ")]]}}'" to JSON - strip it.
            The patchset number is under revisions -> _number field.
            """,
            options=ClaudeAgentOptions(allowed_tools=["WebFetch"]),
        ):
            if hasattr(message, 'result'):
                # Try to parse the patchset info
                result_text = message.result.strip()
                try:
                    # Simple extraction - look for numbers
                    import json
                    # Try to extract JSON from result
                    if 'patchset_number' in result_text:
                        data = json.loads(result_text)
                        current_patchset = data.get('patchset_number')
                        patchset_ref = data.get('ref')
                    else:
                        # Try to find patchset number in text
                        match = re.search(r'"_number":\s*(\d+)', result_text)
                        if match:
                            current_patchset = int(match.group(1))
                        # Try to find ref
                        match = re.search(r'"ref":\s*"([^"]+)"', result_text)
                        if match:
                            patchset_ref = match.group(1)
                except:
                    pass

                if current_patchset:
                    print(f"✓ Patchset: {current_patchset} (latest)")
                if patchset_ref:
                    print(f"✓ Ref: {patchset_ref}")

    # Check for previous reviews and prepare context
    previous_review_content, previous_patchset, old_review_file = prepare_review_context(
        output_dir, repo_name, change_number, current_patchset
    )

    # Create the new review filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    review_file = create_review_filename(
        output_dir, repo_name, change_number, current_patchset, timestamp
    )

    print(f"📄 Review will be saved to: {review_file.name}\n")

    repo_path = Path(DEVSTACK_PATH) / repo_name.split('/')[-1]

    if not repo_path.exists():
        print(f"❌ Repository not found at: {repo_path}")
        print(f"   Please ensure DevStack is set up correctly.")
        return

    # Build the prompt with previous review context if available
    previous_review_section = ""
    if previous_review_content and previous_patchset:
        previous_review_section = f"""

## IMPORTANT: Previous Review Context

This change has been reviewed before. You previously reviewed **Patchset {previous_patchset}**.

**Previous Review Summary** (for context):
```
{previous_review_content[:3000]}
... (truncated for brevity)
```

**Your Task for This Review:**
- Focus on what changed between PS {previous_patchset} and PS {current_patchset or 'current'}
- Note if previous issues were addressed
- Identify new issues introduced in this patchset
- Comment on whether the change is moving in the right direction
- Include a "Changes Since Previous Review" section

"""
    elif previous_review_content:
        previous_review_section = f"""

## IMPORTANT: Previous Review Context

This change has been reviewed before.

**Previous Review Summary** (for context):
```
{previous_review_content[:3000]}
... (truncated for brevity)
```

**Your Task for This Review:**
- Note if previous issues were addressed
- Identify any new issues
- Include a "Changes Since Previous Review" section if you can determine what changed

"""

    # Add note if reviewing a specific (potentially not latest) patchset
    specific_patchset_note = ""
    if requested_patchset:
        specific_patchset_note = f"\n**NOTE**: You are reviewing a SPECIFIC patchset (PS {requested_patchset}), which may not be the latest version of this change.\n"

    prompt = f"""
You are performing a comprehensive code review for an OpenStack Octavia change.

**Change Information:**
- Repository: {repo_name}
- Change Number: {change_number}
- Patchset: {current_patchset or 'unknown'}
- Gerrit URL: {GERRIT_BASE_URL}/c/{repo_name}/+/{change_number}
- Local repo: {repo_path}
{specific_patchset_note}{previous_review_section}
**Your Task:**
Perform a complete code review following these steps:

## Step 1: Get Current Branch
Save the current branch name so we can return to it later.

## Step 2: Fetch the Change
Fetch the specific patchset from Gerrit:
```bash
cd {repo_path}
{"git fetch " + GERRIT_BASE_URL + "/" + repo_name + " " + patchset_ref if patchset_ref else "git fetch " + GERRIT_BASE_URL + "/" + repo_name + " refs/changes/*/" + change_number + "/*"}
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
{"" if not previous_patchset else f'''
## Step 3a: Compare with Previous Patchset (PS {previous_patchset})

**IMPORTANT**: You have context from a previous review of Patchset {previous_patchset}.

Compare the current patchset with your previous review:
- Check if issues you identified in PS {previous_patchset} were addressed
- Identify what changed between patchsets (new files, modifications, deletions)
- Note if the change is improving or regressing
- Be specific about what was fixed and what wasn't

Reference the previous review context provided at the beginning of these instructions.
'''}
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
**Patchset**: {current_patchset or 'unknown'}
**Reviewed**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Reviewer**: Claude Code Review Agent (Vertex AI)
{"**Previous Review**: Patchset " + str(previous_patchset) if previous_patchset else "**First Review**"}

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
{"" if not previous_patchset else f'''
## Changes Since Previous Review (PS {previous_patchset})

### Issues Addressed
[List issues from previous review that were fixed in this patchset]
- ✅ Issue 1: Description of what was fixed
- ✅ Issue 2: Description of what was fixed
- ⚠️ Issue 3: Partially addressed or still present

### New Changes in This Patchset
[What was added/modified/removed in this patchset compared to PS {previous_patchset}]
- New file: path/to/file.py
- Modified: path/to/another.py (what changed)
- Removed: old/file.py

### New Issues Introduced
[Any new problems that appeared in this patchset]
- Issue 1: Description
- Issue 2: Description

### Overall Progress
[Assessment of whether the change is improving or regressing]

---
'''}
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
    parser = argparse.ArgumentParser(
        description='Review an OpenStack Octavia change from OpenDev',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Review latest patchset
  %(prog)s 919846

  # Review specific patchset
  %(prog)s 919846 2
  %(prog)s 919846 --patchset 3

  # Review using URL
  %(prog)s https://review.opendev.org/c/openstack/octavia/+/919846

  # Review specific patchset using URL
  %(prog)s https://review.opendev.org/c/openstack/octavia/+/919846 2
        """
    )

    parser.add_argument(
        'change',
        help='Change number or Gerrit URL (e.g., 919846 or https://review.opendev.org/c/openstack/octavia/+/919846)'
    )

    parser.add_argument(
        'patchset',
        nargs='?',
        type=int,
        default=None,
        help='Specific patchset number to review (e.g., 2). If omitted, reviews the latest patchset.'
    )

    parser.add_argument(
        '--patchset', '-p',
        dest='patchset_flag',
        type=int,
        help='Alternative way to specify patchset number'
    )

    args = parser.parse_args()

    # Determine which patchset to use (positional arg takes precedence)
    patchset = args.patchset if args.patchset else args.patchset_flag

    if patchset:
        print(f"📌 Reviewing patchset {patchset}\n")

    asyncio.run(review_specific_change(args.change, patchset))


if __name__ == "__main__":
    main()
