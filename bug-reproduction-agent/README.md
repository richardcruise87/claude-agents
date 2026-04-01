# Octavia Bug Reproduction Agent

AI-powered bug reproduction agent that watches for bug triage reports and attempts to reproduce bugs in DevStack environments.

## Overview

The Bug Reproduction Agent automates the process of validating bug triage reports by:

1. Watching for new bug triage reports (from the Bug Triage Agent)
2. Parsing reproduction steps from triage markdown files
3. Checking DevStack environment health
4. Generating bash scripts to reproduce the bug
5. Executing scripts with safety controls (timeouts, cleanup)
6. Iteratively refining scripts using AI (up to 3 attempts)
7. Generating comprehensive reproduction reports
8. Saving successful reproduction scripts for reuse

## Features

- **Event-Driven Triggering**: systemd Path unit watches triage directory using inotify
- **Single-Bug Processing**: Ensures only one bug reproduction runs at a time (single DevStack constraint)
- **AI-Powered Script Generation**: Uses Claude Agent SDK to generate and refine reproduction scripts
- **Smart Tracking**: Avoids reprocessing bugs, tracks reproduction status and attempts
- **DevStack Health Checks**: Validates environment before attempting reproduction
- **Safe Script Execution**: Timeouts, cleanup traps, resource limits
- **Comprehensive Reporting**: Documents all attempts, outputs, and analysis
- **Error Categorization**: Distinguishes script errors from environment errors from successful reproductions

## Architecture

```
New Triage Report (~/octavia_bug_triages/)
         ↓
systemd Path Unit (inotify watch)
         ↓
Triggers octavia-bug-reproduction.service
         ↓
Bug Reproduction Agent (Type=oneshot)
         ↓
1. Find newest unprocessed triage
2. Parse triage markdown
3. Check DevStack health
4. Attempt 1: Generate script from triage
5. Execute script (timeout: 600s)
6. Attempt 2-3: AI refines script if needed
7. Generate report
8. Save successful script
9. Update tracking file
         ↓
Exit (systemd queues next trigger if needed)
```

## Installation

### 1. Install as Python Package

```bash
# Create virtual environment
python3 -m venv ~/.venv/claude-agents
source ~/.venv/claude-agents/bin/activate

# Install shared library
cd ~/git/claude-agents/agents_lib
pip install -e .

# Install bug-reproduction-agent
cd ~/git/claude-agents/bug-reproduction-agent
pip install -e .
```

This installs the `octavia-reproduce-bugs` command.

### 2. Configure

```bash
# Copy sample configuration
cp config.sample.json config.json

# Edit configuration (set paths, parameters)
vim config.json
```

**Required Configuration:**
- `triage_reports_dir`: Directory where triage reports are saved (default: `~/octavia_bug_triages`)
- `reproductions_output_dir`: Directory for reproduction reports and scripts (default: `~/octavia_bug_reproductions`)
- `devstack.path`: Path to DevStack installation (default: `/opt/stack`)
- `devstack.openrc_file`: OpenStack credentials file (default: `/opt/stack/devstack/openrc`)

**Optional Configuration:**
- `reproduction.max_attempts`: Maximum script refinement attempts (default: 3)
- `reproduction.script_timeout`: Script execution timeout in seconds (default: 600)
- `cutoff_date`: Only process triages for bugs created after this date (default: 30 days ago)

### 3. Setup systemd Integration

```bash
# Run setup script
cd ~/git/claude-agents/systemd
./setup-systemd.sh

# Enable and start path watcher
systemctl --user enable octavia-bug-reproduction.path
systemctl --user start octavia-bug-reproduction.path

# Enable persistence after logout
loginctl enable-linger $USER
```

## Usage

### Automatic (systemd Path Watcher)

The path unit watches `~/octavia_bug_triages/` for changes. When a new triage report appears, the service automatically triggers.

