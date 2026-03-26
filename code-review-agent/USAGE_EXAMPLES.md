# Usage Examples - Octavia Code Review Agent

Complete guide to using the Octavia Code Review Agent with all available options.

## Basic Usage

### Review Latest Patchset

```bash
# By change number (simplest)
./review_single_change.py 919846

# By URL
./review_single_change.py https://review.opendev.org/c/openstack/octavia/+/919846
```

**Output:**
```
📋 Change Details:
  Repository: openstack/octavia
  Change Number: 919846
  URL: https://review.opendev.org/c/openstack/octavia/+/919846

🔍 Fetching latest patchset information from Gerrit...
✓ Patchset: 3 (latest)
✓ Ref: refs/changes/46/919846/3

📄 Review will be saved to: review_openstack_octavia_919846_ps3_20260326_143000-latest.md
```

## Review Specific Patchsets

### By Positional Argument

```bash
# Review patchset 1
./review_single_change.py 919846 1

# Review patchset 2
./review_single_change.py 919846 2

# Review patchset 3
./review_single_change.py 919846 3
```

### By Flag

```bash
# Using --patchset
./review_single_change.py 919846 --patchset 2

# Using -p (short form)
./review_single_change.py 919846 -p 2
```

### With URLs

```bash
# URL + patchset number
./review_single_change.py https://review.opendev.org/c/openstack/octavia/+/919846 2

# URL + flag
./review_single_change.py https://review.opendev.org/c/openstack/octavia/+/919846 --patchset 2
```

**Output for specific patchset:**
```
📌 Reviewing patchset 2

📋 Change Details:
  Repository: openstack/octavia
  Change Number: 919846

🔍 Fetching patchset 2 information from Gerrit...
✓ Patchset: 2 (requested)
✓ Ref: refs/changes/46/919846/2

📄 Review will be saved to: review_openstack_octavia_919846_ps2_20260326_143000-latest.md
```

## Common Scenarios

### Scenario 1: Review Original Submission

Developer uploads PS 1. You want to review the initial version:

```bash
./review_single_change.py 919846 1
```

Creates: `review_openstack_octavia_919846_ps1_timestamp-latest.md`

### Scenario 2: Review After Developer Updates

Developer uploads PS 2 addressing feedback. Review the latest:

```bash
./review_single_change.py 919846
# or explicitly
./review_single_change.py 919846 2
```

Creates: `review_openstack_octavia_919846_ps2_timestamp-latest.md`

The agent will:
- Detect previous PS 1 review
- Rename PS 1 review (removes `-latest`)
- Compare PS 2 with PS 1
- Note which issues were fixed

### Scenario 3: Compare Multiple Patchsets

You want to compare PS 1 and PS 3 manually:

```bash
# Review PS 1
./review_single_change.py 919846 1

# Review PS 3
./review_single_change.py 919846 3

# Compare the review files
diff ~/octavia_reviews/review_*_ps1_*.md ~/octavia_reviews/review_*_ps3_*.md
```

### Scenario 4: Historical Context

Change is at PS 5, but discussion mentions an issue from PS 2:

```bash
# Review PS 2 to see the historical context
./review_single_change.py 919846 2
```

### Scenario 5: Validate Bug Fix

Bug reported in PS 1, claimed fixed in PS 3:

```bash
# Review PS 1 to confirm bug exists
./review_single_change.py 919846 1

# Review PS 3 to confirm bug is fixed
./review_single_change.py 919846 3

# Check both reviews for the specific issue
grep -A 5 "specific bug pattern" ~/octavia_reviews/review_*_ps1_*.md
grep -A 5 "specific bug pattern" ~/octavia_reviews/review_*_ps3_*.md
```

## Review File Naming

All review files include the patchset number for easy tracking:

```bash
~/octavia_reviews/
├── review_openstack_octavia_919846_ps1_20260326_120000.md       # Historical
├── review_openstack_octavia_919846_ps2_20260326_130000.md       # Historical
├── review_openstack_octavia_919846_ps3_20260326_140000-latest.md  # Current
```

**Naming Pattern:**
```
review_{repository}_{change}_{ps_number}_{timestamp}[-latest].md
```

- **`-latest`**: Current/most recent review
- **Without `-latest`**: Historical review

## Finding Reviews

### Find Latest Review for a Change

```bash
ls -t ~/octavia_reviews/review_*_919846_*-latest.md | head -1
```

### Find Specific Patchset Review

```bash
ls ~/octavia_reviews/review_*_919846_ps2_*.md
```

### Find All Reviews for a Change

```bash
ls ~/octavia_reviews/review_*_919846_*.md
```

### Count Patchsets Reviewed

```bash
ls ~/octavia_reviews/review_*_919846_ps*.md | wc -l
```

## Advanced Usage

### Review Multiple Patchsets in Sequence

