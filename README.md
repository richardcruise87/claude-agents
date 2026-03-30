# Claude Agents

Collection of AI agents powered by Claude via Google Vertex AI.

## Agents

### [Bug Triage Agent](bug-triage-agent/)

AI-powered bug triage agent for OpenStack Launchpad bugs.

**Features:**
- 🐛 Monitors Launchpad for new bugs
- 🔍 Performs intelligent bug analysis and triage
- 🎯 Suggests reproduction strategies
- 🔎 Checks for duplicates and potential fixes
- 📝 Generates detailed triage reports
- ⏱️ Tracks and re-triages updated bugs

**Quick start:**
```bash
octavia-triage-bugs  # After installation
# Or run directly:
cd bug-triage-agent
./bug_triage_agent.py
```

**Documentation:** [bug-triage-agent/README.md](bug-triage-agent/README.md)

### [Code Review Agent](code-review-agent/)

AI-powered code review agent for OpenStack Octavia projects on OpenDev.

**Features:**
- 🔍 Monitors OpenDev for new changes
- 🧪 Runs unit, functional, and style tests
- 📊 Performs comprehensive code analysis
- 📝 Generates detailed review documents
- ⚖️ Provides recommendations and verdicts
- 🔄 Tracks patchset changes and provides context

**Quick start:**
```bash
octavia-review-change <change_number>  # After installation
# Or run directly:
cd code-review-agent
./review_single_change.py <change_number>
```

**Documentation:** [code-review-agent/README.md](code-review-agent/README.md)

### [Bug Reproduction Agent](bug-reproduction-agent/)

AI-powered bug reproduction agent that validates bug triage reports in DevStack environments.

**Features:**
- 🔬 Watches for new bug triage reports
- 🤖 AI-generated reproduction scripts
- 🔄 Iterative script refinement (up to 3 attempts)
- 🏥 DevStack health checks
- 🛡️ Safe execution with timeouts and cleanup
- 📝 Comprehensive reproduction reports
- 💾 Saves working reproduction scripts

**Quick start:**
```bash
octavia-reproduce-bugs  # After installation
# Or run directly:
cd bug-reproduction-agent
./bug_reproduction_agent.py
```

**Documentation:** [bug-reproduction-agent/README.md](bug-reproduction-agent/README.md)

---

## About

These agents use the [Claude Agent SDK](https://docs.anthropic.com/en/docs/build-with-claude/agent-sdk) to perform autonomous, multi-step tasks.

**Technology:**
- Claude models via Google Vertex AI
- Python 3.8+
- Claude Agent SDK

## Installation

### Option 1: Install as Python Packages (Recommended)

Each agent can be installed individually as a Python package:

```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install shared library
pip install -e agents_lib/

# Install agents individually
pip install -e bug-triage-agent/          # Installs 'octavia-triage-bugs' command
pip install -e code-review-agent/         # Installs 'octavia-review-agent' and 'octavia-review-change' commands
pip install -e bug-reproduction-agent/    # Installs 'octavia-reproduce-bugs' command
```

After installation, the agents are available as commands:
- `octavia-triage-bugs` - Bug triage agent
- `octavia-review-agent` - Code review monitoring agent
- `octavia-review-change <change_number>` - Review a specific change
- `octavia-reproduce-bugs` - Bug reproduction agent

### Option 2: Run Directly (Development)

```bash
cd bug-triage-agent
./bug_triage_agent.py

cd code-review-agent
./octavia_review_agent.py
./review_single_change.py <change_number>
```

### Prerequisites

- Python 3.8+
- Vertex AI access: `export CLAUDE_CODE_USE_VERTEX=1`
- Google Cloud credentials configured:
  - Application default: `gcloud auth application-default login`
  - Or service account: `export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json`

### Configuration

Each agent requires a `config.json` file (created from `config.sample.json`):

```bash
cd bug-triage-agent
cp config.sample.json config.json
# Edit config.json with your settings

cd code-review-agent
cp config.sample.json config.json
# Edit config.json with your settings
```

## Automation with Systemd

Run agents automatically on a schedule using systemd timers:

```bash
# Quick setup
cd systemd
./setup-systemd.sh

# Enable timers
systemctl --user enable octavia-bug-triage.timer
systemctl --user start octavia-bug-triage.timer

systemctl --user enable octavia-code-review.timer
systemctl --user start octavia-code-review.timer

# Enable path watcher for bug reproduction (event-driven)
systemctl --user enable octavia-bug-reproduction.path
systemctl --user start octavia-bug-reproduction.path

# Enable persistence after logout
loginctl enable-linger $USER
```

**Default Schedules:**
- Bug Triage: Daily at 9:00 AM
- Code Review: Every 4 hours
- Bug Reproduction: Event-driven (triggered by new triage reports)

**Features:**
- Runs in isolated virtual environment
- Automatic scheduling with systemd timers
- Logging via journald
- Easy monitoring with systemctl
- Customizable schedules and resource limits

See [systemd/README.md](systemd/README.md) for complete documentation.

## Adding New Agents

Create a new directory under `claude-agents/` with:
- `README.md` - Agent documentation
- Python scripts - Agent implementation
- Configuration files - Agent settings
- `.gitignore` - Ignore patterns

## License

Custom tools for personal/team use. Modify as needed.
