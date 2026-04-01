# Octavia Code Review Agent

An AI-powered code review agent for OpenStack Octavia projects on OpenDev, using Claude via Google Vertex AI.

## Overview

This agent monitors Octavia repositories on OpenDev for new changes, downloads them to your local DevStack environment, runs comprehensive tests, performs code analysis, and generates detailed review documents.

**What it does:**
- ✅ Monitors OpenDev for new Octavia changes
- ✅ Downloads changes to local DevStack
- ✅ Runs unit tests, functional tests, and linting
- ✅ Performs comprehensive code analysis
- ✅ Generates detailed testing strategies
- ✅ Creates professional code review documents
- ❌ Does NOT post reviews to Gerrit (keeps them local)

## Files

- **`octavia_review_agent.py`** - Main monitoring agent that checks for new changes
- **`review_single_change.py`** - Review a specific change by number or URL
- **`octavia_review_config.json`** - Configuration file
- **`test_agent.py`** - Simple test to verify Vertex AI connectivity

## Prerequisites

1. **Claude Agent SDK installed** ✅ (Already done)
   ```bash
   pip install claude-agent-sdk
   ```

2. **Vertex AI configured** ✅ (Already done)
   ```bash
   export CLAUDE_CODE_USE_VERTEX=1
   ```

3. **Google Cloud credentials set up**
   ```bash
   gcloud auth application-default login
   # OR use a service account
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
   ```

4. **DevStack installed** (Required)
   - Make sure DevStack is installed and Octavia repos are cloned
   - Update `devstack_path` in the configuration to match your setup

5. **Python 3.8+**

## Configuration

Edit `octavia_review_config.json` or modify the CONFIG dictionary in the Python files:

```json
{
  "repositories": [
    "openstack/octavia",
    "openstack/octavia-lib",
    "openstack/octavia-tempest-plugin",
    "openstack/python-octaviaclient"
  ],
  "devstack": {
    "path": "/opt/stack"  // ← Update this to your DevStack location
  },
  "output": {
    "reviews_directory": "~/octavia_reviews"
  }
}
```

**Important settings to update:**
- `devstack.path` - Path to your DevStack installation
- `output.reviews_directory` - Where to save review documents
- `repositories` - Which Octavia repos to monitor

## Usage

### Option 1: Review a Specific Change

The easiest way to get started:

```bash
# Make the script executable
chmod +x review_single_change.py

# Review by change number
./review_single_change.py 912345

# Or by full URL
./review_single_change.py https://review.opendev.org/c/openstack/octavia/+/912345
```

This will:
1. Fetch the change details from OpenDev
2. Download the change to your local repo
3. Run all tests (unit, functional, pep8)
4. Analyze the code comprehensively
5. Generate a detailed review document in `~/octavia_reviews/`

### Option 2: Monitor for New Changes

Run the monitoring agent to check all configured repos:

```bash
chmod +x octavia_review_agent.py
./octavia_review_agent.py
```

This will:
- Check all configured Octavia repositories
- Review up to 3 new changes per repo
- Track reviewed changes to avoid duplicates
- Save all reviews to the output directory

### Option 3: Automated Monitoring with Cron

Set up automatic monitoring every hour:

```bash
# Edit your crontab
crontab -e

# Add this line (runs every hour):
0 * * * * python3 ~/git/claude-agents/code-review-agent/octavia_review_agent.py >> ~/octavia_reviews.log 2>&1
```

Or every 30 minutes:
```bash
*/30 * * * * /usr/bin/python3 ~/octavia_review_agent.py >> ~/octavia_reviews.log 2>&1
```

### Option 4: Run as a Systemd Service

Create `/etc/systemd/system/octavia-review.service`:

```ini
[Unit]
Description=Octavia Code Review Agent
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/home/YOUR_USERNAME/git/claude-agents/code-review-agent
Environment="CLAUDE_CODE_USE_VERTEX=1"
ExecStart=/usr/bin/python3 /home/YOUR_USERNAME/git/claude-agents/code-review-agent/octavia_review_agent.py
Restart=on-failure
RestartSec=3600

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable octavia-review
sudo systemctl start octavia-review
sudo systemctl status octavia-review
```

