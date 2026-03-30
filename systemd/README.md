# Systemd Integration for Claude Agents

This directory contains systemd service and timer files for running the Claude Agents automatically on a schedule.

## Quick Start

```bash
# Run the setup script
cd systemd
./setup-systemd.sh

# Enable and start the timers
systemctl --user enable octavia-bug-triage.timer
systemctl --user start octavia-bug-triage.timer

systemctl --user enable octavia-code-review.timer
systemctl --user start octavia-code-review.timer

# Enable user services to persist after logout
loginctl enable-linger $USER
```

## Overview

Each agent has two systemd units:

| Agent | Service | Timer | Default Schedule |
|-------|---------|-------|------------------|
| Bug Triage | `octavia-bug-triage.service` | `octavia-bug-triage.timer` | Daily at 9:00 AM |
| Code Review | `octavia-code-review.service` | `octavia-code-review.timer` | Every 4 hours |

## Files

- **`octavia-bug-triage.service`** - Bug triage agent service
- **`octavia-bug-triage.timer`** - Bug triage scheduling timer
- **`octavia-code-review.service`** - Code review agent service
- **`octavia-code-review.timer`** - Code review scheduling timer
- **`setup-systemd.sh`** - Automated setup script
- **`README.md`** - This file

## Setup Details

### Automatic Setup (Recommended)

The `setup-systemd.sh` script automates the entire process:

1. Creates a virtual environment at `~/.venv/claude-agents/`
2. Installs all agent packages in the venv
3. Checks for configuration files
4. Installs service and timer files to `~/.config/systemd/user/`
5. Reloads systemd
6. Provides next steps

### Manual Setup

If you prefer manual setup:

#### 1. Create Virtual Environment

```bash
python3 -m venv ~/.venv/claude-agents
source ~/.venv/claude-agents/bin/activate

# Install packages
pip install -e ../agents_lib/
pip install -e ../bug-triage-agent/
pip install -e ../code-review-agent/

deactivate
```

#### 2. Configure Agents

Ensure each agent has a `config.json` file:

```bash
cd ../bug-triage-agent
cp config.sample.json config.json
# Edit config.json

cd ../code-review-agent
cp config.sample.json config.json
# Edit config.json
```

#### 3. Install Systemd Files

Copy service and timer files to your systemd user directory:

```bash
mkdir -p ~/.config/systemd/user/

# Update paths in service files (replace %h with actual home, %u with username)
sed "s|%h|$HOME|g; s|%u|$USER|g" octavia-bug-triage.service > ~/.config/systemd/user/octavia-bug-triage.service
sed "s|%h|$HOME|g; s|%u|$USER|g" octavia-code-review.service > ~/.config/systemd/user/octavia-code-review.service

# Copy timer files
cp octavia-bug-triage.timer ~/.config/systemd/user/
cp octavia-code-review.timer ~/.config/systemd/user/

# Reload systemd
systemctl --user daemon-reload
```

## Usage

### Enable and Start Timers

```bash
# Bug triage agent
systemctl --user enable octavia-bug-triage.timer
systemctl --user start octavia-bug-triage.timer

# Code review agent
systemctl --user enable octavia-code-review.timer
systemctl --user start octavia-code-review.timer
```

### Check Timer Status

```bash
# List all timers
systemctl --user list-timers

# Check specific timer
systemctl --user status octavia-bug-triage.timer
systemctl --user status octavia-code-review.timer
```

### Run Services Manually

```bash
# Trigger a run immediately (for testing)
systemctl --user start octavia-bug-triage.service
systemctl --user start octavia-code-review.service

# Check service status
systemctl --user status octavia-bug-triage.service
systemctl --user status octavia-code-review.service
```

### View Logs

```bash
# Follow logs in real-time
journalctl --user -u octavia-bug-triage.service -f
journalctl --user -u octavia-code-review.service -f

# View recent logs
journalctl --user -u octavia-bug-triage.service -n 50
journalctl --user -u octavia-code-review.service -n 50

# View logs since a specific time
journalctl --user -u octavia-bug-triage.service --since "1 hour ago"
journalctl --user -u octavia-code-review.service --since "today"
```

### Stop and Disable Timers

```bash
# Stop timers
systemctl --user stop octavia-bug-triage.timer
systemctl --user stop octavia-code-review.timer

# Disable timers (won't start on boot)
systemctl --user disable octavia-bug-triage.timer
systemctl --user disable octavia-code-review.timer
```

## Customization

### Changing Schedules

Edit the timer files in `~/.config/systemd/user/` and modify the `OnCalendar` directive:

```ini
[Timer]
# Daily at 9:00 AM
OnCalendar=*-*-* 09:00:00

# Every hour
OnCalendar=hourly

# Every 6 hours
OnCalendar=00/6:00:00

# Weekdays at 9 AM and 5 PM
OnCalendar=Mon..Fri *-*-* 09:00:00
OnCalendar=Mon..Fri *-*-* 17:00:00
```

After editing, reload systemd:

```bash
systemctl --user daemon-reload
systemctl --user restart octavia-bug-triage.timer
```

### Environment Variables

