#!/bin/bash
set -e

# Update Claude Agents to Latest Version
# This script updates code, reinstalls packages, and reloads systemd services

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$HOME/.venv/claude-agents"

echo "========================================="
echo "Claude Agents Update Script"
echo "========================================="
echo ""

# Step 1: Pull latest changes from git
echo "📥 Step 1: Pulling latest changes from git..."
cd "$SCRIPT_DIR"
git pull
echo "✓ Git pull complete"
echo ""

# Step 2: Reinstall packages in virtual environment
echo "📦 Step 2: Reinstalling packages in virtual environment..."
if [ ! -d "$VENV_PATH" ]; then
    echo "❌ ERROR: Virtual environment not found at $VENV_PATH"
    echo "   Run systemd/setup-systemd.sh first to create it"
    exit 1
fi

# Activate venv
source "$VENV_PATH/bin/activate"

# Reinstall agents_lib first (other packages depend on it)
echo "   Installing agents_lib..."
cd "$SCRIPT_DIR/agents_lib"
pip install -e . --quiet

# Reinstall all agent packages
echo "   Installing bug-triage-agent..."
cd "$SCRIPT_DIR/bug-triage-agent"
pip install -e . --quiet

echo "   Installing code-review-agent..."
cd "$SCRIPT_DIR/code-review-agent"
pip install -e . --quiet

echo "   Installing bug-reproduction-agent..."
cd "$SCRIPT_DIR/bug-reproduction-agent"
pip install -e . --quiet

echo "✓ All packages reinstalled"
echo ""

# Step 3: Reload systemd daemon
echo "🔄 Step 3: Reloading systemd daemon..."
systemctl --user daemon-reload
echo "✓ Systemd daemon reloaded"
echo ""

# Step 4: Check which services are running
echo "🔍 Step 4: Checking running services..."
RUNNING_SERVICES=()

if systemctl --user is-active --quiet octavia-bug-triage.timer; then
    RUNNING_SERVICES+=("octavia-bug-triage.timer")
fi

if systemctl --user is-active --quiet octavia-code-review.timer; then
    RUNNING_SERVICES+=("octavia-code-review.timer")
fi

if systemctl --user is-active --quiet octavia-bug-reproduction.path; then
    RUNNING_SERVICES+=("octavia-bug-reproduction.path")
fi

if [ ${#RUNNING_SERVICES[@]} -eq 0 ]; then
    echo "ℹ️  No services are currently running"
    echo ""
    echo "========================================="
    echo "✅ Update Complete!"
    echo "========================================="
    echo ""
    echo "To start services, run:"
    echo "  systemctl --user start octavia-bug-triage.timer"
    echo "  systemctl --user start octavia-code-review.timer"
    echo "  systemctl --user start octavia-bug-reproduction.path"
    exit 0
fi

# Step 5: Ask about restarting services
echo "Currently running services:"
for service in "${RUNNING_SERVICES[@]}"; do
    echo "  - $service"
done
echo ""

read -p "Restart running services to apply updates? [y/N] " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "♻️  Step 5: Restarting services..."
    for service in "${RUNNING_SERVICES[@]}"; do
        echo "   Restarting $service..."
        systemctl --user restart "$service"
    done
    echo "✓ Services restarted"
else
    echo "⏭️  Skipping service restart"
    echo ""
    echo "ℹ️  NOTE: Services will use updated code on their next scheduled run"
    echo "   To restart manually, run:"
    for service in "${RUNNING_SERVICES[@]}"; do
        echo "     systemctl --user restart $service"
    done
fi

echo ""
echo "========================================="
echo "✅ Update Complete!"
echo "========================================="
echo ""
echo "Updated packages:"
echo "  ✓ agents-lib (shared utilities)"
echo "  ✓ octavia-bug-triage-agent"
echo "  ✓ octavia-code-review-agent"
echo "  ✓ octavia-bug-reproduction-agent"
echo ""
echo "Changes are now active in $VENV_PATH"
echo ""
echo "View service status:"
echo "  systemctl --user list-timers octavia-*"
echo "  systemctl --user status octavia-bug-reproduction.path"
