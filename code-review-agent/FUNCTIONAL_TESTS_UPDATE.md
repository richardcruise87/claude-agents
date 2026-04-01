# Functional Tests Update

**Date:** 2026-04-01
**Purpose:** Enable functional test execution in code review agent

---

## Problem

The code review agent was skipping functional tests with the assumption that they required a DevStack setup. However, the functional tests can run without DevStack.

---

## Changes Made

### File: `prompts/code_review_prompt.txt`

#### 1. Step 5: Run Functional Tests (Lines 56-67)

**Before:**
```
## Step 5: Run Functional Tests (if applicable)
Try to run functional tests:
```bash
tox -e functional
```
If not available, document that functional tests were skipped.
```

**After:**
```
## Step 5: Run Functional Tests
Run functional tests using tox:
```bash
cd {repo_path}
tox -e functional
```

**IMPORTANT:** The functional tests will run without a DevStack setup. Run them and capture the results.
- If the tox environment doesn't exist, check `tox.ini` for the correct environment name
- Common environment names: `functional`, `func`, `api`
- If tox fails to find the environment, document that functional tests are not available for this repository
- Capture all output, failures, and warnings
```

**Changes:**
- Removed "(if applicable)" from title - functional tests should be attempted
- Changed from "Try to run" to "Run functional tests" - more assertive
- Added explicit note that functional tests will run without DevStack
- Added guidance for finding the correct tox environment name
- Changed from "skipped" to "not available" for repositories without functional tests

#### 2. Functional Tests Results Template (Line 201-206)

**Before:**
```
### Functional Tests
```
[Full test output or summary]
```
**Status**: ✅ PASS / ❌ FAIL / ⏭️ SKIPPED
**Details**: [Results or reason for skipping]
```

**After:**
```
### Functional Tests
```
[Full test output or summary]
```
**Status**: ✅ PASS / ❌ FAIL / ⚠️ NOT AVAILABLE
**Details**: [Test results, failures, or note if repository doesn't have functional tests]
```

**Changes:**
- Changed "⏭️ SKIPPED" to "⚠️ NOT AVAILABLE"
- Changed details from "reason for skipping" to "note if repository doesn't have functional tests"
- This discourages skipping tests unnecessarily

---

## Impact

### Before
- Functional tests were routinely skipped
- Reviews lacked functional test coverage information
- Agent assumed DevStack was required

### After
- Functional tests will be executed on every review
- Reviews will include functional test results
- Only truly unavailable tests will be marked as such

---

## Verification

Octavia repository has functional tests:
```bash
$ grep -A 3 "\[testenv:functional\]" /opt/stack/octavia/tox.ini
[testenv:functional]
setenv = OS_TEST_PATH={toxinidir}/octavia/tests/functional
         PYTHONWARNINGS=always::DeprecationWarning
```

Test directory structure:
```
/opt/stack/octavia/octavia/tests/functional/
├── amphorae/
├── api/
├── db/
└── __init__.py
```

These tests run without requiring a DevStack deployment.

---

## Next Review Cycle

The next code review will:
1. ✅ Run unit tests (`tox -e py3`)
2. ✅ **Run functional tests (`tox -e functional`)** ← Now enabled
3. ✅ Run code quality checks (`tox -e pep8`)

All three test suites will be executed and results included in review documents.

---

## Notes

- If a repository genuinely doesn't have functional tests, the agent will note this but won't treat it as an error
- Some repositories may use different environment names (`func`, `api`, etc.) - the agent is instructed to check `tox.ini`
- Test failures will be captured and included in the review for analysis
