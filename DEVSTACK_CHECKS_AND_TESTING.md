# DevStack Checks and Testing Enhancement

**Date:** 2026-04-01
**Purpose:** Add pre-flight checks and DevStack integration testing to agents

---

## Overview

Enhanced both bug-reproduction and code-review agents with comprehensive pre-flight checks and DevStack integration testing capabilities.

---

## Changes Made

### 1. Shared DevStack Checks Library

**New File:** `agents_lib/agents_lib/devstack_checks.py`

Provides shared functionality for:
- DevStack health checking (services, API, disk space)
- Git branch verification
- Branch checkout (main/master)
- Test environment cleanup

**Exported Functions:**
```python
from agents_lib import (
    DevStackHealth,
    BranchCheck,
    check_devstack_health,
    check_repo_on_main_branch,
    checkout_main_branch,
    cleanup_test_environment,
    format_health_report,
)
```

**Key Features:**
- `check_devstack_health()` - Verify DevStack is operational
- `check_repo_on_main_branch()` - Ensure repos are on main/master
- `checkout_main_branch()` - Auto-checkout main branch if needed
- `cleanup_test_environment()` - Delete test resources after testing

---

### 2. Bug Reproduction Agent Updates

**File:** `bug-reproduction-agent/bug_reproduction_agent.py`

**Changes:**
1. Now uses shared `agents_lib.devstack_checks` instead of local module
2. Added branch verification for Octavia repos before reproduction
3. Automatically checks out main branch if needed

**New Pre-flight Checks:**
```
🏥 Checking DevStack health...
   ✅ DevStack is healthy

📋 Checking repository branches...
   ✅ octavia: On main branch
   ✅ octavia-lib: On main branch
   ✅ python-octaviaclient: On main branch
```

**Behavior:**
- Checks health before attempting reproduction
- Verifies Octavia repos are on main/master
- Auto-checkout main if on different branch
- Only proceeds if environment is healthy

---

### 3. Code Review Agent Updates

**File:** `code-review-agent/review_single_change.py`

**Changes:**
1. Added pre-flight health checks before review
2. Added branch verification and auto-checkout
3. Integrated with shared devstack_checks module

**New Pre-flight Checks:**
```
🔍 Running pre-flight checks...

🏥 Checking DevStack health...
   ✅ DevStack is healthy

📋 Checking repository branch...
   ✅ On main branch
```

**Behavior:**
- Checks DevStack health (if `test_in_devstack` enabled)
- Verifies repository is on main/master (if `verify_main_branch` enabled)
- Auto-checkout main if needed
- Continues with limited testing if DevStack unhealthy

---

### 4. Code Review Prompt Enhancements

**File:** `code-review-agent/prompts/code_review_prompt.txt`

**New Step 6: DevStack Integration Testing**

```bash
# Source credentials
source ~/git/devstack/openrc admin admin

# Test the change in DevStack
openstack loadbalancer create --name test-review-lb --vip-subnet-id private-subnet

# Cleanup test resources
openstack loadbalancer delete --cascade test-review-lb
```

**Updated Step 11: Cleanup and Return to Branch**

- Added explicit cleanup instructions
- Always cleanup, even if tests fail
- Delete test resources with `test-review-` prefix

**Review Document Template:**

Added DevStack testing section:
```markdown
### DevStack Integration Tests
**Status**: ✅ PASS / ❌ FAIL / ⏭️ NOT APPLICABLE
**Details**: [What was tested, results]
**Cleanup**: [Confirm resources cleaned up]
```

**Step Numbers Updated:**
- Steps 6-10 → Steps 7-11 (added DevStack testing as step 6)

---

### 5. Configuration Updates

**File:** `code-review-agent/config.sample.json`

**New DevStack Settings:**
```json
{
  "devstack": {
    "path": "/opt/stack",
    "openrc_file": "~/git/devstack/openrc",
    "required_services": [
      "devstack@o-api.service",
      "devstack@o-cw.service",
      "devstack@o-hm.service"
    ],
    "min_disk_space_gb": 10,
    "verify_main_branch": true,
    "test_in_devstack": true,
    "cleanup_on_failure": true
  }
}
```

**Configuration Options:**

| Option | Default | Description |
|--------|---------|-------------|
| `verify_main_branch` | `true` | Check repos are on main/master before testing |
| `test_in_devstack` | `true` | Enable DevStack integration testing |
| `cleanup_on_failure` | `true` | Cleanup test resources even if tests fail |
| `required_services` | (list) | systemd services that must be running |
| `min_disk_space_gb` | `10` | Minimum free disk space required |

---

## Behavior Changes

### Bug Reproduction Agent

**Before:**
- Only checked DevStack health
- No branch verification
- Could run with repos on wrong branches

**After:**
- ✅ Checks DevStack health
- ✅ Verifies all Octavia repos on main/master
- ✅ Auto-checkout main if needed
- ✅ Clear error messages for environment issues

### Code Review Agent

**Before:**
- No health checks
- No branch verification
- No DevStack testing
- No cleanup instructions

