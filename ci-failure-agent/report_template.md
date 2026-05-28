# CI Failure Analysis: {PROJECT} Change #{CHANGE_NUMBER} PS{PATCHSET}

**Generated:** {ANALYSIS_DATE}
**Agent:** OpenStack CI Failure Analysis Agent

## Summary

| Field | Value |
|-------|-------|
| Gerrit Change | [{PROJECT} #{CHANGE_NUMBER}]({GERRIT_URL}) |
| Patchset | {PATCHSET} |
| Pipeline | {PIPELINE} |
| Total Failing Jobs | {TOTAL_FAILURES} |
| Analysis Date | {ANALYSIS_DATE} |

## Failing Jobs Overview

| Job | Category | Voting | Brief Summary |
|-----|----------|--------|---------------|
[Add one row per failing job — fill in Category and Brief Summary based on your analysis]

## Detailed Analysis

[For each failing job, include a subsection following this structure:]

### <job_name>

- **Build URL:** <full build URL from the job details above>
- **Log URL:** <log URL from the job details above>
- **Duration:** <duration from the job details above>
- **Voting:** <Yes (blocks merge) | No (informational only)>

**Root Cause Analysis:**

<Detailed explanation of what went wrong. Be specific — quote error messages, test names,
line numbers where relevant. Reference the pre-fetched log excerpt provided in the prompt.>

**Key Log Evidence:**
```
<Paste 10–30 lines from the actual log that prove the diagnosis. This is required — do not skip.>
```

**Category:** CODE_ISSUE | ENVIRONMENTAL | UNRELATED | INFRA_FAILURE

**Recommendation:** <Specific action the author should take for this job>

---
[Repeat the above structure for each failing job]

## Overall Recommendation

**Action Required:** [Choose ONE: RE-RUN ONLY | CODE FIX REQUIRED | CODE FIX + RE-RUN | INVESTIGATE]

<2–4 sentences explaining the overall recommendation and its reasoning.>

### Jobs Requiring Code Fix

<List each job needing a code change, with a one-sentence description of what to fix.
Write "None." if no code fixes are needed.>

### Jobs That Can Be Re-Run

<List each job with ENVIRONMENTAL or INFRA_FAILURE category.
Write "None." if no re-runs are needed.>

## How to Act

**To re-run all failed jobs**, post this comment on the Gerrit change:

```
recheck
```

**Gerrit change:** {GERRIT_URL}

## Links

- **Gerrit Change:** {GERRIT_URL}
- **Zuul Build Search:** {ZUUL_BUILD_SEARCH_URL}

---

END OF REPORT