## Review Document Structure

Each review generates a comprehensive markdown document with:

### 1. Change Summary
- What the change does
- Files modified/added/deleted
- Lines changed
- Commit message analysis

### 2. Test Results
- **Unit Tests**: Full output with pass/fail status
- **Functional Tests**: Results or skip reason
- **Code Quality**: PEP8/Flake8 results

### 3. Code Analysis
- **Overall Assessment**: High-level evaluation
- **Strengths**: What's done well
- **Issues**: Categorized by severity (Critical/Major/Minor/Nit)
  - Critical 🔴: Must fix before merge
  - Major 🟡: Should fix
  - Minor 🔵: Nice to have
  - Nit 🟢: Very minor suggestions

### 4. Testing Strategy
- Tests that were executed
- Recommended additional testing
- Manual test procedures
- Test coverage gaps

### 5. Recommendations
- **Required Changes**: Blocking issues
- **Suggested Improvements**: Non-blocking
- **Questions for Author**: Clarifications needed
- **Nice-to-Haves**: Future enhancements

### 6. Detailed Comments
File-by-file, line-by-line review with:
- Specific line numbers
- Severity levels
- Detailed explanations
- Code suggestions

### 7. Final Verdict
- Overall assessment
- Recommendation (Approve/Request Changes/Needs Discussion)
- Confidence level
- Next steps

## Example Review Workflow

```bash
# 1. Check for new Octavia changes
./octavia_review_agent.py

# 2. Agent finds change #912345 in openstack/octavia

# 3. Agent performs:
#    - git fetch from OpenDev
#    - git checkout FETCH_HEAD
#    - tox -e py3 (unit tests)
#    - tox -e functional (functional tests)
#    - tox -e pep8 (style checks)
#    - Deep code analysis
#    - Review document generation

# 4. Review saved to:
#    ~/octavia_reviews/review_openstack_octavia_912345_20260326_143022.md

# 5. You read the review and decide whether to:
#    - Copy comments to Gerrit manually
#    - Use insights for your own review
#    - Share with team
```

## What the Agent Analyzes

### Code Quality
- PEP 8 compliance
- Naming conventions
- Code organization
- Complexity and readability

### Correctness & Safety
- Logic errors
- Edge case handling
- Error handling and exceptions
- Security vulnerabilities (SQL injection, XSS, etc.)
- Thread safety
- Resource management

### Testing
- Test coverage for changes
- Test quality and meaningfulness
- Missing test scenarios

### Documentation
- Docstrings accuracy
- Code comments
- Commit message quality
- Release notes (if needed)

### OpenStack Specifics
- API compatibility
- Database migrations
- Configuration changes
- Deprecation handling
- Upgrade compatibility

## Tracking Reviewed Changes

The agent maintains a file (`~/.octavia_reviewed_changes.json`) to track which changes have been reviewed. This prevents duplicate reviews.

To reset and review everything again:
```bash
rm ~/.octavia_reviewed_changes.json
```

## Customization

### Adjust Test Commands

Edit the scripts to change how tests are run:

```python
# In review_single_change.py or octavia_review_agent.py
# Change test commands in the prompt:
tox -e py3              # Unit tests
tox -e functional       # Functional tests
tox -e pep8            # Style checks
```

### Filter Changes

Modify the Gerrit query in `fetch_pending_changes()`:

```python
# Only review changes from specific authors
gerrit_query_url = (
    f"{CONFIG['gerrit_base_url']}/changes/"
    f"?q=project:{repo_name}+status:open+owner:john@example.com"
)

# Only review changes with specific topics
gerrit_query_url = (
    f"{CONFIG['gerrit_base_url']}/changes/"
    f"?q=project:{repo_name}+status:open+topic:bug/123456"
)
```

### Customize Review Format

Edit the review document template in the prompt to add/remove sections or change formatting.

## Troubleshooting

### "Repository not found"
- Check that `DEVSTACK_PATH` points to your DevStack installation
- Ensure Octavia repos are cloned: `ls /opt/stack/octavia`