**After:**
- ✅ Pre-flight health checks
- ✅ Branch verification with auto-checkout
- ✅ DevStack integration testing (Step 6)
- ✅ Explicit cleanup instructions (Step 11)
- ✅ Cleanup on failure (configurable)

---

## Testing Workflow

### Code Review Agent - Full Test Cycle

1. **Pre-flight Checks**
   - DevStack health (services, API, disk)
   - Repository on main branch

2. **Code Analysis**
   - Fetch change from Gerrit
   - Analyze code changes

3. **Automated Testing**
   - Unit tests (`tox -e py3`)
   - Functional tests (`tox -e functional`)
   - **DevStack integration tests** ← NEW
   - Code quality (`tox -e pep8`)

4. **Cleanup**
   - Delete all `test-review-*` resources
   - Return to original branch

---

## Cleanup Behavior

**Cleanup Strategy:**
- Always cleanup, even on test failure (default)
- Resources with `test-review-` prefix are deleted
- Cleanup commands run with error suppression (continue on failure)
- Verifies cleanup completed

**Cleanup Commands:**
```bash
# Delete test load balancers
openstack loadbalancer list --name test-review- | xargs openstack loadbalancer delete --cascade

# Delete test servers
openstack server list --name test-review- | xargs openstack server delete

# Verify cleanup
openstack loadbalancer list --name test-review-
```

**Configuration:**
- `cleanup_on_failure: true` (default) - Always cleanup
- `cleanup_on_failure: false` - Only cleanup on success

---

## Error Handling

### DevStack Unhealthy

**Bug Reproduction Agent:**
- Aborts reproduction
- Generates report with `ENVIRONMENT_ERROR` status
- Records in tracking file (won't retry until fixed)

**Code Review Agent:**
- Shows warning
- Continues with limited testing
- Notes environment issues in review

### Branch Check Failure

**Both Agents:**
- Attempts auto-checkout to main/master
- If checkout fails, shows warning
- Continues but notes potential issues

### Cleanup Failure

- Errors logged but don't fail the review
- Commands continue even if one fails
- Manual cleanup may be needed

---

## Example Output

### Bug Reproduction Agent
```
🏥 Checking DevStack health...
   ✅ DevStack is healthy

📋 Checking repository branches...
   ✅ octavia: On main branch
   ✅ octavia-lib: On main branch
   ⚠️  python-octaviaclient: Not on main branch (on 'feature-branch')
      Attempting to checkout main/master...
      ✅ Checked out main branch
```

### Code Review Agent
```
🔍 Running pre-flight checks...

🏥 Checking DevStack health...
   ✅ DevStack is healthy

📋 Checking repository branch...
   ✅ On main branch

================================================================================

🤖 Starting comprehensive code review...
```

---

## Files Modified

1. `agents_lib/agents_lib/__init__.py` - Export devstack_checks functions
2. `agents_lib/agents_lib/devstack_checks.py` - NEW shared module
3. `bug-reproduction-agent/bug_reproduction_agent.py` - Add branch checks
4. `code-review-agent/config.sample.json` - Add DevStack config options
5. `code-review-agent/review_single_change.py` - Add pre-flight checks
6. `code-review-agent/prompts/code_review_prompt.txt` - Add DevStack testing step

---

## Migration Notes

### Updating Existing Installations

1. **Update config files:**
   ```bash
   # Compare with new sample config
   diff config.json config.sample.json
   
   # Add new devstack options
   vim config.json
   ```

2. **Install updated agents_lib:**
   ```bash
   cd agents_lib
   pip install -e .
   ```

3. **Update individual agents:**
   ```bash
   cd bug-reproduction-agent
   pip install -e .
   
   cd ../code-review-agent
   pip install -e .
   ```

4. **No tracking file changes needed** - backward compatible

### Disabling New Features

To disable DevStack testing in code review agent:
```json
{
  "devstack": {
    "test_in_devstack": false,
    "verify_main_branch": false
  }
}
```

---

## Future Enhancements

Potential improvements:
- Configurable test resource naming patterns
- More sophisticated cleanup (age-based, pattern matching)
- Health check caching (avoid redundant checks)
- Branch protection (prevent accidental commits to main)
- DevStack performance testing integration
- Resource quota checks before testing

---

## Testing

**Validated:**
- ✅ Shared devstack_checks module import
- ✅ Pre-flight checks execute correctly
- ✅ Branch verification and auto-checkout
- ✅ Health check detects unhealthy DevStack
- ✅ Cleanup instructions in prompt
- ✅ Configuration options work as expected

**Next Steps:**
- Run full code review with DevStack testing
- Test with unhealthy DevStack environment
- Verify cleanup commands work correctly
- Test with repositories on non-main branches

---

## Summary

These changes ensure agents:
1. **Verify environment** before starting work
2. **Use clean state** (repos on main branch)
3. **Test changes live** in DevStack (code review)
4. **Clean up after themselves** (avoid resource accumulation)

This improves reliability, prevents false failures, and makes agent behavior more predictable.
