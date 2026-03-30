# CLAUDE.md - Claude Agents Repository

Context file for AI instances working with this repository.

**Last Updated:** 2026-03-30
**Repository:** https://github.com/richardcruise87/claude-agents
**Purpose:** AI-powered automation agents for OpenStack development

---

## Project Overview

This repository contains Claude-based automation agents for OpenStack project maintenance:

1. **Bug Triage Agent** (`bug-triage-agent/`) - Monitors Launchpad for bugs, performs intelligent triage
2. **Code Review Agent** (`code-review-agent/`) - Monitors Gerrit for changes, performs AI-powered code reviews
3. **Shared Library** (`agents_lib/`) - Common utilities shared between agents

### Key Features

- **Automated Monitoring**: Fetches bugs/changes from Launchpad/Gerrit APIs
- **AI-Powered Analysis**: Uses Claude (via Vertex AI) for intelligent triage/review
- **Sequence Tracking**: Tracks multiple triages/reviews of the same item
- **Smart Skipping**: Only processes items that have been updated
- **Cutoff Date Filtering**: Ignores items created before configurable date
- **Subprocess Isolation**: Multi-item processing without SDK conflicts

---

## Installation

### Package-based Installation (Recommended)

All agents can be installed as Python packages using pip:

```bash
# Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate

# Install shared library
pip install -e agents_lib/

# Install agents individually
pip install -e bug-triage-agent/    # Provides: octavia-triage-bugs
pip install -e code-review-agent/   # Provides: octavia-review-agent, octavia-review-change
```

**Installed Commands:**
- `octavia-triage-bugs [--single-bug FILE]` - Bug triage agent
- `octavia-review-agent` - Code review monitoring agent
- `octavia-review-change <change_number> [patchset]` - Review specific change

**Dependencies:**
Each agent package automatically installs:
- `claude-agent-sdk` - AI agent framework
- `agents-lib` - Shared utilities library

### Direct Execution (Development)

```bash
# Run agents directly without installation
cd bug-triage-agent
./bug_triage_agent.py

cd code-review-agent
./octavia_review_agent.py
./review_single_change.py <change_number>
```

**Note:** Direct execution requires `agents_lib` to be installed separately:
```bash
cd agents_lib
pip install -e .
```

---

## Repository Structure

```
claude-agents/
├── CLAUDE.md                    # This file - context for AI instances
├── README.md                    # User-facing documentation
├── LICENSE                      # Apache 2.0 license
│
├── agents_lib/                  # Shared library package
│   ├── setup.py                 # Package installation
│   └── agents_lib/
│       ├── __init__.py          # Public API exports
│       ├── config_loader.py     # Config loading utilities
│       ├── prompt_loader.py     # Template loading utilities
│       ├── tracking.py          # Item tracking utilities
│       └── utils.py             # Common utilities
│
├── bug-triage-agent/            # Launchpad bug triage agent
│   ├── setup.py                 # Package installation
│   ├── MANIFEST.in              # Package data inclusion
│   ├── bug_triage_agent.py      # Main agent (fetches bugs, orchestrates)
│   ├── config.py                # Configuration loader
│   ├── config.sample.json       # Template configuration
│   ├── config.json              # Active config (gitignored)
│   ├── bug_tracker.py           # Bug tracking wrappers
│   ├── prompts/
│   │   ├── __init__.py          # Prompt loader
│   │   └── bug_triage_prompt.txt # Triage prompt template
│   ├── README.md                # Agent documentation
│   └── QUICK_START.md           # Quick start guide
│
└── code-review-agent/           # Gerrit code review agent
    ├── setup.py                 # Package installation
    ├── MANIFEST.in              # Package data inclusion
    ├── octavia_review_agent.py  # Main monitoring agent
    ├── review_single_change.py  # Single change review script
    ├── config.py                # Configuration loader
    ├── config.sample.json       # Template configuration
    ├── config.json              # Active config (gitignored)
    ├── patchset_tracker.py      # Patchset tracking
    ├── prompts/
    │   ├── __init__.py          # Prompt loader
    │   └── code_review_prompt.txt # Review prompt template
    ├── README.md                # Agent documentation
    └── QUICK_START.md           # Quick start guide
```

---

## Shared Library (`agents_lib`)

**Installation:**
```bash
cd agents_lib
pip install -e .  # Editable install for development
```

**Key Modules:**

### `config_loader.py`
Generic configuration loading with environment variable overrides:
- `load_agent_config(config_dir, env_overrides, defaults)` - Load config from JSON + env vars
- `apply_cutoff_date(config, key_path, default_days)` - Apply cutoff date logic
- `expand_config_paths(config, path_keys)` - Expand ~ and env vars in paths