```bash
# Script to review all patchsets from 1 to 5
for ps in {1..5}; do
    echo "Reviewing patchset $ps..."
    ./review_single_change.py 919846 $ps
    sleep 5  # Brief pause between reviews
done
```

### Review with Custom Output Location

```bash
# Set output directory via environment variable
export REVIEWS_OUTPUT_DIR=/custom/path/reviews
./review_single_change.py 919846 2
```

### Batch Review Multiple Changes

```bash
# Review latest patchset for multiple changes
for change in 919846 919847 919848; do
    ./review_single_change.py $change
done

# Review specific patchsets
./review_single_change.py 919846 2
./review_single_change.py 919847 1
./review_single_change.py 919848 3
```

## Help and Options

### Show Help

```bash
./review_single_change.py --help
```

Output:
```
usage: review_single_change.py [-h] [--patchset PATCHSET_FLAG]
                               change [patchset]

Review an OpenStack Octavia change from OpenDev

positional arguments:
  change                Change number or Gerrit URL
  patchset              Specific patchset number to review (e.g., 2).
                        If omitted, reviews the latest patchset.

options:
  -h, --help            show this help message and exit
  --patchset PATCHSET_FLAG, -p PATCHSET_FLAG
                        Alternative way to specify patchset number

Examples:
  # Review latest patchset
  review_single_change.py 919846

  # Review specific patchset
  review_single_change.py 919846 2
  review_single_change.py 919846 --patchset 3

  # Review using URL
  review_single_change.py https://review.opendev.org/c/openstack/octavia/+/919846

  # Review specific patchset using URL
  review_single_change.py https://review.opendev.org/c/openstack/octavia/+/919846 2
```

## Integration with Workflow

### In Your Daily Workflow

```bash
# Morning: Check new changes
./octavia_review_agent.py

# Specific change needs attention at PS 2
./review_single_change.py 919846 2

# Developer uploads PS 3
./review_single_change.py 919846  # Latest (PS 3)

# Read incremental review
cat ~/octavia_reviews/review_*_919846_ps3_*-latest.md
```

### In CI/CD Pipeline

```bash
#!/bin/bash
# review_pipeline.sh

CHANGE=$1
PATCHSET=$2

echo "Starting review pipeline for change $CHANGE PS $PATCHSET"

# Run review
./review_single_change.py $CHANGE $PATCHSET

# Check for critical issues
REVIEW_FILE=$(ls -t ~/octavia_reviews/review_*_${CHANGE}_ps${PATCHSET}_*.md | head -1)

if grep -q "Critical Issues 🔴" "$REVIEW_FILE"; then
    echo "❌ Critical issues found - review required"
    exit 1
else
    echo "✅ No critical issues - can proceed"
    exit 0
fi
```

### With Git Hooks

```bash
# .git/hooks/pre-push

#!/bin/bash
# Review changes before pushing to Gerrit

CHANGE_ID=$(git log -1 --pretty=%B | grep "Change-Id:" | cut -d: -f2 | tr -d ' ')

if [ -n "$CHANGE_ID" ]; then
    echo "Running review before push..."
    ./review_single_change.py $CHANGE_ID
fi
```

## Troubleshooting

### "Patchset not found"

If you try to review a patchset that doesn't exist:

```bash
# Change only has PS 1 and 2, but you try PS 5
./review_single_change.py 919846 5
```

The agent will fail during git fetch. Check available patchsets on Gerrit first.

### "Invalid patchset number"

Patchset must be a positive integer:

```bash
# ❌ Invalid
./review_single_change.py 919846 0
./review_single_change.py 919846 -1
./review_single_change.py 919846 abc

# ✅ Valid
./review_single_change.py 919846 1
./review_single_change.py 919846 10
```

### Multiple Review Files

If you review the same patchset multiple times, you'll get multiple files:

```
review_openstack_octavia_919846_ps2_20260326_130000-latest.md
review_openstack_octavia_919846_ps2_20260326_140000-latest.md  # Same PS, later time
```

The latest by timestamp is the most recent review.

## Best Practices

### 1. Review in Order

Review patchsets sequentially for best context:

```bash
./review_single_change.py 919846 1
./review_single_change.py 919846 2
./review_single_change.py 919846 3
```

### 2. Use Latest for Current State

Unless you need historical context, review the latest:

```bash
# Best for current state
./review_single_change.py 919846
```

### 3. Archive Old Reviews

Periodically archive old reviews to keep directory clean:

```bash
# Move reviews older than 30 days
find ~/octavia_reviews -name "*.md" -mtime +30 -exec mv {} ~/octavia_reviews/archive/ \;
```

### 4. Check Patchset Count First

On Gerrit web UI, check how many patchsets exist before reviewing specific ones.

### 5. Document Your Process

Keep notes on which patchsets you reviewed and why:

```bash
echo "PS 2: Reviewed focus on security fixes" >> ~/octavia_reviews/notes.txt
```

---

**Last Updated:** March 26, 2026
**Version:** 2.2 (Specific Patchset Support)
