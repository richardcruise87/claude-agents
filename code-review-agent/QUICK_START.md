# Quick Start Guide - Octavia Code Review Agent

## ✅ Setup Status
Your agent is ready! All prerequisites are configured:
- ✅ Claude Agent SDK installed
- ✅ Vertex AI configured and working
- ✅ DevStack found with Octavia repos
- ✅ Output directory created

## 🚀 How to Use

### Option 1: Review a Specific Change (Recommended to Start)

```bash
# Review latest patchset
./review_single_change.py 912345

# Review specific patchset (e.g., patchset 2)
./review_single_change.py 912345 2

# Using URL (latest)
./review_single_change.py https://review.opendev.org/c/openstack/octavia/+/912345

# Using URL (specific patchset)
./review_single_change.py https://review.opendev.org/c/openstack/octavia/+/912345 3

# Alternative syntax
./review_single_change.py 912345 --patchset 2
```

**What happens:**
1. Agent fetches the change from OpenDev
2. Downloads it to your local repo
3. Runs unit tests (`tox -e py3`)
4. Runs functional tests (`tox -e functional`)
5. Runs style checks (`tox -e pep8`)
6. Analyzes all code changes
7. Generates a comprehensive review document
8. Saves to: `~/octavia_reviews/review_*.md`

**Time:** 5-15 minutes depending on test suite size

---

### Option 2: Monitor All Repos for New Changes

```bash
./octavia_review_agent.py
```

**What happens:**
1. Checks all configured Octavia repos:
   - openstack/octavia
   - openstack/octavia-lib
   - openstack/octavia-tempest-plugin
   - openstack/python-octaviaclient