### `tracking.py`
Item tracking (bugs, changes, patchsets):
- `load_tracking_file(tracking_file)` - Load tracking history
- `save_tracking_file(tracking_file, history)` - Save tracking history
- `should_process_item(item_id, item_last_updated, history, id_prefix)` - Check if item needs processing
- `record_processed_item(tracking_file, item_id, ...)` - Record processed item
- `create_output_filename(output_dir, item_id, item_title, sequence, ...)` - Generate filenames

### `utils.py`
Common utilities:
- `expand_path(path_str)` - Expand ~ and environment variables
- `slugify(text, max_length)` - Convert text to filesystem-safe slug

### `prompt_loader.py`
Template loading:
- `load_prompt_template(template_name, prompts_dir)` - Load prompt from file
- `format_prompt(template, **replacements)` - Format template with replacements

**Usage Pattern:**
```python
from agents_lib import (
    load_agent_config,
    apply_cutoff_date,
    expand_config_paths,
    should_process_item,
    record_processed_item,
)
```

---

## Bug Triage Agent

**Purpose:** Monitor Launchpad for Octavia bugs and perform AI-powered triage

**Key Files:**
- `bug_triage_agent.py` - Main entry point
- `bug_tracker.py` - Wrapper functions for backward compatibility
- `prompts/bug_triage_prompt.txt` - 183-line triage prompt template

**Configuration:** `config.json`
```json
{
  "launchpad_project": "octavia",
  "triages_output_dir": "~/octavia_bug_triages",
  "devstack_path": "/opt/stack",
  "max_bugs_per_run": 5,
  "cutoff_date": null,  // null = 30 days ago
  "bug_statuses": ["New", "Confirmed", "Triaged", "In Progress"],
  "triage_tracking_file": "~/.octavia_bug_triages.json"
}
```

**Output Format:**
```
bug_<number>_<title-slug>_<timestamp>_<sequence>.md
Example: bug_2146764_test_backup_member_randomly_fails_20260330_103423_1.md
```

**Sequence Tracking:**
- Sequence 1: Initial triage
- Sequence 2+: Re-triage after bug update
- Compares `date_last_updated` from Launchpad with tracking file
- Only re-triages if bug has new information

**Subprocess Isolation:**
When `max_bugs_per_run > 1`:
- Each bug triaged in separate subprocess
- Avoids Claude Agent SDK asyncio cleanup issues
- Uses `--single-bug <json-file>` internal mode

**Running:**
```bash
./bug_triage_agent.py
```

---

## Code Review Agent

**Purpose:** Monitor Gerrit for OpenStack changes and perform AI-powered code reviews

**Key Files:**
- `octavia_review_agent.py` - Main monitoring agent
- `review_single_change.py` - Single change review script
- `patchset_tracker.py` - Patchset tracking and history
- `prompts/code_review_prompt.txt` - Review prompt template

**Configuration:** `config.json`
```json
{
  "repositories": ["openstack/octavia", "openstack/octavia-lib", ...],
  "devstack": {"path": "/opt/stack"},
  "output": {"reviews_directory": "~/octavia_reviews"},
  "gerrit": {"base_url": "https://review.opendev.org"},
  "monitoring": {
    "max_reviews_per_cycle": 3,
    "reviewed_changes_file": "~/.octavia_reviewed_changes.json"
  },
  "filters": {
    "cutoff_date": null,  // null = 30 days ago
    "skip_wip": true,
    "skip_draft": true
  }
}
```

**Output Format:**
```
review_<repo>_<change_number>_ps<patchset>_<timestamp>.md
Example: review_openstack_octavia_982567_ps1_20260330_103423.md
```

**Patchset Tracking:**
- Tracks each patchset separately: `change_id~ps1`, `change_id~ps2`, etc.
- Provides previous review context to AI when reviewing new patchsets
- Compares changes between patchsets

**Running:**
```bash
./octavia_review_agent.py
```

---

## Important Patterns and Conventions

### Configuration Loading

**Pattern used by both agents:**
```python
from agents_lib import load_agent_config, apply_cutoff_date, expand_config_paths

config = load_agent_config(config_dir, env_overrides, defaults)
config = apply_cutoff_date(config, "cutoff_date", default_days=30)
config = expand_config_paths(config, path_keys)
```

**Environment Variable Overrides:**
- Bug triage: `TRIAGES_OUTPUT_DIR`, `DEVSTACK_PATH`, `LAUNCHPAD_PROJECT`, `MAX_BUGS`, `CUTOFF_DATE`
- Code review: `REVIEWS_OUTPUT_DIR`, `DEVSTACK_PATH`, `GERRIT_URL`, `MAX_REVIEWS`, `CUTOFF_DATE`

