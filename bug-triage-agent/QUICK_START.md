# Quick Start - Bug Triage Agent

Get started with the Octavia Bug Triage Agent in 5 minutes!

## Prerequisites Check

```bash
# 1. Check Python version (need 3.8+)
python3 --version

# 2. Check Vertex AI setup
echo $CLAUDE_CODE_USE_VERTEX  # Should be "1"

# 3. Check gcloud authentication
gcloud auth list
```

## Setup

### 1. Install Dependencies
```bash
pip install claude-agent-sdk httpx
```

### 2. Create Configuration
```bash
cd /home/rcruise/git/claude-agents/bug-triage-agent
cp config.sample.json config.json

# Edit config.json if needed (optional)
# Default settings work for standard DevStack setup
```

### 3. Create Output Directory
```bash
mkdir -p ~/octavia_bug_triages
```

## Run Your First Triage

```bash
./bug_triage_agent.py
```

**What happens:**
1. Fetches recent bugs from Launchpad
2. Checks which bugs need triaging
3. Performs AI analysis on new/updated bugs
4. Saves triage reports to `~/octavia_bug_triages/`

**Time:** 5-10 minutes for 5 bugs

## View Results

```bash
# List triage reports
ls -lt ~/octavia_bug_triages/

# Read latest triage
cat ~/octavia_bug_triages/bug_*.md | less

# Count triages
ls ~/octavia_bug_triages/*.md | wc -l
```

## Example Output

```bash
$ ./bug_triage_agent.py

🚀 Bug Triage Agent Starting...
📁 Output directory: /home/rcruise/octavia_bug_triages
🐛 Project: octavia

🔍 Fetching bugs from Launchpad for octavia...
✓ Found 15 bugs
  - Bug #2070819: Octavia fails to create load balancer...
  - Bug #2070516: Amphora not responding to health checks...
  - Bug #2069234: API returns 500 error on pool creation...

📌 Bug #2070819: Octavia fails to create load balancer
   Status: New | Importance: High | Sequence: 1

🤖 Starting bug triage analysis...
  Analyzing bug report...
  Checking for duplicates...
  Searching for related fixes...
  Creating reproduction strategy...
  Generating triage report...

✅ Triage Complete!
📄 Triage saved to: bug_2070819_octavia_fails_to_create_load_balancer_20260330_143052_1.md

✅ Completed 5 triages for octavia
📊 Triages saved to: /home/rcruise/octavia_bug_triages
```

## Triage Report Contents

Each report includes:

### 1. Bug Summary
```markdown
- **Status**: Valid Bug
- **Severity**: High
- **Affected Components**: API, Controller
```

### 2. Duplicate Check
```markdown
Potential duplicates:
- Bug #2070500 - Similar symptoms with LB creation
- Bug #2069100 - Related to API validation
```

### 3. Fix Status
```markdown
**Already Fixed**: Possibly
**Related Commits**:
- abc123 - "Fix LB creation race condition" (2 weeks ago)
```

### 4. Reproduction Steps
```markdown
### Prerequisites
- DevStack with Octavia enabled

### Steps
1. source /opt/stack/devstack/openrc admin admin
2. openstack loadbalancer create --name test-lb --vip-subnet-id private-subnet
3. [commands to trigger bug]
```

### 5. Investigation Guide
```markdown
**Files to examine:**
- octavia/api/v2/controllers/load_balancer.py:123
- octavia/controller/worker/v2/flows/load_balancer_flows.py:456

**Logs to check:**
- /var/log/octavia/octavia-api.log
- /var/log/octavia/octavia-worker.log
```

### 6. Fix Recommendations
```markdown
**Suggested approach:**
- Add validation in API layer
- Update worker flow to handle edge case

**Testing:**
- Unit test for validation
- Functional test for creation flow
```

## Re-Running

### Second Run (Same Day)
```bash
$ ./bug_triage_agent.py

⏭️  Skipping Bug #2070819 - No updates since last triage
⏭️  Skipping Bug #2070516 - No updates since last triage

📌 Bug #2069234: API returns 500 error (NEW)
   Sequence: 1
[performs triage...]
```

### After Bug Update
If someone updates bug #2070819 with new info:

```bash
$ ./bug_triage_agent.py

📌 Bug #2070819: Octavia fails to create load balancer
   Status: Confirmed | Importance: High | Sequence: 2
   [Bug updated with stack trace]

🤖 Starting bug triage analysis...
  Checking changes since last triage...
  Previous triage found: sequence #1
  [re-analyzes with new information...]

✅ Triage Complete!
📄 Triage saved to: bug_2070819_octavia_fails_to_create_load_balancer_20260330_160000_2.md
```

**Result**: Two triage files for the same bug:
- `..._1.md` - Initial triage
- `..._2.md` - Updated triage with new info

## Configuration Options

### Customize Output Location
```bash
export TRIAGES_OUTPUT_DIR=~/my-custom-triages
./bug_triage_agent.py
```

### Limit Number of Bugs
```bash
export MAX_BUGS=10
./bug_triage_agent.py
```

### Change Project
Edit `config.json`:
```json
{
  "launchpad_project": "neutron"
}
```

## Automation

### Run Every 6 Hours
```bash
crontab -e

# Add this line:
0 */6 * * * cd /home/rcruise/git/claude-agents/bug-triage-agent && ./bug_triage_agent.py >> ~/triage.log 2>&1
```

### Run Daily at 9 AM
```bash
0 9 * * * cd /home/rcruise/git/claude-agents/bug-triage-agent && ./bug_triage_agent.py >> ~/triage.log 2>&1
```

## Troubleshooting

### Issue: "httpx not available"
```bash
pip install httpx
```

### Issue: "DevStack path not found"
```bash
# Edit config.json
{
  "devstack_path": "/path/to/your/devstack"
}
```

### Issue: "Vertex AI authentication failed"
```bash
export CLAUDE_CODE_USE_VERTEX=1
gcloud auth application-default login
```

### Issue: "No bugs found"
This is normal! It means no bugs match your filter criteria, or all bugs have been triaged.

## Next Steps

1. **Read triage reports**: Review the AI analysis
2. **Update Launchpad**: Add triage findings to bugs
3. **Prioritize fixes**: Use triage recommendations
4. **Automate**: Set up cron job for regular monitoring
5. **Customize**: Edit `prompts/bug_triage_prompt.txt` for your needs

## Tips

✅ **Start small**: Run with `max_bugs_per_run: 3` first
✅ **Review output**: Check triage quality before relying on it
✅ **Customize prompts**: Edit template to match your workflow
✅ **Track sequences**: Use sequence numbers to see bug evolution
✅ **Share triages**: Triage reports are markdown - easy to share!

---

**Happy Triaging! 🐛**
