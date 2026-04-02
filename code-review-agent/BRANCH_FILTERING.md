# Branch Filtering - Code Review Agent

The code review agent supports filtering changes by branch name using include and exclude lists with wildcard support.

## Configuration

Add branch filters to `config.json`:

```json
{
  "filters": {
    "exclude_branches": [],
    "include_branches": ["master", "main"]
  }
}
```

## How It Works

Branch filtering follows a two-step process:

1. **Exclude list** is applied first (default: allow all branches)
2. **Include list** is applied second (overrides excludes)

This allows flexible configurations like "exclude everything except X" or "allow everything except Y".

## Wildcard Support

Both lists support wildcard patterns using `*`:

- `master` - Exact match for "master" branch
- `stable/*` - Matches "stable/2024.1", "stable/wallaby", etc.
- `*` - Matches all branches
- `feature/*/test` - Matches "feature/foo/test", "feature/bar/test", etc.

## Examples

### Example 1: Only Review master Branch (Default)

```json
{
  "filters": {
    "exclude_branches": [],
    "include_branches": ["master", "main"]
  }
}
```

**Result:**
- ✅ `master` - Reviewed
- ✅ `main` - Reviewed
- ❌ `stable/2024.1` - Skipped
- ❌ `feature/foo` - Skipped

### Example 2: Review All Branches Except Stable

```json
{
  "filters": {
    "exclude_branches": ["stable/*"],
    "include_branches": []
  }
}
```

**Result:**
- ✅ `master` - Reviewed
- ✅ `feature/foo` - Reviewed
- ❌ `stable/2024.1` - Skipped
- ❌ `stable/wallaby` - Skipped

### Example 3: Only Review master (Exclude All Others)

```json
{
  "filters": {
    "exclude_branches": ["*"],
    "include_branches": ["master"]
  }
}
```

**Result:**
- ✅ `master` - Reviewed (include overrides exclude)
- ❌ `main` - Skipped
- ❌ `feature/foo` - Skipped
- ❌ `stable/2024.1` - Skipped

### Example 4: Review master and All Stable Branches

```json
{
  "filters": {
    "exclude_branches": ["*"],
    "include_branches": ["master", "stable/*"]
  }
}
```

**Result:**
- ✅ `master` - Reviewed
- ✅ `stable/2024.1` - Reviewed
- ✅ `stable/wallaby` - Reviewed
- ❌ `feature/foo` - Skipped
- ❌ `bugfix/123` - Skipped

### Example 5: Exclude Feature and Bugfix Branches

```json
{
  "filters": {
    "exclude_branches": ["feature/*", "bugfix/*"],
    "include_branches": []
  }
}
```

**Result:**
- ✅ `master` - Reviewed
- ✅ `stable/2024.1` - Reviewed
- ❌ `feature/test` - Skipped
- ❌ `bugfix/123` - Skipped

### Example 6: Review All Branches (No Filtering)

```json
{
  "filters": {
    "exclude_branches": [],
    "include_branches": []
  }
}
```

**Result:**
- ✅ `master` - Reviewed
- ✅ `stable/2024.1` - Reviewed
- ✅ `feature/foo` - Reviewed
- ✅ All branches - Reviewed

## Processing Logic

The filtering logic works as follows:

```python
def should_review_branch(branch_name, exclude_list, include_list):
    # Start with allowed by default
    allowed = True
    
    # Apply exclude list first
    if exclude_list:
        for pattern in exclude_list:
            if matches_wildcard(branch_name, pattern):
                allowed = False
                break
    
    # Apply include list second (overrides excludes)
    if include_list:
        # If include list exists and we didn't apply excludes,
        # default to not allowed unless matched
        if not exclude_list:
            allowed = False
        
        for pattern in include_list:
            if matches_wildcard(branch_name, pattern):
                allowed = True
                break
    
    return allowed
```

## Output

When branch filtering is active, the agent shows which branches are being filtered:

```
✓ Found 25 change(s)
📅 Cutoff date: 2026-03-03 (ignoring changes created before this date)
🌿 Branch filters: exclude=[], include=['master', 'main']
✓ Filtered to 3 reviewable change(s)
⏭️  Skipped 15 changes on excluded branches
⏭️  Skipped 5 changes created before cutoff date
⏭️  Skipped 2 already reviewed changes
```

## Testing

Test your branch filter configuration:

```bash
# Test the filtering logic
cd code-review-agent
python3 test_branch_filter.py
```

This runs comprehensive tests covering:
- Wildcard matching
- Include/exclude combinations
- Edge cases

## Common Use Cases

### 1. Production Deployments

Only review changes to protected branches:

```json
{
  "exclude_branches": ["*"],
  "include_branches": ["master", "main", "stable/*"]
}
```

### 2. Development Focus

Skip work-in-progress feature branches:

```json
{
  "exclude_branches": ["wip/*", "tmp/*"],
  "include_branches": []
}
```

### 3. Release Management

Only review release branches:

```json
{
  "exclude_branches": ["*"],
  "include_branches": ["release/*"]
}
```

### 4. Multi-Team Repository

Different teams use different branch prefixes:

```json
{
  "exclude_branches": ["team-a/*", "team-b/*"],
  "include_branches": ["team-c/*", "master"]
}
```

## Environment Variables

Branch filters can also be set via environment variables (comma-separated):

```bash
export EXCLUDE_BRANCHES="feature/*,bugfix/*"
export INCLUDE_BRANCHES="master,main"
```

**Note:** Environment variable support requires updating `config.py` to add these overrides.

## Debugging

If changes aren't being reviewed as expected:

1. Check the output for branch filter configuration
2. Verify branch names match your patterns exactly
3. Remember: include list overrides exclude list
4. Test patterns with `test_branch_filter.py`

## Performance

Branch filtering happens in memory after fetching changes from Gerrit, so:
- No impact on Gerrit API performance
- Minimal CPU overhead (simple string matching)
- Filters applied before expensive review operations

## Compatibility

Branch filtering is:
- ✅ Backward compatible (empty lists = no filtering)
- ✅ Works with existing cutoff_date filter
- ✅ Works with already-reviewed tracking
- ✅ Works with patchset tracking

## Best Practices

1. **Start restrictive, open up**: Begin with `include_branches: ["master"]` and add more as needed
2. **Use wildcards carefully**: `*` matches everything, including unexpected branches
3. **Document your filters**: Add comments in config.json explaining why branches are excluded
4. **Test before deploying**: Use `test_branch_filter.py` to verify patterns
5. **Monitor skipped counts**: Watch logs to ensure you're not skipping too many changes

## See Also

- [config.sample.json](config.sample.json) - Configuration examples
- [test_branch_filter.py](test_branch_filter.py) - Test suite
- [README.md](README.md) - Main documentation

---

*Last updated: 2026-04-02*