### Cutoff Date Logic

**Default Behavior:**
- If `cutoff_date` is `null` or not specified: defaults to current date - 30 days
- Format: `YYYY-MM-DD` (e.g., `"2026-03-01"`)
- Filters items by **creation date** (not last update date)

**Purpose:** Focus on recent items, reduce processing time

### Tracking Files

**Bug Triage:** `~/.octavia_bug_triages.json`
```json
{
  "bug_2146764": {
    "last_triaged": "2026-03-30T10:40:34.069365",
    "last_updated": "2026-03-30T08:36:48.382279+00:00",
    "sequence": 1
  }
}
```

**Code Review:** `~/.octavia_reviewed_changes.json`
```json
{
  "982567~ps1": {
    "last_processed": "2026-03-30T11:30:00.000000",
    "last_updated": "2026-03-29T14:20:00.000000",
    "sequence": 1
  }
}
```

### Prompt Templates

**Location:** `<agent>/prompts/<prompt_name>.txt`

**Loading:**
```python
from agents_lib import load_prompt_template

template = load_prompt_template("bug_triage_prompt", prompts_dir)
```

**Replacement Pattern:** `{placeholder}` syntax
```python
formatted = template.replace('{bug_number}', bug_number)
formatted = formatted.replace('{bug_title}', bug_title)
# ... etc
```

**Why separate files:**
- Keeps main code clean
- Easy to edit prompts without touching Python
- Better for version control and prompt engineering

---

## Development Workflow

### Making Changes to Agents

1. **Test configuration changes:**
```bash
cd bug-triage-agent  # or code-review-agent
python3 config.py    # Test config loading
```

2. **Test agent startup:**
```bash
timeout 10 ./bug_triage_agent.py  # Quick startup test
```

3. **Test with specific config:**
```bash
export CUTOFF_DATE="2026-03-29"
./bug_triage_agent.py
```

### Making Changes to Shared Library

1. **Edit files in `agents_lib/agents_lib/`**

2. **No reinstall needed** (editable install)

3. **Test with both agents:**
```bash
cd bug-triage-agent && python3 config.py
cd ../code-review-agent && python3 config.py
```

4. **Update `__init__.py`** if adding new functions:
```python
from .new_module import new_function
__all__ = [..., "new_function"]
```

### Git Commit Guidelines

**Commit Message Format:**
```
<action> <component>: <brief description>

<detailed description>

Changes:
- Bullet points of changes

Testing:
✅ What was tested
✅ Test results

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

**Common Actions:**
- `Add` - New feature
- `Fix` - Bug fix
- `Refactor` - Code restructuring
- `Update` - Modify existing feature
- `Create` - New file/module

---

## Common Issues and Solutions

### Claude Agent SDK Asyncio Issues

**Problem:** Sequential `query()` calls cause `RuntimeError: Attempted to exit cancel scope in a different task`

**Solution:** Subprocess isolation (already implemented)
- Bug triage: Uses subprocess when `max_bugs_per_run > 1`
- Each subprocess gets fresh Python interpreter and asyncio loop
- Internal `--single-bug` mode for subprocess

### Cutoff Date Not Filtering

**Check:**
1. Is `cutoff_date` in the config?
2. Is it being applied correctly? (Check startup message)
3. Are items' creation dates being compared (not update dates)?

**Debug:**
```python
print(f"Item created: {item_created_date}")
print(f"Cutoff date: {CONFIG['cutoff_date']}")
print(f"Should skip: {item_created_date < CONFIG['cutoff_date']}")
```

### Config Not Loading

**Common causes:**
1. No `config.json` or `config.sample.json`
2. Invalid JSON syntax
3. Missing required fields

**Fix:**
```bash
cp config.sample.json config.json
python3 -m json.tool config.json  # Validate JSON
```

### Tracking File Corruption

**Symptoms:** Items being re-processed unnecessarily

**Fix:**
```bash
# Backup
cp ~/.octavia_bug_triages.json ~/.octavia_bug_triages.json.bak

# Validate
python3 -m json.tool ~/.octavia_bug_triages.json

# Reset if needed
echo '{}' > ~/.octavia_bug_triages.json
```

---

## Testing

### Unit Testing Config Modules

```bash
# Bug triage
cd bug-triage-agent
python3 config.py
python3 -c "from bug_tracker import *; print('Imports OK')"

# Code review
cd code-review-agent
python3 config.py
```

### Integration Testing Agents

```bash
# Test with cutoff date to avoid processing many items
export CUTOFF_DATE="2026-03-29"
export MAX_BUGS=1  # or MAX_REVIEWS=1

