# Octavia Bug Triage Agent

AI-powered bug triage agent for OpenStack Octavia. Monitors Launchpad for bugs, performs intelligent triage, suggests reproduction strategies, and checks for duplicates and potential fixes.

## Features

✅ **Automated Monitoring**: Fetches bugs from Launchpad API
✅ **Intelligent Triage**: Uses Claude AI (via Vertex AI) to analyze bugs
✅ **Duplicate Detection**: Searches for similar bugs
✅ **Fix Verification**: Checks if bugs are already fixed in recent commits
✅ **Reproduction Strategy**: Creates detailed DevStack reproduction steps
✅ **Sequence Tracking**: Tracks multiple triages of the same bug
✅ **Smart Skipping**: Only re-triages bugs that have been updated
✅ **Configurable**: Portable configuration for different environments

## Prerequisites

- Python 3.8+
- Claude Agent SDK (with Vertex AI support)
- Vertex AI authentication configured
- DevStack installation (optional, for code analysis)
- httpx library (recommended, falls back to urllib)

## Installation

1. **Clone the repository**:
```bash
cd /home/rcruise/git/claude-agents/bug-triage-agent
```

2. **Install dependencies**:
```bash
pip install claude-agent-sdk httpx
```

3. **Configure Vertex AI**:
```bash
export CLAUDE_CODE_USE_VERTEX=1
# Ensure gcloud is authenticated
```

4. **Create configuration**:
```bash
cp config.sample.json config.json
# Edit config.json with your settings
```

## Configuration

### config.json

```json
{
  "launchpad_project": "octavia",
  "triages_output_dir": "~/octavia_bug_triages",
  "devstack_path": "/opt/stack",
  "max_bugs_per_run": 5,
  "bug_statuses": ["New", "Confirmed", "Triaged", "In Progress"],
  "bug_importance": ["Critical", "High", "Medium", "Low", "Undecided"],
  "triage_tracking_file": "~/.octavia_bug_triages.json"
}
```

### Environment Variables

Override config settings with environment variables:

- `TRIAGES_OUTPUT_DIR`: Output directory for triages
- `DEVSTACK_PATH`: Path to DevStack installation
- `LAUNCHPAD_PROJECT`: Launchpad project name
- `MAX_BUGS`: Maximum bugs to triage per run

## Usage

### Basic Usage

```bash
./bug_triage_agent.py
```

This will:
1. Fetch bugs from Launchpad for the configured project
2. Check which bugs need triaging
3. Perform AI-powered triage on new/updated bugs
4. Save triage reports to the output directory

### Output Files

Triage files are saved with the format:
```
bug_<number>_<title-slug>_<timestamp>_<sequence>.md
```

Examples:
```
bug_1234567_load_balancer_fails_to_start_20260330_143000_1.md
bug_1234567_load_balancer_fails_to_start_20260330_150000_2.md
bug_7654321_amphora_not_responding_20260330_143100_1.md
```

**Sequence numbers**:
- `_1.md`: Initial triage
- `_2.md`: Second triage (after bug update)
- `_3.md`: Third triage (after another update)
- etc.

## How It Works

### 1. Bug Fetching
- Connects to Launchpad API
- Fetches bugs matching configured statuses
- Retrieves bug details, descriptions, and metadata

### 2. Triage Decision
- Checks tracking file for previous triages
- Compares bug's `last_updated` timestamp
- Only triages if:
  - Bug never triaged before (sequence 1)
  - Bug updated since last triage (sequence+1)

### 3. AI-Powered Analysis
The agent performs:
- **Validation**: Is this a real bug or configuration issue?
- **Duplicate Check**: Search for similar bugs
- **Fix Verification**: Check if already fixed in recent commits
- **Component Analysis**: Identify affected Octavia components
- **Severity Assessment**: Evaluate impact and priority
- **Reproduction Strategy**: Create detailed DevStack steps
- **Investigation Guide**: Suggest files and logs to examine
- **Fix Proposal**: Recommend approaches to fix the bug

### 4. Output Generation
Creates comprehensive triage report with:
- Bug summary and validation status
- Duplicate bugs found
- Potential existing fixes
- DevStack reproduction steps
- Investigation areas
- Fix strategy recommendations
- Priority and next steps

## Triage Report Structure

Each triage report includes:

```markdown
# Bug Triage: #1234567 - Load Balancer Fails to Start

## Bug Summary
- **Status**: Valid Bug
- **Severity**: High
- **Affected Components**: Controller, Database

## Duplicate Check
- Potential duplicates: #1234560, #1234550

## Fix Status
- **Already Fixed**: Possibly
- **Related Commit**: abc123def - "Fix LB initialization race condition"

## Reproduction Strategy
### Prerequisites
- DevStack with Octavia enabled
- ...

### Steps
1. Create load balancer...
2. Trigger the bug...

## Investigation Guide
- Files to examine: octavia/controller/worker/v2/...
- Logs to check: /var/log/octavia/...

## Fix Proposal
- Suggested approach: Add synchronization to...
- Testing: Verify with load test...

## Priority Recommendation
- **Priority**: High
- **Justification**: Affects production deployments
```

