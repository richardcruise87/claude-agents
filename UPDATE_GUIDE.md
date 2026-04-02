# Claude Agents - Update Guide

Quick guide for updating the agents to the latest version.

## One-Shot Update Script

**Location:** `update-agents.sh` (in repository root)

### Usage

```bash
cd ~/git/claude-agents
./update-agents.sh
```

### What It Does

The script automatically:

1. **Pulls latest code** from git repository
2. **Reinstalls all packages** in the virtual environment:
   - `agents-lib` (shared utilities)
   - `octavia-bug-triage-agent`
   - `octavia-code-review-agent`
   - `octavia-bug-reproduction-agent`
3. **Reloads systemd daemon** to pick up any service file changes
4. **Checks running services** and offers to restart them
5. **Confirms completion** with summary of updates

### Interactive Prompts

The script will ask:

```
Restart running services to apply updates? [y/N]
```

- **y**: Restart services immediately (updates apply now)
- **N**: Skip restart (updates apply on next scheduled run)

### Example Output

```
=========================================
Claude Agents Update Script
=========================================

📥 Step 1: Pulling latest changes from git...
✓ Git pull complete

📦 Step 2: Reinstalling packages in virtual environment...
   Installing agents_lib...
   Installing bug-triage-agent...
   Installing code-review-agent...
   Installing bug-reproduction-agent...
✓ All packages reinstalled

🔄 Step 3: Reloading systemd daemon...
✓ Systemd daemon reloaded

🔍 Step 4: Checking running services...
Currently running services:
  - octavia-bug-triage.timer
  - octavia-code-review.timer
  - octavia-bug-reproduction.path

Restart running services to apply updates? [y/N] y
♻️  Step 5: Restarting services...
   Restarting octavia-bug-triage.timer...
   Restarting octavia-code-review.timer...
   Restarting octavia-bug-reproduction.path...
✓ Services restarted

=========================================
✅ Update Complete!
=========================================

Updated packages:
  ✓ agents-lib (shared utilities)
  ✓ octavia-bug-triage-agent
  ✓ octavia-code-review-agent
  ✓ octavia-bug-reproduction-agent

Changes are now active in ~/.venv/claude-agents
```

## Manual Update Steps

If you prefer to update manually:

### 1. Pull Latest Code

```bash
cd ~/git/claude-agents
git pull
```

### 2. Reinstall Packages

```bash
source ~/.venv/claude-agents/bin/activate

# Reinstall in order (agents_lib first)
cd ~/git/claude-agents/agents_lib
pip install -e .

cd ~/git/claude-agents/bug-triage-agent
pip install -e .

cd ~/git/claude-agents/code-review-agent
pip install -e .

cd ~/git/claude-agents/bug-reproduction-agent
pip install -e .
```

### 3. Reload Systemd

```bash
systemctl --user daemon-reload
```

### 4. Restart Services (Optional)

```bash
# Restart timers
systemctl --user restart octavia-bug-triage.timer
systemctl --user restart octavia-code-review.timer

# Restart path watcher
systemctl --user restart octavia-bug-reproduction.path
```

## Verification

After updating, verify the services are working:

```bash
# Check service status
systemctl --user status octavia-bug-triage.timer
systemctl --user status octavia-code-review.timer
systemctl --user status octavia-bug-reproduction.path

# View timer schedule
systemctl --user list-timers octavia-*

# Check logs for errors
journalctl --user -u octavia-bug-triage.service -n 50
journalctl --user -u octavia-code-review.service -n 50
journalctl --user -u octavia-bug-reproduction.service -n 50
```

## When to Restart Services

**You should restart services immediately if:**
- Bug fixes that affect currently running code
- New features you want to use right away
- Configuration changes in agent code
- Critical security updates

**You can skip restart if:**
- Documentation-only changes
- Non-urgent feature additions
- Changes to unrelated agents
- You're okay waiting for next scheduled run

## Troubleshooting

### Virtual Environment Not Found

**Error:**
```
❌ ERROR: Virtual environment not found at ~/.venv/claude-agents
   Run systemd/setup-systemd.sh first to create it
```

**Solution:**
```bash
cd ~/git/claude-agents/systemd
./setup-systemd.sh
```

### Permission Errors

**Error:**
```
Permission denied: ~/.venv/claude-agents
```

**Solution:**
Ensure the virtual environment is owned by your user:
```bash
ls -la ~/.venv/claude-agents
# Should show your username, not root
```

### Git Pull Conflicts

**Error:**
```
error: Your local changes to the following files would be overwritten by merge
```

**Solution:**
Stash or commit your local changes first:
```bash
# Option 1: Stash changes
git stash
./update-agents.sh
git stash pop  # Restore your changes

# Option 2: Commit changes
git add .
git commit -m "Local changes"
./update-agents.sh
```

### Service Restart Fails

**Error:**
```
Failed to restart octavia-bug-triage.timer: Unit not found
```

**Solution:**
Service may not be enabled. Check and enable:
```bash
systemctl --user list-unit-files octavia-*
systemctl --user enable octavia-bug-triage.timer
systemctl --user start octavia-bug-triage.timer
```

## Update Frequency

**Recommended update schedule:**

- **Daily:** If actively developing/testing
- **Weekly:** For production use with active development
- **Monthly:** For stable production deployments
- **As needed:** When new features or bug fixes are announced

## Checking for Updates

Before running the update script:

```bash
cd ~/git/claude-agents
git fetch
git log HEAD..origin/main --oneline
```

This shows what commits will be pulled.

## Rollback

If an update causes issues, you can rollback:

```bash
cd ~/git/claude-agents

# Find the previous commit
git log --oneline -n 5

# Rollback to previous version (replace COMMIT_HASH)
git checkout COMMIT_HASH

# Reinstall packages
./update-agents.sh
```

To return to latest:
```bash
git checkout main
git pull
./update-agents.sh
```

## Configuration Changes

**Note:** The update script only updates code, not configuration files.

If `config.json` files need updates:
- Review the corresponding `config.sample.json` for new options
- Manually update your `config.json` files
- Restart services to apply config changes

## See Also

- [systemd/README.md](systemd/README.md) - Systemd service documentation
- [CLAUDE.md](CLAUDE.md) - Complete project documentation
- [agents_lib/](agents_lib/) - Shared library documentation

---

*Last updated: 2026-04-02*