timeout 30 ./bug_triage_agent.py
# Check: Should start, fetch items, filter by cutoff, process 1 item
```

### Testing Shared Library

```bash
cd agents_lib
python3 -c "
from agents_lib import *
print('All imports successful')
print(slugify('Test Title With Spaces'))
print(expand_path('~/test'))
"
```

---

## Architecture Decisions

### Why Shared Library?

**Before:** 170 lines of duplicate code between agents
**After:** 250+ lines of reusable shared code

**Benefits:**
- Bug fixes apply to both agents
- Consistent behavior
- Easier to add new agents
- Proper Python package structure

### Why Subprocess Isolation?

**Problem:** Claude Agent SDK has asyncio cleanup issues when calling `query()` multiple times

**Alternatives Considered:**
1. ❌ Manual sleep between calls - Fragile, arbitrary timing
2. ❌ Fix SDK directly - Beyond project scope
3. ✅ Subprocess isolation - Clean, reliable, already works

**Implementation:**
- Create temp JSON file with bug/change data
- Run `python agent.py --single-bug /tmp/data.json`
- Subprocess gets fresh asyncio loop
- Main process continues after subprocess completes

### Why Cutoff Date?

**Problem:** Processing old bugs/changes wastes time

**Solution:** Configurable cutoff date
- Default: 30 days ago
- Filters by creation date
- Reduces API calls and processing time
- Focus on recent items

### Why Sequence Tracking?

**Problem:** Need to track multiple triages/reviews of same item

**Solution:** Sequence numbers
- Sequence 1: Initial triage/review
- Sequence 2+: Re-triage/review after updates
- Compare timestamps to detect updates
- Provides previous context to AI

---

## External Dependencies

### Required

- **Python 3.8+**
- **claude-agent-sdk** - AI agent framework
- **httpx** - Async HTTP client (recommended)
  - Falls back to urllib if not available
  - Much more reliable for API calls

### Optional

- **DevStack** - For code analysis (path configured in `config.json`)
- **git** - For checking commit history, searching fixes

### APIs Used

- **Launchpad API** - `https://api.launchpad.net/1.0/`
  - Bug tracking for OpenStack projects
  - No authentication required for read-only access

- **Gerrit API** - `https://review.opendev.org/`
  - Code review platform for OpenStack
  - Public API, no authentication for read access

- **Vertex AI** - Claude API access
  - Requires `CLAUDE_CODE_USE_VERTEX=1`
  - Authentication via gcloud

---

## Future Enhancements

### Potential Improvements

1. **Parallel Processing**
   - Currently sequential in subprocess mode
   - Could run multiple subprocesses in parallel
   - Would need concurrency control

2. **Database Backend**
   - Currently uses JSON files for tracking
   - SQLite would be more robust
   - Better for querying history

3. **Web Interface**
   - View triage/review history
   - Search processed items
   - Statistics and trends

4. **Notification System**
   - Email/Slack notifications
   - Alert on high-priority bugs
   - Daily/weekly summaries

5. **More Agents**
   - Release notes generator
   - Documentation checker
   - Test coverage analyzer

---

## Key Learnings

### From Development

1. **Prompt Engineering is Critical**
   - Keep prompts in separate files
   - Iterate on prompt quality
   - Provide clear structure and examples

2. **Tracking Prevents Waste**
   - Always track what's been processed
   - Compare timestamps, not just IDs
   - Sequence numbers for multiple processings

3. **Configuration Must Be Portable**
   - Environment variable overrides
   - Defaults that work out of box
   - Path expansion for ~ and $VAR

4. **SDK Quirks Require Workarounds**
   - Subprocess isolation for asyncio issues
   - Can't always fix upstream
   - Pragmatic solutions win

5. **Shared Code Pays Off**
   - Initial overhead to create library
   - But eliminates bugs in multiple places
   - Makes adding agents much easier

---

## Quick Reference

### Starting Agents

```bash
# Bug triage
cd bug-triage-agent
./bug_triage_agent.py

# Code review
cd code-review-agent
./octavia_review_agent.py
```

### Configuration Files

- `config.json` - Active config (gitignored)
- `config.sample.json` - Template to copy
- Tracking files in `~/.octavia_*`

### Output Locations

- Bug triages: `~/octavia_bug_triages/`
- Code reviews: `~/octavia_reviews/`

### Environment Variables

```bash
export CUTOFF_DATE="2026-03-01"
export MAX_BUGS=3
export MAX_REVIEWS=5
export DEVSTACK_PATH="/opt/stack"
```

---

**For more details, see individual agent READMEs and QUICK_START guides.**
