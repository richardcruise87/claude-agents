#!/bin/bash
# Setup script for systemd timers for Claude Agents
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
VENV_DIR="${VENV_DIR:-$HOME/.venv/claude-agents}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo "=============================================="
echo "  Claude Agents - Systemd Setup"
echo "=============================================="
echo ""

# Step 1: Create virtual environment
echo -e "${BLUE}Step 1: Creating virtual environment${NC}"
if [ -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}⚠${NC} Virtual environment already exists at $VENV_DIR"
    echo -n "Recreate it? (y/n) "
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        rm -rf "$VENV_DIR"
        python3 -m venv "$VENV_DIR"
        echo -e "${GREEN}✓${NC} Virtual environment created"
    else
        echo -e "${GREEN}✓${NC} Using existing virtual environment"
    fi
else
    python3 -m venv "$VENV_DIR"
    echo -e "${GREEN}✓${NC} Virtual environment created at $VENV_DIR"
fi

# Step 2: Install packages
echo ""
echo -e "${BLUE}Step 2: Installing packages${NC}"
source "$VENV_DIR/bin/activate"

echo "Installing agents_lib..."
pip install -q -e "$REPO_DIR/agents_lib/"
echo -e "${GREEN}✓${NC} agents_lib installed"

echo "Installing bug-triage-agent..."
pip install -q -e "$REPO_DIR/bug-triage-agent/"
echo -e "${GREEN}✓${NC} bug-triage-agent installed"

echo "Installing code-review-agent..."
pip install -q -e "$REPO_DIR/code-review-agent/"
echo -e "${GREEN}✓${NC} code-review-agent installed"

echo "Installing bug-reproduction-agent..."
pip install -q -e "$REPO_DIR/bug-reproduction-agent/"
echo -e "${GREEN}✓${NC} bug-reproduction-agent installed"

echo "Installing ci-failure-agent..."
pip install -q -e "$REPO_DIR/ci-failure-agent/"
echo -e "${GREEN}✓${NC} ci-failure-agent installed"

deactivate

# Step 3: Check configuration files
echo ""
echo -e "${BLUE}Step 3: Checking configuration files${NC}"

for agent_dir in "bug-triage-agent" "code-review-agent" "bug-reproduction-agent" "ci-failure-agent"; do
    config_file="$REPO_DIR/$agent_dir/config.json"
    sample_file="$REPO_DIR/$agent_dir/config.sample.json"

    if [ ! -f "$config_file" ]; then
        echo -e "${YELLOW}⚠${NC} $agent_dir/config.json not found"
        if [ -f "$sample_file" ]; then
            echo -n "  Create from config.sample.json? (y/n) "
            read -r response
            if [[ "$response" =~ ^[Yy]$ ]]; then
                cp "$sample_file" "$config_file"
                echo -e "${GREEN}✓${NC} Created $agent_dir/config.json"
                echo -e "${YELLOW}⚠${NC} Please edit $config_file before starting services"
            fi
        fi
    else
        echo -e "${GREEN}✓${NC} $agent_dir/config.json exists"
    fi
done

# Step 4: Create systemd user directory
echo ""
echo -e "${BLUE}Step 4: Setting up systemd user services${NC}"
SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
mkdir -p "$SYSTEMD_USER_DIR"
echo -e "${GREEN}✓${NC} Created $SYSTEMD_USER_DIR"

# Step 5: Update service files with actual paths
echo ""
echo -e "${BLUE}Step 5: Installing systemd service and timer files${NC}"

for service_file in octavia-bug-triage.service octavia-code-review.service octavia-bug-reproduction.service octavia-ci-failure.service; do
    # Copy and update paths
    sed "s|%h|$HOME|g; s|%u|$USER|g" \
        "$SCRIPT_DIR/$service_file" > "$SYSTEMD_USER_DIR/$service_file"
    echo -e "${GREEN}✓${NC} Installed $service_file"
done

for timer_file in octavia-bug-triage.timer octavia-code-review.timer octavia-ci-failure.timer; do
    cp "$SCRIPT_DIR/$timer_file" "$SYSTEMD_USER_DIR/$timer_file"
    echo -e "${GREEN}✓${NC} Installed $timer_file"
done

for path_file in octavia-bug-reproduction.path; do
    sed "s|%h|$HOME|g; s|%u|$USER|g" \
        "$SCRIPT_DIR/$path_file" > "$SYSTEMD_USER_DIR/$path_file"
    echo -e "${GREEN}✓${NC} Installed $path_file"
done

# Step 6: Reload systemd
echo ""
echo -e "${BLUE}Step 6: Reloading systemd user daemon${NC}"
systemctl --user daemon-reload
echo -e "${GREEN}✓${NC} Systemd reloaded"

# Step 7: Instructions
echo ""
echo "=============================================="
echo -e "${GREEN}✓ Setup complete!${NC}"
echo "=============================================="
echo ""
echo "Next steps:"
echo ""
echo "1. Edit configuration files (if needed):"
echo "   - $REPO_DIR/bug-triage-agent/config.json"
echo "   - $REPO_DIR/code-review-agent/config.json"
echo "   - $REPO_DIR/bug-reproduction-agent/config.json"
echo ""
echo "2. Enable and start timers:"
echo "   ${BLUE}systemctl --user enable octavia-bug-triage.timer${NC}"
echo "   ${BLUE}systemctl --user start octavia-bug-triage.timer${NC}"
echo ""
echo "   ${BLUE}systemctl --user enable octavia-code-review.timer${NC}"
echo "   ${BLUE}systemctl --user start octavia-code-review.timer${NC}"
echo ""
echo "3. Enable and start bug reproduction path watcher:"
echo "   ${BLUE}systemctl --user enable octavia-bug-reproduction.path${NC}"
echo "   ${BLUE}systemctl --user start octavia-bug-reproduction.path${NC}"
echo ""
echo "   ${BLUE}systemctl --user enable octavia-ci-failure.timer${NC}"
echo "   ${BLUE}systemctl --user start octavia-ci-failure.timer${NC}"
echo ""
echo "4. Check timer/path status:"
echo "   ${BLUE}systemctl --user list-timers${NC}"
echo "   ${BLUE}systemctl --user status octavia-bug-reproduction.path${NC}"
echo ""
echo "5. Run services manually (for testing):"
echo "   ${BLUE}systemctl --user start octavia-bug-triage.service${NC}"
echo "   ${BLUE}systemctl --user start octavia-code-review.service${NC}"
echo "   ${BLUE}systemctl --user start octavia-bug-reproduction.service${NC}"
echo "   ${BLUE}systemctl --user start octavia-ci-failure.service${NC}"
echo ""
echo "6. View logs:"
echo "   ${BLUE}journalctl --user -u octavia-bug-triage.service -f${NC}"
echo "   ${BLUE}journalctl --user -u octavia-code-review.service -f${NC}"
echo "   ${BLUE}journalctl --user -u octavia-bug-reproduction.service -f${NC}"
echo "   ${BLUE}journalctl --user -u octavia-ci-failure.service -f${NC}"
echo ""
echo "6. Enable user services to start at boot:"
echo "   ${BLUE}loginctl enable-linger $USER${NC}"
echo ""
echo "=============================================="
