#!/bin/bash
# Initial setup script for Octavia Review Agent
# Run this after cloning the repository

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=============================================="
echo "  Octavia Code Review Agent - Installation"
echo "=============================================="
echo ""

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check Python
echo -n "Checking Python 3.8+... "
if command -v python3 &>/dev/null; then
    python_version=$(python3 --version 2>&1 | awk '{print $2}')
    echo -e "${GREEN}✓${NC} Python $python_version"
else
    echo -e "${RED}✗${NC} Python 3 not found"
    echo "Please install Python 3.8 or later"
    exit 1
fi

# Check pip
echo -n "Checking pip... "
if command -v pip3 &>/dev/null || command -v pip &>/dev/null; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${RED}✗${NC}"
    echo "Please install pip"
    exit 1
fi

# Install Claude Agent SDK
echo -e "\n${BLUE}Installing dependencies...${NC}"
echo -n "Installing Claude Agent SDK... "
if pip3 install --user claude-agent-sdk &>/dev/null || pip install --user claude-agent-sdk &>/dev/null; then
    echo -e "${GREEN}✓${NC}"
else
    echo -e "${YELLOW}⚠${NC} Already installed or failed"
fi

# Create config.json from sample
echo ""
if [[ ! -f "config.json" ]]; then
    echo -e "${BLUE}Creating configuration file...${NC}"
    cp config.sample.json config.json
    echo -e "${GREEN}✓${NC} Created config.json from config.sample.json"
    echo ""
    echo -e "${YELLOW}IMPORTANT: Edit config.json to match your environment!${NC}"
    echo ""
    echo "Key settings to update:"
    echo "  - devstack.path: Path to your DevStack installation"
    echo "  - output.reviews_directory: Where to save reviews"
    echo "  - repositories: Which repos to monitor"
else
    echo -e "${GREEN}✓${NC} config.json already exists"
fi

# Prompt for configuration
echo ""
echo -e "${BLUE}Configuration Setup${NC}"
echo "Would you like to configure basic settings now? (y/n)"
read -r response

if [[ "$response" =~ ^[Yy]$ ]]; then
    # Read DevStack path
    echo ""
    echo -n "Enter DevStack installation path [/opt/stack]: "
    read -r devstack_path
    devstack_path=${devstack_path:-/opt/stack}

    # Read output directory
    echo -n "Enter reviews output directory [~/octavia_reviews]: "
    read -r output_dir
    output_dir=${output_dir:-~/octavia_reviews}

    # Update config.json
    python3 << EOF
import json
with open('config.json', 'r') as f:
    config = json.load(f)
config['devstack']['path'] = '$devstack_path'
config['output']['reviews_directory'] = '$output_dir'
with open('config.json', 'w') as f:
    json.dump(config, f, indent=2)
print('Configuration updated!')
EOF

    echo -e "${GREEN}✓${NC} Configuration saved"
fi

# Create output directory
echo ""
output_dir=$(python3 -c "from config import load_config; print(load_config()['reviews_output_dir'])")
if [[ ! -d "$output_dir" ]]; then
    echo -n "Creating output directory... "
    mkdir -p "$output_dir" 2>/dev/null && echo -e "${GREEN}✓${NC}" || echo -e "${YELLOW}⚠${NC} (will be created on first run)"
fi

# Vertex AI setup
echo ""
echo -e "${BLUE}Vertex AI Setup${NC}"
echo ""
echo "This agent requires Google Cloud Vertex AI access."
echo ""
echo "Setup steps:"
echo "  1. Set environment variable:"
echo "     export CLAUDE_CODE_USE_VERTEX=1"
echo ""
echo "  2. Configure Google Cloud credentials (choose one):"
echo "     a) Application default credentials:"
echo "        gcloud auth application-default login"
echo ""
echo "     b) Service account:"
echo "        export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json"
echo ""
echo "  3. Add to your ~/.bashrc or ~/.zshrc to persist:"
echo "     export CLAUDE_CODE_USE_VERTEX=1"
echo ""

# Check if Vertex AI is configured
if [[ "$CLAUDE_CODE_USE_VERTEX" == "1" ]]; then
    echo -e "${GREEN}✓${NC} CLAUDE_CODE_USE_VERTEX is set"
else
    echo -e "${YELLOW}⚠${NC} CLAUDE_CODE_USE_VERTEX not set"
    echo ""
    echo "Set it now for this session? (y/n)"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        export CLAUDE_CODE_USE_VERTEX=1
        echo -e "${GREEN}✓${NC} Set for current session"
        echo -e "${YELLOW}Note:${NC} Add 'export CLAUDE_CODE_USE_VERTEX=1' to ~/.bashrc to persist"
    fi
fi

# Make scripts executable
echo ""
echo -n "Making scripts executable... "
chmod +x *.py *.sh 2>/dev/null
echo -e "${GREEN}✓${NC}"

# Run verification
echo ""
echo "=============================================="
echo ""
echo "Installation complete!"
echo ""
echo "Next steps:"
echo "  1. Edit config.json if you haven't already"
echo "  2. Run setup verification:"
echo "     ./setup_review_agent.sh"
echo ""
echo "  3. Try reviewing a change:"
echo "     ./review_single_change.py <change_number>"
echo ""
echo "=============================================="