2. Reviews up to 3 new changes per repo
3. Tracks reviewed changes (won't review the same change twice)
4. Saves all reviews to `~/octavia_reviews/`

**Time:** Depends on how many new changes are found

---

### Option 3: Automated Monitoring (Cron)

Set up hourly monitoring:

```bash
# Edit crontab
crontab -e

# Add this line (runs every hour at :00)
0 * * * * /usr/bin/python3 /home/rcruise/git/claude-agents/code-review-agent/octavia_review_agent.py >> /home/rcruise/octavia_reviews.log 2>&1
```

Or every 4 hours:
```bash
0 */4 * * * /usr/bin/python3 /home/rcruise/octavia_review_agent.py >> /home/rcruise/octavia_reviews.log 2>&1
```

---

## 📋 Example Workflow

### Scenario: A team member posts a new change

1. **You get notified**: "Please review change #923456 in openstack/octavia"

2. **Run the agent**:
   ```bash
   ./review_single_change.py 923456
   ```

3. **Agent works** (you'll see live progress):
   ```
   🔍 Looking up change 923456...
   📋 Change Details:
     Repository: openstack/octavia
     Change Number: 923456
     URL: https://review.opendev.org/c/openstack/octavia/+/923456

   🤖 Starting comprehensive code review...
     Fetching change from Gerrit...
     Running git diff to analyze changes...
     Running unit tests...
     Running functional tests...
     Analyzing code quality...
     Generating review document...

   ✅ Review Complete!
   📄 Review Document: ~/octavia_reviews/review_openstack_octavia_923456_20260326_153045.md
   ```

4. **Read the review**:
   ```bash
   cat ~/octavia_reviews/review_openstack_octavia_923456_20260326_153045.md
   ```

5. **The review includes**:
   - ✅ Test results (unit, functional, pep8)
   - 🔍 Detailed code analysis
   - 🐛 Issues found (categorized by severity)
   - 💡 Specific recommendations with line numbers
   - 📝 Testing strategy
   - ⚖️ Final verdict (Approve/Request Changes/Needs Discussion)

6. **Post your review**: Use the agent's insights to write your Gerrit review

---

## 📄 Review Document Contents

Each review includes:

### 1. Change Summary
- What changed, why, and how many lines
- Commit message analysis

### 2. Test Results
```
Unit Tests: ✅ PASS (45 passed, 0 failed)
Functional Tests: ✅ PASS (12 passed, 0 failed)
PEP8: ✅ PASS (no violations)
```

### 3. Code Analysis
```
Issues Found:

Critical Issues 🔴
1. File: octavia/controller/worker/v2/flows.py:234
   Issue: Potential SQL injection vulnerability
   Impact: User input not sanitized before database query
   Suggestion: Use parameterized queries

Major Issues 🟡
1. File: octavia/api/v2/controllers/load_balancer.py:145
   Issue: Missing error handling for network timeout
   Suggestion: Add try/except for requests.Timeout

Minor Issues 🔵
1. File: octavia/common/utils.py:89
   Issue: Function complexity too high (12 branches)
   Suggestion: Consider refactoring into smaller functions
```

### 4. Testing Strategy
- What was tested
- What else should be tested
- Manual testing steps

### 5. Final Verdict
```
Recommendation: 🔄 Request Changes

Required fixes:
- Fix SQL injection vulnerability (Critical)
- Add error handling for network calls (Major)

Suggested improvements:
- Refactor complex function (Minor)

Overall: Good approach but needs security fix before merge.
```

---

## 🔧 Customization

### Review Specific Files Only

Edit the prompt in `review_single_change.py` to focus on certain files:

```python
# Add to the prompt:
Focus your analysis on changes to:
- octavia/api/**/*.py
- octavia/controller/**/*.py

Skip test files and configuration files.
```

### Change Test Commands

If your setup uses different test commands:

```python
# In the Python scripts, change:
tox -e py3          # to: python -m pytest
tox -e functional   # to: ./run_functional_tests.sh
tox -e pep8        # to: flake8 .
```

### Filter Changes by Author

In `octavia_review_agent.py`, modify the Gerrit query:

```python
gerrit_query_url = (
    f"{CONFIG['gerrit_base_url']}/changes/"
    f"?q=project:{repo_name}+status:open+owner:jane@example.com"
)
```

---

## 🎯 Use Cases

### 1. Daily Review Workflow
```bash
# Morning: Check what's new
./octavia_review_agent.py

# Read the reviews
ls -lt ~/octavia_reviews/ | head -5
cat ~/octavia_reviews/review_*.md

# Post reviews on Gerrit
```

### 2. Pre-Review Analysis
```bash
# Before reviewing a large change, get AI insights
./review_single_change.py 923456

# Read the analysis
# Use it to inform your human review
```

### 3. Test Validation
```bash
# Run automated tests on a change before approving
./review_single_change.py 923456

# Check test results in the review document
# Approve with confidence
```

### 4. Learning Tool
```bash
# New to the codebase? Review recent changes to learn
./review_single_change.py 923456

# The agent explains what the code does
# Points out patterns and best practices
```

---

## 📊 Example Commands

```bash
# List all reviews
ls -lh ~/octavia_reviews/

# Count reviews
ls ~/octavia_reviews/*.md | wc -l

# Find reviews with critical issues
grep -l "Critical Issues" ~/octavia_reviews/*.md

# Find all approve recommendations
grep -l "Recommend.*Approve" ~/octavia_reviews/*.md

# Search for security issues
grep -r "security\|vulnerability\|injection" ~/octavia_reviews/

# Get a specific review
cat ~/octavia_reviews/review_openstack_octavia_923456_*.md | less
```

---

## 🐛 Troubleshooting

### "Repository not found"
```bash
# Check DevStack path
ls -la /opt/stack/octavia

# Update path if needed - edit scripts and change:
DEVSTACK_PATH = "/your/actual/path"
```

### "Tests failed"
- This is normal - it means the change has test failures
- The review will document what failed
- Use this info in your Gerrit review

### "Agent is slow"
- Tests can take 5-15 minutes
- You'll see progress updates
- Functional tests are especially slow

### "Git fetch failed"
```bash
# Check network connectivity
curl https://review.opendev.org

# Try manual fetch
cd /opt/stack/octavia
git fetch https://review.opendev.org/openstack/octavia refs/changes/56/923456/1
```

---

## 💡 Tips

1. **Start small**: Review a single recent change first
2. **Read the output**: The review documents are comprehensive
3. **Don't auto-post**: Always review the agent's analysis before posting to Gerrit
4. **Customize prompts**: Adjust the analysis to your team's standards
5. **Track costs**: Each review uses ~50k-100k tokens on Vertex AI
6. **Use filters**: Focus on changes you care about

---

## 🎓 What the Agent Does Well

✅ **Finds common bugs**: SQL injection, XSS, race conditions
✅ **Checks style**: PEP8, naming, formatting
✅ **Runs tests**: Unit, functional, integration
✅ **Analyzes complexity**: Flags overly complex functions
✅ **Reviews documentation**: Docstrings, comments, commit messages
✅ **Suggests improvements**: Specific, actionable recommendations

## ⚠️ What to Double-Check

⚠️ **Architectural decisions**: AI may not understand system design choices
⚠️ **Business logic**: Domain-specific requirements need human judgment
⚠️ **API contracts**: Breaking changes require human review
⚠️ **Performance**: AI estimates, not benchmarks
⚠️ **Security**: Critical vulns should be verified by humans

---

## 📞 Next Steps

Ready to start? Try this:

```bash
# 1. Run setup check
./setup_review_agent.sh

# 2. Review a recent change (pick any open change from OpenDev)
./review_single_change.py <change_number>

# 3. Read the review document
cat ~/octavia_reviews/review_*.md | less

# 4. See how it works? Set up monitoring!
./octavia_review_agent.py
```

---

**Happy Reviewing! 🚀**

Questions? Check `OCTAVIA_REVIEW_README.md` for full documentation.
