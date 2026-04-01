# Quick Start Guide - Bug Reproduction Agent

Get the Octavia Bug Reproduction Agent up and running in 5 minutes.

## Prerequisites

- Python 3.8+
- DevStack installation (running)
- Bug Triage Agent configured (optional but recommended)
- Claude Agent SDK credentials (Vertex AI)

## Installation Steps

### 1. Install Package

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

### 2. Create Configuration

```bash
# Copy sample config
cd ~/git/claude-agents/bug-reproduction-agent
cp config.sample.json config.json

# Edit if needed (defaults should work)
vim config.json
```

**Minimum required:**
```json
{
  "triage_reports_dir": "~/octavia_bug_triages",
  "reproductions_output_dir": "~/octavia_bug_reproductions",
  "devstack": {
    "path": "/opt/stack",
    "openrc_file": "/opt/stack/devstack/openrc"
  }
}
```

### 3. Verify DevStack Health

```bash
# Check Octavia services
systemctl status devstack@o-api devstack@o-cw devstack@o-hm

# Test API
source /opt/stack/devstack/openrc admin admin
openstack loadbalancer list
```

### 4. Test Manual Run

```bash
# Make sure you have at least one triage report
ls ~/octavia_bug_triages/

# Run agent
octavia-reproduce-bugs
```

**Expected output:**
```
================================================================================
Octavia Bug Reproduction Agent
================================================================================

Configuration:
  Triage reports: ~/octavia_bug_triages
  Output directory: ~/octavia_bug_reproductions
  Tracking file: ~/.octavia_bug_reproductions.json
  Max attempts: 3
  Script timeout: 600s

Found 1 triage files

Processing new triage: bug_2146764_test_backup_member_randomly_fails_20260330_103423_1.md

================================================================================
Processing triage: bug_2146764_test_backup_member_randomly_fails_20260330_103423_1.md
================================================================================

📄 Parsing triage report...
   Bug: #2146764 - test_backup_member_randomly_fails...
   Severity: Medium
   Reproduction steps: 4 bash blocks

🏥 Checking DevStack health...
   ✅ DevStack is healthy

🔧 Attempt 1/3
   Generating initial script from triage...
   Executing script (timeout: 600s)...
   Exit code: 0
   Error type: BUG_REPRODUCED
   Execution time: 45.2s
   ✅ Bug reproduced successfully!

📝 Generating reproduction report...
   💾 Saved reproduction script: ~/octavia_bug_reproductions/scripts/bug_2146764_reproduction.sh
   💾 Saved report: ~/octavia_bug_reproductions/reproduction_2146764_..._1.md

================================================================================
✅ Bug #2146764 successfully reproduced!
================================================================================

================================================================================
✅ Reproduction cycle complete!
================================================================================
```

### 5. Check Output

```bash
# View report
ls -lh ~/octavia_bug_reproductions/
cat ~/octavia_bug_reproductions/reproduction_*.md

# View reproduction script (if successful)
ls -lh ~/octavia_bug_reproductions/scripts/
cat ~/octavia_bug_reproductions/scripts/bug_*.sh
```

## Setup Automation (systemd)

### 6. Install systemd Units

```bash
cd ~/git/claude-agents/systemd
./setup-systemd.sh
```

**Follow prompts:**
- Creates virtual environment (if needed)
- Installs all packages
- Checks configuration files
- Installs systemd service and path files

### 7. Enable Path Watcher

```bash
# Enable path unit (watches ~/octavia_bug_triages/)
systemctl --user enable octavia-bug-reproduction.path
systemctl --user start octavia-bug-reproduction.path

# Enable persistence after logout
loginctl enable-linger $USER
```

### 8. Verify Automation

```bash
# Check path unit status
systemctl --user status octavia-bug-reproduction.path
```

**Expected:** `active (waiting)`

**Test trigger:**
```bash
# Create test file in triage directory
touch ~/octavia_bug_triages/test_trigger.md

# Watch logs (should trigger service)
journalctl --user -u octavia-bug-reproduction.service -f
```

**Clean up test:**
```bash
rm ~/octavia_bug_triages/test_trigger.md
```

## Integration with Bug Triage Agent

The Bug Reproduction Agent works best with the Bug Triage Agent:

```bash
# Enable bug triage timer (runs daily at 9 AM)
systemctl --user enable octavia-bug-triage.timer
systemctl --user start octavia-bug-triage.timer

# Bug reproduction path already enabled (watches for new triages)
systemctl --user status octavia-bug-reproduction.path
```

**Workflow:**
1. Bug Triage Agent runs (timer or manual)
2. Creates triage report in `~/octavia_bug_triages/`
3. Path unit detects new file
4. Bug Reproduction Agent triggers automatically
5. Reproduction report saved to `~/octavia_bug_reproductions/`

## Quick Reference

### Commands

