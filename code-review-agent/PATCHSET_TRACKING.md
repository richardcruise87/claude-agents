# Patchset Tracking and Incremental Reviews

The Octavia Code Review Agent now supports **incremental reviews** across multiple patchsets of the same change.

## Overview

When a developer uploads a new patchset to address review feedback:
1. ✅ The agent detects it's a new patchset of a previously reviewed change
2. ✅ Loads the previous review for context
3. ✅ Focuses on what changed between patchsets
4. ✅ Notes which issues were addressed and which remain
5. ✅ Preserves review history with proper filenames

## How It Works

### Patchset Detection

The agent fetches patchset information from Gerrit API:
```bash
GET /changes/919846?o=CURRENT_REVISION
```

Extracts:
- Current patchset number (e.g., PS 2, PS 3)
- Git ref for fetching the specific patchset

### Review File Naming

**First Review (PS 1):**
```
review_openstack_octavia_919846_ps1_20260326_120000-latest.md
```

**Second Review (PS 2):**
- Old file renamed: `review_openstack_octavia_919846_ps1_20260326_120000.md` (no -latest)
- New file created: `review_openstack_octavia_919846_ps2_20260326_130000-latest.md`

**Pattern:**
```
review_{repo}_{change}_ps{num}_{timestamp}[-latest].md
                        ^^^^^^              ^^^^^^^^
                        patchset            current review
```

### Review Context

When reviewing PS 2+, the agent receives:
1. **Full previous review** - All findings from the last review
2. **Previous patchset number** - To compare versions
3. **Instruction to focus on changes** - What's different

## Review Document Structure

### For First Review (PS 1)

```markdown
# Code Review: openstack/octavia - Change #919846

**Patchset**: 1
**First Review**

## Change Summary
[Normal review content]

## Test Results
[Test output]

## Code Analysis
[Detailed analysis]

...
```

### For Subsequent Reviews (PS 2+)

```markdown
# Code Review: openstack/octavia - Change #919846

**Patchset**: 2
**Previous Review**: Patchset 1

## Change Summary
[What changed in PS 2]

## Changes Since Previous Review (PS 1)

### Issues Addressed
- ✅ Fixed KeyError in jinja_cfg.py line 388
- ✅ Corrected cipher filtering logic
- ⚠️ Jinja2 typo still present (needs attention)

### New Changes in This Patchset
- Modified: octavia/common/jinja/haproxy/combined_listeners/jinja_cfg.py
  - Changed dict.pop() instead of del
  - Fixed cipher set filtering
- Added: New test case for TLS 1.3 ciphers
- No files removed

### New Issues Introduced
- Minor: Missing docstring in new helper function

### Overall Progress
The patchset addresses 2 of 4 critical issues from PS 1.
Moving in the right direction, but still needs work.

---

## Test Results
[Current test output]

## Code Analysis
[Analysis focused on new changes and remaining issues]

...
```

## Example Workflow

### Developer uploads PS 1

```bash
# You review it
./review_single_change.py 919846

# Creates: review_openstack_octavia_919846_ps1_20260326_120000-latest.md
# Contains: 4 critical issues found
```

### Developer uploads PS 2 fixing 2 issues

```bash
# You review it again
./review_single_change.py 919846

# What happens:
# 1. Old file renamed: review_..._ps1_...-latest.md → review_..._ps1_....md
# 2. Agent loads PS 1 review as context
# 3. Creates new: review_..._ps2_...-latest.md
# 4. New review includes:
#    - ✅ Fixed: Issues 1 and 2
#    - ❌ Still present: Issues 3 and 4
#    - Focus on the 2 fixes and any new code
```

### Developer uploads PS 3 fixing remaining issues

```bash
./review_single_change.py 919846

# What happens:
# 1. Old PS 2 file renamed (removes -latest)
# 2. Agent loads PS 2 review as context
# 3. Creates: review_..._ps3_...-latest.md
# 4. New review notes all issues resolved!
```

## File History Example

After reviewing PS 1, 2, and 3:

```
~/octavia_reviews/
├── review_openstack_octavia_919846_ps1_20260326_120000.md
├── review_openstack_octavia_919846_ps2_20260326_130000.md
└── review_openstack_octavia_919846_ps3_20260326_140000-latest.md
                                                           ^^^^^^^
                                                           current review
```

- **-latest** = Most recent review
- **Without -latest** = Historical reviews

## Benefits

### For Reviewers

✅ **Don't repeat yourself** - Agent remembers what you already reviewed
✅ **Focus on changes** - See only what's new in this patchset
✅ **Track progress** - Clear view of which issues were addressed
✅ **Historical context** - All previous reviews preserved

### For Developers

✅ **Targeted feedback** - Know exactly what changed
✅ **Progress tracking** - See improvements acknowledged
✅ **Clear expectations** - Understand what still needs work

### For Teams

✅ **Review history** - Full audit trail of the change evolution
✅ **Learning tool** - See how changes improved over time
✅ **Quality metrics** - Track issue resolution across patchsets

## API Integration

### Patchset Tracker Module

```python
from patchset_tracker import (
    find_previous_reviews,
    get_latest_review,
    prepare_review_context,
    create_review_filename,
    rename_review_with_patchset
)

# Find all reviews for a change
reviews = find_previous_reviews(output_dir, "openstack/octavia", "919846")

# Get the most recent review
latest = get_latest_review(output_dir, "openstack/octavia", "919846")

# Prepare context for new review (renames old file)
prev_content, prev_ps, old_file = prepare_review_context(
    output_dir, "openstack/octavia", "919846", current_patchset=2
)

# Create filename for new review
new_file = create_review_filename(
    output_dir, "openstack/octavia", "919846", patchset_number=2, timestamp
)
```

## Configuration

No configuration needed! Patchset tracking is automatic when:
- Gerrit API is accessible
- Change has multiple patchsets
- You review the same change more than once

## Limitations

### Current

- **Patchset detection** requires Gerrit API access
- **Context size** limited to ~3000 chars from previous review
- **Manual comparison** if patchset number can't be determined

### Future Enhancements

Potential improvements:
- [ ] Side-by-side diff of previous vs current patchset
- [ ] Issue tracking across patchsets with IDs
- [ ] Summary of all patchsets in a change
- [ ] Git range-diff between patchsets
- [ ] Metrics on issue resolution rate

## Troubleshooting

### "Previous review not found"

The agent looks for files matching:
```
review_{repo}_{change_number}_*.md
```

If you have reviews but they're not being found:
- Check the filename pattern matches
- Ensure they're in the correct output directory
- Verify the change number matches

### "Patchset number unknown"

If Gerrit API is unreachable or the format changed:
- Review still works, just without patchset number in filename
- Previous reviews will still be detected by change number
- Comparison section may be skipped

### "Old review not renamed"

If the old review file doesn't get renamed:
- Check file permissions in output directory
- Verify patchset numbers were detected
- Old review will still be loaded for context

## Best Practices

### Review Workflow

1. **Review each patchset** as it's uploaded
2. **Reference previous reviews** when commenting
3. **Note progress** in your Gerrit comments
4. **Keep -latest reviews** for current state

### File Management

- **Keep old reviews** - they're your audit trail
- **Back up review directory** periodically
- **Archive old changes** after merge

### Team Collaboration

- **Share review directory** with team (if appropriate)
- **Reference review files** in team discussions
- **Use reviews as learning material** for new team members

---

**Feature Status**: ✅ Implemented and tested
**Version**: 2.1 (Patchset Tracking)
**Date**: March 26, 2026