### "Could not fetch change"
- Verify network connectivity to review.opendev.org
- Check that the change number is correct
- Ensure git can access the Gerrit server

### "Tests failed to run"
- Ensure tox is installed: `pip install tox`
- Check that the repo is in a clean state
- Verify Python dependencies are installed

### "Vertex AI authentication error"
- Run: `gcloud auth application-default login`
- Check that `CLAUDE_CODE_USE_VERTEX=1` is set
- Verify your GCP project has Vertex AI enabled

### Agent seems to hang
- Some tests take a long time (especially functional tests)
- The agent will stream progress updates
- You can set timeouts in the Bash commands if needed

## Cost Considerations

Running on Vertex AI incurs costs based on:
- Input tokens (the code, tests, and prompts)
- Output tokens (the review documents)

Each comprehensive review might use:
- ~50,000-100,000 input tokens (large changes with test output)
- ~10,000-20,000 output tokens (detailed review)

**Cost-saving tips:**
- Review fewer changes per cycle (`max_reviews=1`)
- Skip functional tests for minor changes
- Use filters to only review relevant changes
- Run during off-peak hours if you have time-of-use pricing

## Security Note

**The agent does NOT post reviews to Gerrit automatically.**

All reviews are saved locally. You must manually:
- Read the review document
- Decide what to post
- Copy relevant comments to Gerrit yourself

This is intentional to ensure human oversight.

## Advanced Usage

### Review Only Specific Files

Modify the prompt to focus on specific files:

```python
prompt = f"""
Focus your review only on changes to files matching:
- octavia/api/**/*.py
- octavia/controller/**/*.py

Analyze these in detail and skip test files.
"""
```

### Generate Summary Reports

Create a script to summarize multiple reviews:

```bash
# List all reviews
ls -lh ~/octavia_reviews/

# Search for critical issues across all reviews
grep -r "Critical Issues" ~/octavia_reviews/

# Count reviews by verdict
grep -h "Recommendation:" ~/octavia_reviews/*.md | sort | uniq -c
```

### Integration with Gerrit CLI

Combine with Gerrit CLI tools:

```bash
# Get latest changes
git review -l

# Review a specific change
./review_single_change.py 912345

# After reviewing, post your comments
git review -d 912345
# ... make your comments in Gerrit web UI using the agent's analysis
```

## Examples

### Example 1: Daily Review Workflow

```bash
# Morning: Check for new changes overnight
./octavia_review_agent.py

# Review the generated documents
ls -lt ~/octavia_reviews/ | head -5

# Read the latest review
cat ~/octavia_reviews/review_openstack_octavia_912345_*.md

# Post your review to Gerrit (manually)
# Use the agent's insights to write your comments
```

### Example 2: Pre-merge Validation

```bash
# Your team member asks you to review their change
./review_single_change.py https://review.opendev.org/c/openstack/octavia/+/912345

# Agent runs all tests and analysis
# You get a comprehensive report to help your review
# Post your informed review on Gerrit
```

### Example 3: Bulk Analysis

```bash
# Review the last 10 changes to octavia
# (Modify max_reviews in the script)
./octavia_review_agent.py

# Generate a summary
echo "# Review Summary - $(date)" > summary.md
grep -h "## Final Verdict" ~/octavia_reviews/*.md >> summary.md
```

## Future Enhancements

Potential additions (you can implement these):
- Post reviews to Gerrit automatically (with approval)
- Slack/email notifications when reviews are complete
- Dashboard showing review statistics
- Integration with CI/CD pipelines
- Machine learning to learn from your review patterns
- Comparative analysis across patch sets

## Support

This is a custom agent built with Claude Agent SDK. For issues:

1. **Agent SDK issues**: Check the [Claude documentation](https://docs.anthropic.com/)
2. **Vertex AI issues**: Check your GCP console and credentials
3. **DevStack issues**: Check OpenStack DevStack documentation
4. **Script issues**: Review the Python scripts and error messages

## License

This is a custom tool for your use. Modify as needed for your workflow.

---

**Happy Reviewing! 🚀**

*Powered by Claude via Google Vertex AI*