```bash
# Manual run
octavia-reproduce-bugs

# Check path watcher
systemctl --user status octavia-bug-reproduction.path

# View logs
journalctl --user -u octavia-bug-reproduction.service -f

# List timers and paths
systemctl --user list-timers
systemctl --user list-units --type=path
```

### Files

```bash
# Configuration
~/.venv/claude-agents/                          # Virtual environment
~/git/claude-agents/bug-reproduction-agent/config.json  # Active config

# Input
~/octavia_bug_triages/                          # Triage reports (input)

# Output
~/octavia_bug_reproductions/                    # Reproduction reports
~/octavia_bug_reproductions/scripts/            # Reproduction scripts
~/.octavia_bug_reproductions.json               # Tracking file

# systemd
~/.config/systemd/user/octavia-bug-reproduction.path     # Path unit
~/.config/systemd/user/octavia-bug-reproduction.service  # Service unit
```

### Environment Variables

```bash
# Override config
export TRIAGES_DIR="~/octavia_bug_triages"
export REPRODUCTIONS_OUTPUT_DIR="~/octavia_bug_reproductions"
export DEVSTACK_PATH="/opt/stack"
export MAX_ATTEMPTS=3
export SCRIPT_TIMEOUT=600

# Run with overrides
octavia-reproduce-bugs
```

## Common Tasks

### Reprocess a Bug

```bash
# Remove from tracking file
vim ~/.octavia_bug_reproductions.json
# Delete the bug entry

# Run agent again
octavia-reproduce-bugs
```

### Increase Script Timeout

```bash
# Edit config
vim ~/git/claude-agents/bug-reproduction-agent/config.json
# Change: "script_timeout": 1200

# Or use environment variable
export SCRIPT_TIMEOUT=1200
octavia-reproduce-bugs
```

### View Specific Reproduction

```bash
# Find report
ls ~/octavia_bug_reproductions/ | grep <bug_number>

# View report
cat ~/octavia_bug_reproductions/reproduction_<bug_number>_*.md

# View script (if successful)
cat ~/octavia_bug_reproductions/scripts/bug_<bug_number>_reproduction.sh
```

### Disable Automation

```bash
# Stop and disable path watcher
systemctl --user stop octavia-bug-reproduction.path
systemctl --user disable octavia-bug-reproduction.path
```

### Enable Automation Again

```bash
systemctl --user enable octavia-bug-reproduction.path
systemctl --user start octavia-bug-reproduction.path
```

## Troubleshooting

### No Reproductions Happening

**Check 1: Path unit running?**
```bash
systemctl --user status octavia-bug-reproduction.path
```
Expected: `active (waiting)`

**Check 2: Triage files exist?**
```bash
ls ~/octavia_bug_triages/
```
Expected: At least one `bug_*.md` file

**Check 3: Already processed?**
```bash
cat ~/.octavia_bug_reproductions.json
```
Remove entry to reprocess

**Check 4: Trigger manually**
```bash
touch ~/octavia_bug_triages/test.md
journalctl --user -u octavia-bug-reproduction.service -f
rm ~/octavia_bug_triages/test.md
```

### DevStack Health Failures

**Check services:**
```bash
systemctl status devstack@o-api devstack@o-cw devstack@o-hm
```

**Restart if needed:**
```bash
sudo systemctl restart devstack@o-*
```

**Check API:**
```bash
source /opt/stack/devstack/openrc admin admin
openstack loadbalancer list
```

### Service Errors

**View detailed logs:**
```bash
journalctl --user -u octavia-bug-reproduction.service --no-pager -n 100
```

**Common errors:**

1. **Config not found**
   ```bash
   cd ~/git/claude-agents/bug-reproduction-agent
   cp config.sample.json config.json
   ```

2. **Venv not found**
   ```bash
   cd ~/git/claude-agents/systemd
   ./setup-systemd.sh
   ```

3. **Claude credentials**
   ```bash
   export CLAUDE_CODE_USE_VERTEX=1
   gcloud auth application-default login
   ```

### Script Failures

**Test script manually:**
```bash
source /opt/stack/devstack/openrc admin admin
bash ~/octavia_bug_reproductions/scripts/bug_<number>_reproduction.sh
```

**View report for details:**
```bash
cat ~/octavia_bug_reproductions/reproduction_<number>_*.md
```
Look for "Reproduction Attempts" section with error details.

## Next Steps

- Read [README.md](README.md) for comprehensive documentation
- See [../systemd/README.md](../systemd/README.md) for advanced systemd configuration
- Check [../README.md](../README.md) for overall project documentation

## Support

For issues or questions:
- Check logs: `journalctl --user -u octavia-bug-reproduction.service`
- Review configuration: `~/git/claude-agents/bug-reproduction-agent/config.json`
- See main repository issues: https://github.com/richardcruise87/claude-agents/issues