Edit the service files to add environment variables:

```ini
[Service]
Environment="CLAUDE_CODE_USE_VERTEX=1"
Environment="CUTOFF_DATE=2026-03-01"
Environment="MAX_BUGS=5"
Environment="MAX_REVIEWS=3"
```

After editing:

```bash
systemctl --user daemon-reload
```

### Resource Limits

Uncomment and adjust resource limits in service files:

```ini
[Service]
# Limit memory to 2GB
MemoryMax=2G

# Limit CPU to 50%
CPUQuota=50%
```

### Using a Different Virtual Environment

Edit the service files and change the `ExecStart` path:

```ini
[Service]
ExecStart=/path/to/your/venv/bin/octavia-triage-bugs
```

## Persistence After Logout

By default, user systemd services stop when you log out. To keep them running:

```bash
# Enable user lingering
loginctl enable-linger $USER

# Check lingering status
loginctl show-user $USER | grep Linger
```

## Troubleshooting

### Service Fails to Start

```bash
# Check service status
systemctl --user status octavia-bug-triage.service

# View full logs
journalctl --user -u octavia-bug-triage.service --no-pager

# Test the command directly
~/.venv/claude-agents/bin/octavia-triage-bugs
```

### Timer Not Triggering

```bash
# Check if timer is active
systemctl --user is-active octavia-bug-triage.timer

# Check timer details
systemctl --user list-timers octavia-bug-triage.timer

# Verify timer is enabled
systemctl --user is-enabled octavia-bug-triage.timer
```

### Virtual Environment Not Found

Ensure the venv path in service files matches your actual venv location:

```bash
# Check ExecStart path in service file
grep ExecStart ~/.config/systemd/user/octavia-bug-triage.service

# Verify venv exists
ls -la ~/.venv/claude-agents/bin/octavia-triage-bugs
```

### Configuration File Issues

```bash
# Check if config files exist
ls -la ~/git/claude-agents/bug-triage-agent/config.json
ls -la ~/git/claude-agents/code-review-agent/config.json

# Validate JSON syntax
python3 -m json.tool ~/git/claude-agents/bug-triage-agent/config.json
```

### Google Cloud Credentials

Ensure Vertex AI credentials are available to the service:

```bash
# For application default credentials
gcloud auth application-default login

# For service account (add to service file)
Environment="GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json"
```

## Monitoring

### Create Status Dashboard

```bash
#!/bin/bash
# save as ~/bin/agent-status.sh

echo "=== Systemd Timer Status ==="
systemctl --user list-timers | grep octavia

echo ""
echo "=== Recent Bug Triage Runs ==="
journalctl --user -u octavia-bug-triage.service --since "1 week ago" --no-pager | grep -E "Triage cycle complete|ERROR"

echo ""
echo "=== Recent Code Review Runs ==="
journalctl --user -u octavia-code-review.service --since "1 week ago" --no-pager | grep -E "Review cycle complete|ERROR"
```

### Email Notifications on Failure

Add to service files:

```ini
[Service]
OnFailure=failure-notification@%n.service
```

Then create a notification service (see systemd documentation).

## Examples

### Run Bug Triage Every Morning

```bash
# Edit ~/.config/systemd/user/octavia-bug-triage.timer
[Timer]
OnCalendar=*-*-* 09:00:00
Persistent=true
```

### Run Code Review During Business Hours

```bash
# Edit ~/.config/systemd/user/octavia-code-review.timer
[Timer]
OnCalendar=Mon..Fri *-*-* 09,11,13,15,17:00:00
Persistent=true
```

### Run with Custom Configuration

```bash
# Edit ~/.config/systemd/user/octavia-bug-triage.service
[Service]
Environment="CUTOFF_DATE=2026-03-15"
Environment="MAX_BUGS=10"
Environment="TRIAGES_OUTPUT_DIR=/custom/path/triages"
```

## Advanced Usage

### Running as System Service (Root)

For system-wide services (requires root):

```bash
sudo cp *.service *.timer /etc/systemd/system/
# Edit files to use absolute paths and specific user
sudo systemctl daemon-reload
sudo systemctl enable octavia-bug-triage.timer
sudo systemctl start octavia-bug-triage.timer
```

### Multiple Instances

To run multiple instances with different configs:

```bash
# Copy and rename service files
cp octavia-bug-triage.service octavia-bug-triage-urgent.service

# Edit to use different config or environment variables
Environment="CUTOFF_DATE=2026-03-29"
Environment="MAX_BUGS=20"

# Create corresponding timer
cp octavia-bug-triage.timer octavia-bug-triage-urgent.timer
# Edit Requires= line to match new service name
```

## See Also

- [systemd.service man page](https://www.freedesktop.org/software/systemd/man/systemd.service.html)
- [systemd.timer man page](https://www.freedesktop.org/software/systemd/man/systemd.timer.html)
- [systemd user units](https://wiki.archlinux.org/title/Systemd/User)
- [Repository README](../README.md)
- [Bug Triage Agent README](../bug-triage-agent/README.md)
- [Code Review Agent README](../code-review-agent/README.md)