**Check status:**
```bash
systemctl --user status octavia-bug-reproduction.path
systemctl --user list-timers  # Shows queued triggers
```

**View logs:**
```bash
journalctl --user -u octavia-bug-reproduction.service -f
```

### Manual Execution

Run the agent manually for testing:

```bash
source ~/.venv/claude-agents/bin/activate
octavia-reproduce-bugs
```

The agent will:
1. Find the newest unprocessed triage report
2. Attempt reproduction
3. Generate report
4. Exit

## Configuration

### config.json

```json
{
  "triage_reports_dir": "~/octavia_bug_triages",
  "reproductions_output_dir": "~/octavia_bug_reproductions",
  "reproduction_tracking_file": "~/.octavia_bug_reproductions.json",

  "devstack": {
    "path": "/opt/stack",
    "openrc_file": "/opt/stack/devstack/openrc",
    "required_services": [
      "devstack@o-api.service",
      "devstack@o-cw.service",
      "devstack@o-hm.service",
      "devstack@keystone.service",
      "devstack@n-api.service",
      "devstack@q-svc.service"
    ],
    "health_timeout": 30,
    "min_disk_space_gb": 10
  },

  "reproduction": {
    "max_attempts": 3,
    "script_timeout": 600,
    "cleanup_after_attempt": true,
    "working_directory": "/tmp/octavia-reproductions"
  },

  "cutoff_date": null
}
```

### Environment Variables

Override configuration with environment variables:

- `TRIAGES_DIR` → `triage_reports_dir`
- `REPRODUCTIONS_OUTPUT_DIR` → `reproductions_output_dir`
- `DEVSTACK_PATH` → `devstack.path`
- `MAX_ATTEMPTS` → `reproduction.max_attempts`
- `SCRIPT_TIMEOUT` → `reproduction.script_timeout`
- `CUTOFF_DATE` → `cutoff_date`

**Example:**
```bash
export MAX_ATTEMPTS=5
export SCRIPT_TIMEOUT=900
octavia-reproduce-bugs
```

### systemd Service Environment

Edit `~/.config/systemd/user/octavia-bug-reproduction.service`:

```ini
[Service]
Environment="CLAUDE_CODE_USE_VERTEX=1"
Environment="MAX_ATTEMPTS=3"
Environment="SCRIPT_TIMEOUT=600"
```

## Output

### Reproduction Reports

Location: `~/octavia_bug_reproductions/`

**Filename format:** `reproduction_<bug_number>_<title_slug>_<timestamp>_<sequence>.md`

**Example:** `reproduction_2146764_test_backup_member_randomly_fails_20260330_143022_1.md`

**Report sections:**
- Executive Summary
- Triage Summary
- DevStack Health Check
- Reproduction Attempts (all attempts with scripts and outputs)
- Root Cause Analysis (if reproduced)
- Final Reproduction Script (if reproduced)
- Recommendations

### Reproduction Scripts

Location: `~/octavia_bug_reproductions/scripts/`

**Filename format:** `bug_<bug_number>_reproduction.sh`

**Example:** `bug_2146764_reproduction.sh`

Scripts are saved only for successfully reproduced bugs and are made executable.

### Tracking File

Location: `~/.octavia_bug_reproductions.json`

Tracks which bugs have been processed to avoid duplicates.

**Format:**
```json
{
  "bug_2146764": {
    "last_processed": "2026-03-30T14:30:22.123456",
    "triage_file": "~/octavia_bug_triages/bug_2146764_..._1.md",
    "sequence": 1,
    "reproduction_status": "REPRODUCED",
    "attempts": 2,
    "final_script_path": "~/octavia_bug_reproductions/scripts/bug_2146764_reproduction.sh"
  }
}
```

## Reproduction Process

### 1. Parse Triage Report

Extracts from markdown:
- Bug number, title, severity
- Reproduction steps (bash code blocks from Step 7)
- Prerequisites and expected behavior
- Root cause summary

