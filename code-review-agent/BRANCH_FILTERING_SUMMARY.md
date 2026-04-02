# Branch Filtering Feature - Quick Summary

**Date:** 2026-04-02
**Status:** ✅ Complete and Tested

## What Was Added

Branch filtering capability for the code review agent with include/exclude lists and wildcard support.

## Quick Start

### Default Configuration (Recommended)

Only review changes on `master` and `main` branches:

```json
{
  "filters": {
    "exclude_branches": [],
    "include_branches": ["master", "main"]
  }
}
```

This is now the **default configuration** in `config.sample.json`.

### Common Configurations

**1. Review all branches except stable:**
```json
{
  "filters": {
    "exclude_branches": ["stable/*"],
    "include_branches": []
  }
}
```

**2. Only review master (exclude everything else):**
```json
{
  "filters": {
    "exclude_branches": ["*"],
    "include_branches": ["master"]
  }
}
```

**3. Review master and all stable branches:**
```json
{
  "filters": {
    "exclude_branches": ["*"],
    "include_branches": ["master", "stable/*"]
  }
}
```

## How It Works

1. **Exclude list processed first** - Blocks branches matching patterns
2. **Include list processed second** - Overrides excludes for matching branches

This allows "exclude all except X" patterns.

## Wildcards

- `master` - Exact match only
- `stable/*` - Matches stable/2024.1, stable/wallaby, etc.
- `*` - Matches all branches
- `feature/*/test` - Matches feature/foo/test, etc.

## Testing Your Configuration

```bash
cd ~/git/claude-agents/code-review-agent
python3 test_branch_filter.py
```

**Expected output:**
```
Testing wildcard matching...
✓ All wildcard matching tests passed

Testing branch filtering logic...
✓ Test 1: No filters - all allowed
✓ Test 2: Exclude all, include master - only master allowed
...
✅ All tests passed!
```

## See It In Action

When running the code review agent, you'll see:

```
✓ Found 25 change(s)
📅 Cutoff date: 2026-03-03 (ignoring changes created before this date)
🌿 Branch filters: exclude=[], include=['master', 'main']
✓ Filtered to 3 reviewable change(s)
⏭️  Skipped 15 changes on excluded branches
⏭️  Skipped 5 changes created before cutoff date
⏭️  Skipped 2 already reviewed changes
```

The `🌿 Branch filters` line shows your active configuration.

## Example Workflow

### Scenario: Only Review Production Branches

**Goal:** Review only changes to master and stable branches, skip all feature work.

**Configuration:**
```json
{
  "filters": {
    "exclude_branches": ["*"],
    "include_branches": ["master", "main", "stable/*"]
  }
}
```

**Result:**
- ✅ master → Reviewed
- ✅ stable/2024.1 → Reviewed
- ✅ stable/wallaby → Reviewed
- ❌ feature/new-api → Skipped
- ❌ bugfix/issue-123 → Skipped

### Scenario: Skip Development Branches

**Goal:** Review everything except WIP and experimental branches.

**Configuration:**
```json
{
  "filters": {
    "exclude_branches": ["wip/*", "experimental/*", "tmp/*"],
    "include_branches": []
  }
}
```

**Result:**
- ✅ master → Reviewed
- ✅ feature/foo → Reviewed
- ✅ stable/2024.1 → Reviewed
- ❌ wip/test → Skipped
- ❌ experimental/new-feature → Skipped

## Files Modified

- `octavia_review_agent.py` - Core filtering logic
- `config.sample.json` - Default configuration
- `README.md` - Feature documentation link
- `BRANCH_FILTERING.md` - Comprehensive guide (15+ examples)
- `test_branch_filter.py` - Test suite (8 scenarios)

## Commit

**Commit:** `d55a0e7` - Add branch filtering to code review agent

```bash
# View the commit
git log -1 --stat d55a0e7

# Update to latest version
cd ~/git/claude-agents
./update-agents.sh
```

## Backward Compatibility

✅ **Fully backward compatible**

If you don't add branch filters to your `config.json`:
- Empty exclude list = No branches excluded
- Empty include list (when exclude is also empty) = All branches included
- Existing configurations continue to work unchanged

## Performance

Branch filtering is **fast and efficient**:
- Happens in memory after fetching from Gerrit
- Simple string pattern matching
- Applied before expensive review operations
- Reduces load by skipping unwanted branches early

## Documentation

- **Quick guide:** This file
- **Comprehensive guide:** [BRANCH_FILTERING.md](BRANCH_FILTERING.md)
- **Configuration examples:** [config.sample.json](config.sample.json)
- **Test suite:** [test_branch_filter.py](test_branch_filter.py)

## Next Steps

1. Update your `config.json` with desired branch filters
2. Test the configuration: `python3 test_branch_filter.py`
3. Run the agent and check the `🌿 Branch filters` output
4. Adjust filters based on which branches are being skipped

## Questions?

See the comprehensive guide [BRANCH_FILTERING.md](BRANCH_FILTERING.md) which includes:
- Detailed explanation of processing logic
- 6 complete example configurations
- Common use cases (production, development, release management)
- Debugging tips
- Best practices

---

*Feature completed: 2026-04-02*
