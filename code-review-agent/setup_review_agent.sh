#!/bin/bash
# Setup and verification script for Octavia Review Agent

echo "=============================================="
echo "  Octavia Code Review Agent - Setup Check"
echo "=============================================="
echo ""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

errors=0

# Check 1: Python version
echo -n "Checking Python version... "
python_version=$(python3 --version 2>&1 | awk '{print $2}')
if [[ $(echo "$python_version" | cut -d. -f1) -ge 3 ]] && [[ $(echo "$python_version" | cut -d. -f2) -ge 8 ]]; then
    echo -e "${GREEN}✓${NC} Python $python_version"
else
    echo -e "${RED}✗${NC} Python 3.8+ required (found $python_version)"
    errors=$((errors+1))
fi

# Check 2: Claude Agent SDK
echo -n "Checking Claude Agent SDK... "
if python3 -c "import claude_agent_sdk" 2>/dev/null; then
    sdk_version=$(python3 -c "import claude_agent_sdk; print(getattr(claude_agent_sdk, '__version__', 'installed'))" 2>/dev/null)
    echo -e "${GREEN}✓${NC} Installed ($sdk_version)"
else
    echo -e "${RED}✗${NC} Not installed"
    echo "  Install with: pip install claude-agent-sdk"
    errors=$((errors+1))
fi

# Check 3: Vertex AI environment variable
echo -n "Checking CLAUDE_CODE_USE_VERTEX... "
if [[ "$CLAUDE_CODE_USE_VERTEX" == "1" ]]; then
    echo -e "${GREEN}✓${NC} Set"
else
    echo -e "${YELLOW}⚠${NC} Not set"
    echo "  Set with: export CLAUDE_CODE_USE_VERTEX=1"
    echo "  Add to ~/.bashrc or ~/.zshrc for persistence"
fi

# Check 4: Google Cloud credentials
echo -n "Checking Google Cloud credentials... "
if [[ -n "$GOOGLE_APPLICATION_CREDENTIALS" ]]; then
    if [[ -f "$GOOGLE_APPLICATION_CREDENTIALS" ]]; then
        echo -e "${GREEN}✓${NC} Service account configured"
    else
        echo -e "${RED}✗${NC} Service account file not found"
        errors=$((errors+1))
    fi
elif gcloud auth application-default print-access-token &>/dev/null; then
    echo -e "${GREEN}✓${NC} Application default credentials configured"
else
    echo -e "${RED}✗${NC} Not configured"
    echo "  Run: gcloud auth application-default login"
    errors=$((errors+1))
fi

# Check 5: DevStack installation
echo -n "Checking DevStack... "
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEVSTACK_PATH=$(python3 -c "import sys; sys.path.insert(0, '$SCRIPT_DIR'); from config import load_config; print(load_config()['devstack_path'])" 2>/dev/null || echo "/opt/stack")
if [[ -d "$DEVSTACK_PATH" ]]; then
    echo -e "${GREEN}✓${NC} Found at $DEVSTACK_PATH"
else
    echo -e "${YELLOW}⚠${NC} Not found at $DEVSTACK_PATH"
    echo "  Update 'devstack.path' in config.json"
fi

# Check 6: Octavia repositories
echo "Checking Octavia repositories:"
repos=("octavia" "octavia-lib" "python-octaviaclient" "octavia-tempest-plugin")
for repo in "${repos[@]}"; do
    echo -n "  - $repo... "
    if [[ -d "$DEVSTACK_PATH/$repo" ]]; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${YELLOW}⚠${NC} Not found"
    fi
done

# Check 7: Output directory
echo -n "Checking output directory... "
OUTPUT_DIR=$(python3 -c "import sys; sys.path.insert(0, '$SCRIPT_DIR'); from config import load_config; print(load_config()['reviews_output_dir'])" 2>/dev/null || echo "~/octavia_reviews")
OUTPUT_DIR=$(eval echo "$OUTPUT_DIR")  # Expand ~ and vars
if [[ -d "$OUTPUT_DIR" ]]; then
    echo -e "${GREEN}✓${NC} $OUTPUT_DIR exists"
else
    echo -n "Creating $OUTPUT_DIR... "
    mkdir -p "$OUTPUT_DIR"
    if [[ $? -eq 0 ]]; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${RED}✗${NC}"
        errors=$((errors+1))
    fi
fi

# Check 8: Required tools
echo "Checking required tools:"
tools=("git" "tox")
for tool in "${tools[@]}"; do
    echo -n "  - $tool... "
    if command -v $tool &>/dev/null; then
        echo -e "${GREEN}✓${NC}"
    else
        echo -e "${YELLOW}⚠${NC} Not found (may be needed for testing)"
    fi
done

# Check 9: Test Vertex AI connection
echo ""
echo "Testing Vertex AI connection..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if python3 "$SCRIPT_DIR/test_agent.py" 2>&1 | grep -q "✓ Vertex AI API is working"; then
    echo -e "${GREEN}✓${NC} Vertex AI connection successful"
else
    echo -e "${RED}✗${NC} Vertex AI connection failed"
    echo "  Check your Google Cloud credentials and Vertex AI API access"
    errors=$((errors+1))
fi

# Summary
echo ""
echo "=============================================="
if [[ $errors -eq 0 ]]; then
    echo -e "${GREEN}✓ Setup complete! All checks passed.${NC}"
    echo ""
    echo "You're ready to use the Octavia Review Agent!"
    echo ""
    echo "Quick start:"
    echo "  1. Review a specific change:"
    echo "     ./review_single_change.py 912345"
    echo ""
    echo "  2. Monitor for new changes:"
    echo "     ./octavia_review_agent.py"
    echo ""
    echo "  3. Read the documentation:"
    echo "     cat OCTAVIA_REVIEW_README.md"
else
    echo -e "${RED}✗ Setup incomplete. Please fix the errors above.${NC}"
    exit 1
fi
echo "=============================================="