### 2. DevStack Health Check

Verifies:
- Required systemd services running
- OpenStack API connectivity
- Sufficient disk space
- Paths exist

If unhealthy, aborts with environment error report.

### 3. Script Generation (Attempt 1)

- Extracts bash commands from triage report
- Wraps in safety template:
  - `set -euo pipefail` for error handling
  - Cleanup trap for resource deletion
  - Progress logging
  - OpenStack credential sourcing

### 4. Script Execution

- Writes to temporary file
- Makes executable
- Runs with timeout (default: 600s)
- Captures stdout/stderr
- Enforces cleanup on exit

### 5. Result Analysis

Categorizes outcome:
- **REPRODUCED**: Bug successfully appeared
- **NOT_REPRODUCED**: Script ran without error, bug didn't appear
- **SCRIPT_ERROR**: Script syntax or logic error
- **TIMEOUT**: Exceeded time limit
- **ENVIRONMENT_ERROR**: DevStack or service failure

### 6. Script Refinement (Attempts 2-3)

If attempt 1 fails:
- Uses Claude Agent SDK for AI-powered refinement
- Provides: previous script, error output, triage context
- AI generates improved script addressing:
  - Timing issues (add waits)
  - Resource readiness checks
  - Error handling improvements
  - Alternative approaches

### 7. Report Generation

Comprehensive markdown report with:
- All attempts and their outputs
- Scripts used in each attempt
- Error analysis
- Root cause (if reproduced)
- Recommendations for developers

## Error Handling

### Reproduction Status Types

1. **REPRODUCED** - Bug successfully reproduced
   - Script executed without error or expected error appeared
   - Reproduction script saved
   - Root cause analysis included

2. **NOT_REPRODUCED** - Could not reproduce bug
   - Scripts ran but bug didn't appear
   - May be intermittent or environment-specific
   - All attempts documented

