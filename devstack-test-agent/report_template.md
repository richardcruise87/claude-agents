# DevStack Integration Testing

## Summary

### Change Info

- **Repository:** {REPO_NAME}
- **Change:** #{CHANGE_NUMBER}
- **Patchset:** PS{PATCHSET}
- **Gerrit URL:** {GERRIT_URL}
- **Test Date:** {TIMESTAMP}
- **Change Title:** [Run `git log --oneline -1` and insert the commit subject here]

### Overview

[Write 3-5 sentences: what this change does, which files or components are affected,
and the purpose of the change. Use `git show --stat` and the commit message to inform
this section.]

### Test Results

**Overall Status:** [Write exactly one of: ✅ PASS / ❌ FAIL / ⚠️ PARTIAL]

| Test Name | Description | Result |
|-----------|-------------|--------|
| [test name] | [one-line description of what it tests] | [✅ PASS / ❌ FAIL / ⚠️ PARTIAL] |

[Add one row per test performed. Use ✅ PASS, ❌ FAIL, or ⚠️ PARTIAL in the Result column.]

### Usage & Cost

- **Model:** {MODEL_NAME}
- **Total Tokens:** [Insert total input + output token count from the run]
- **Cached Tokens:** [Insert cached token count, or omit this line if zero]
- **Estimated Cost:** [Insert cost in USD, e.g. $0.12]

## Tests Performed

### Test 1: [Test Name]

#### Summary

[2-3 sentences: what aspect of the change this test validates and what the expected
outcome is.]

#### Procedure

[Numbered list of the exact steps taken, including the commands used:]

1. [Step with command, e.g. `openstack loadbalancer create --name {RESOURCE_PREFIX}lb ...`]
2. [Next step]
3. [Continue for all steps in this test]

#### Results

[Key output, error messages, or observations. Use a code block for terminal output:]

```
[paste relevant terminal output here]
```

[Brief narrative explaining what the output shows and whether it matched expectations.]

#### Verdict

[1-2 sentences: was the expected result achieved? Note any discrepancies.]

**Result:** [Write exactly one of: ✅ PASS / ❌ FAIL / ⚠️ PARTIAL]

### Test 2: [Test Name]

[Repeat the Test 1 structure — Summary, Procedure, Results, Verdict — for each
additional test performed. Number tests sequentially.]

## Test Results Summary

**Overall Status:** [Copy from Summary section above — must match exactly]
**Tests Passed:** [X/Y, e.g. 7/7]
**Tests Failed:** [count, e.g. 0]

**Key Findings:**
- [Most important finding from testing]
- [Additional finding — add as many bullets as needed]

**Issues Found:**
- [Describe any bugs, errors, or unexpected behaviours observed. Write "None" if
  all tests passed cleanly.]

**Recommendations:**
- [Suggestions for the change author, or "None" if no issues were found.]

## Cleanup Verification

[Show output confirming all test resources with the prefix {RESOURCE_PREFIX} were
deleted. Run `openstack loadbalancer list` and similar commands to verify.]

**Cleanup Status:** [Write exactly one of: ✅ Complete / ⚠️ Partial / ❌ Failed]

## Service Status After Testing

[Show the output of `systemctl is-active devstack@o-api devstack@o-cw devstack@o-hm`
run after testing completed.]

**Services:** [Write exactly one of: ✅ All Active / ⚠️ Some Issues / ❌ Critical Failure]

---

END OF REPORT