## Tracking

The agent maintains a tracking file (default: `~/.octavia_bug_triages.json`) with:

```json
{
  "bug_1234567": {
    "last_triaged": "2026-03-30T14:30:00",
    "last_updated": "2026-03-30T14:00:00",
    "sequence": 2
  }
}
```

This ensures:
- Bugs aren't re-triaged unnecessarily
- Sequence numbers are correctly incremented
- Only updated bugs are re-analyzed

## Examples

### Example 1: First Run
```bash
$ ./bug_triage_agent.py

🚀 Bug Triage Agent Starting...
📁 Output directory: /home/user/octavia_bug_triages
🐛 Project: octavia

🔍 Fetching bugs from Launchpad for octavia...
✓ Found 15 bugs

📌 Bug #1234567: Load balancer fails to start
   Status: New | Importance: High | Sequence: 1

🤖 Starting bug triage analysis...
[triage process...]
✅ Triage Complete!
📄 Triage saved to: bug_1234567_load_balancer_fails_to_start_20260330_143000_1.md

✅ Completed 5 triages for octavia
```

### Example 2: Re-Run (Bug Updated)
```bash
$ ./bug_triage_agent.py

🔍 Fetching bugs from Launchpad for octavia...
✓ Found 15 bugs

⏭️  Skipping Bug #1234568 - No updates since last triage
⏭️  Skipping Bug #1234569 - No updates since last triage

📌 Bug #1234567: Load balancer fails to start
   Status: Confirmed | Importance: High | Sequence: 2
   [Bug was updated with new information]

🤖 Starting bug triage analysis...
[checking changes since last triage...]
✅ Triage Complete!
📄 Triage saved to: bug_1234567_load_balancer_fails_to_start_20260330_150000_2.md
```

## Customization

### Change Prompt Template

Edit `prompts/bug_triage_prompt.txt` to customize the triage analysis steps and output format.

### Add Custom Analysis

The prompt template supports adding custom analysis steps. Edit the template to include:
- Security impact analysis
- Performance impact assessment
- Backward compatibility checks
- Documentation requirements

### Filter Bugs

Modify `config.json` to change which bugs are fetched:

```json
{
  "bug_statuses": ["New", "Confirmed"],  // Only fetch New and Confirmed
  "bug_importance": ["Critical", "High"]  // Only fetch high-priority bugs
}
```

## Integration

### Cron Job
Run automatically every 6 hours:
```bash
0 */6 * * * cd /path/to/bug-triage-agent && ./bug_triage_agent.py >> ~/triage.log 2>&1
```

### Systemd Timer
Create a systemd service for scheduled triaging.

### Manual Workflow
```bash
# Morning: Check for new bugs
./bug_triage_agent.py

# Review triage reports
ls -lt ~/octavia_bug_triages/ | head -10
cat ~/octavia_bug_triages/bug_*.md

# Update Launchpad with triage findings
```

## Troubleshooting

### "httpx not available"
```bash
pip install httpx
```
Or use the fallback urllib (limited functionality).

### "DevStack path not found"
Edit `config.json` and set the correct `devstack_path`, or set `DEVSTACK_PATH` environment variable.

### "Launchpad API timeout"
Increase timeout in `bug_triage_agent.py` or try again later.

### "Vertex AI authentication failed"
```bash
export CLAUDE_CODE_USE_VERTEX=1
gcloud auth application-default login
```

## Architecture

```
bug-triage-agent/
├── bug_triage_agent.py       # Main agent (fetches bugs, orchestrates triage)
├── config.py                  # Configuration loading
├── config.sample.json         # Template configuration
├── bug_tracker.py             # Triage tracking and sequence management
├── prompts/
│   ├── __init__.py           # Prompt template loader
│   └── bug_triage_prompt.txt # Triage prompt template
└── README.md                  # This file
```

**Data Flow**:
1. `bug_triage_agent.py` fetches bugs from Launchpad
2. `bug_tracker.py` checks if triage is needed
3. `prompts/` loads and formats triage prompt
4. Claude Agent SDK performs AI analysis
5. Results saved to output directory
6. `bug_tracker.py` records triage completion

## License

Same as parent repository.

## Contributing

Follow the same patterns as the code review agent:
1. Keep prompts in separate files
2. Make configuration portable
3. Use sequence tracking for versioning
4. Document clearly

## Acknowledgments

Built with:
- Claude Agent SDK
- Google Vertex AI
- OpenStack Launchpad API
- Python asyncio

---

**Happy Triaging! 🐛**