3. **ENVIRONMENT_ERROR** - DevStack unhealthy
   - Services down, API unreachable, disk full
   - Abort immediately (don't count as attempt)
   - Report environment status

4. **SCRIPT_ERROR** - Script failures
   - Syntax errors, missing resources
   - AI refines for next attempt

5. **TIMEOUT** - Script exceeded time limit
   - Long-running operations
   - AI optimizes for next attempt

### Resource Cleanup

All scripts include cleanup trap:
```bash
trap cleanup EXIT
function cleanup() {
    echo "=== Cleanup ==="
    openstack loadbalancer delete --cascade test-lb 2>/dev/null || true
}
```

Cleanup always executes, even on:
- Script errors
- Timeouts
- Manual interruption

### systemd Resource Limits

Service includes safety limits:
- `MemoryMax=4G` - Prevent memory exhaustion
- `CPUQuota=100%` - One CPU core max
- `TimeoutSec=1800` - 30 minute hard limit (3 attempts × 600s + overhead)

## Troubleshooting

### No Reproductions Happening

**Check path unit:**
```bash
systemctl --user status octavia-bug-reproduction.path
```

Expected: `active (waiting)`

**Test trigger manually:**
```bash
touch ~/octavia_bug_triages/test.md
journalctl --user -u octavia-bug-reproduction.service -f
```

### Service Failing

**View logs:**
```bash
journalctl --user -u octavia-bug-reproduction.service --no-pager
```

**Common issues:**
- Config file missing: `cp config.sample.json config.json`
- Venv not found: Check `ExecStart` path in service file
- DevStack unhealthy: Check service status
- Credentials missing: Set `CLAUDE_CODE_USE_VERTEX=1`

### DevStack Health Failures

**Check services:**
```bash
systemctl status devstack@o-api devstack@o-cw devstack@o-hm
```

**Check API:**
```bash
source /opt/stack/devstack/openrc admin admin
openstack loadbalancer list
```

**Check disk:**
```bash
df -h /opt/stack
```

### Scripts Not Working

**Test script manually:**
```bash
source /opt/stack/devstack/openrc admin admin
bash ~/octavia_bug_reproductions/scripts/bug_XXXXXX_reproduction.sh
```

**Increase timeout:**
```bash
export SCRIPT_TIMEOUT=1200  # 20 minutes
octavia-reproduce-bugs
```

### Already Processed Bugs

The agent tracks processed bugs in `~/.octavia_bug_reproductions.json`.

**Reprocess a bug:**
```bash
# Remove from tracking file
vim ~/.octavia_bug_reproductions.json  # Delete bug entry

# Or reset all tracking
mv ~/.octavia_bug_reproductions.json ~/.octavia_bug_reproductions.json.bak
echo '{}' > ~/.octavia_bug_reproductions.json
```

## Integration with Bug Triage Agent

The Bug Reproduction Agent completes the automated bug analysis pipeline:

```
Launchpad Bug
     ↓
Bug Triage Agent → Triage Report
     ↓
Bug Reproduction Agent → Reproduction Report + Script
```

**Setup both agents:**
1. Bug Triage Agent creates triage reports in `~/octavia_bug_triages/`
2. Bug Reproduction Agent watches that directory
3. New triage triggers reproduction attempt
4. Reproduction report saved to `~/octavia_bug_reproductions/`

**systemd timer example:**
```bash
# Bug triage runs daily at 9 AM
systemctl --user enable octavia-bug-triage.timer

# Bug reproduction watches for new triages
systemctl --user enable octavia-bug-reproduction.path

# Process: Triage at 9 AM → Reproduction triggered automatically
```

## Advanced Configuration

### Custom Prompt Templates

Edit prompt templates to customize AI behavior:

- `prompts/script_generation_prompt.txt` - Initial script generation
- `prompts/script_refinement_prompt.txt` - Script refinement after failures

Templates use `{placeholder}` syntax for variable substitution.

### Multiple DevStack Environments

To run on multiple DevStack hosts, create separate service files:

```bash
# Copy and customize
cp ~/.config/systemd/user/octavia-bug-reproduction.service \
   ~/.config/systemd/user/octavia-bug-reproduction-dev2.service

# Edit to use different config
vim ~/.config/systemd/user/octavia-bug-reproduction-dev2.service
# Change WorkingDirectory or add Environment="DEVSTACK_PATH=/opt/stack2"
```

### Resource Limits

Edit service file to adjust limits:

```ini
[Service]
MemoryMax=8G          # Allow more memory
CPUQuota=200%         # Allow 2 CPU cores
TimeoutSec=3600       # 1 hour timeout
```

## Development

### Running Tests

```bash
# Test triage parsing
cd ~/git/claude-agents/bug-reproduction-agent
python3 -c "
from triage_parser import parse_triage_file
from pathlib import Path
triage = parse_triage_file(Path('~/octavia_bug_triages/bug_XXXXXX.md'))
print(f'Bug: {triage.bug_number}')
print(f'Steps: {len(triage.reproduction_steps)}')
"
```

```bash
# Test DevStack health
python3 -c "
from devstack_health import check_devstack_health
from config import load_config
config = load_config()
health = check_devstack_health(config)
print(f'Healthy: {health.all_healthy}')
"
```

### Adding Custom Modules

1. Create module in `bug-reproduction-agent/`
2. Import in `bug_reproduction_agent.py`
3. Test with `pip install -e .` (editable install)

### Contributing

See main repository README for contribution guidelines.

## See Also

- [QUICK_START.md](QUICK_START.md) - Quick start guide
- [../README.md](../README.md) - Main repository documentation
- [../agents_lib/](../agents_lib/) - Shared library documentation
- [../systemd/README.md](../systemd/README.md) - systemd setup guide

## License

Apache License 2.0 - See [../LICENSE](../LICENSE)
