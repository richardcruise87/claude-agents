#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="${VENV_PATH:-$HOME/.venv/claude-agents}"
INSTALL_SYSTEMD="${INSTALL_SYSTEMD:-}"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

usage() {
    echo "Usage: $(basename "$0") [OPTIONS]"
    echo ""
    echo "Install the Bug Reproduction Agent into the Claude Agents virtual environment."
    echo ""
    echo "Options:"
    echo "  --venv PATH     Virtual environment path (default: ~/.venv/claude-agents)"
    echo "  --systemd       Install systemd unit files"
    echo "  --no-systemd    Skip systemd installation"
    echo "  -h, --help      Show this help"
    echo ""
    echo "The VENV_PATH and INSTALL_SYSTEMD environment variables are also accepted."
    echo ""
    echo "Examples:"
    echo "  $(basename "$0")              # Install package, prompt for systemd"
    echo "  $(basename "$0") --systemd   # Install package + systemd files"
    echo "  $(basename "$0") --no-systemd  # Install package only"
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --venv)        VENV_PATH="$2"; shift 2 ;;
        --systemd)     INSTALL_SYSTEMD=yes; shift ;;
        --no-systemd)  INSTALL_SYSTEMD=no; shift ;;
        -h|--help)     usage; exit 0 ;;
        *) echo "Unknown option: $1"; usage; exit 1 ;;
    esac
done

# Create venv if missing
if [ ! -d "$VENV_PATH" ]; then
    echo -e "${BLUE}Creating virtual environment at $VENV_PATH...${NC}"
    python3 -m venv "$VENV_PATH"
    echo -e "${GREEN}✓${NC} Virtual environment created"
fi

# Install agents_lib if missing
if ! "$VENV_PATH/bin/python" -c "import agents_lib" 2>/dev/null; then
    REPO_DIR="$(dirname "$SCRIPT_DIR")"
    if [ -d "$REPO_DIR/agents_lib" ]; then
        "$VENV_PATH/bin/pip" install -q -e "$REPO_DIR/agents_lib/"
        echo -e "${GREEN}✓${NC} agents_lib installed"
    else
        echo -e "${RED}ERROR${NC}: agents_lib not found. Run setup-agents.sh from the repo root."
        exit 1
    fi
fi

# Install this agent
"$VENV_PATH/bin/pip" install -q -e "$SCRIPT_DIR/"
echo -e "${GREEN}✓${NC} bug-reproduction-agent installed (octavia-reproduce-bugs)"

# Copy config if missing
if [ ! -f "$SCRIPT_DIR/config.json" ] && [ -f "$SCRIPT_DIR/config.sample.json" ]; then
    cp "$SCRIPT_DIR/config.sample.json" "$SCRIPT_DIR/config.json"
    echo -e "${YELLOW}⚠${NC} Created config.json from sample — edit before running"
fi

# Systemd
if [ -z "$INSTALL_SYSTEMD" ]; then
    echo -n "Install systemd service files for the bug reproduction agent? [y/N] "
    read -r _response
    [[ "$_response" =~ ^[Yy]$ ]] && INSTALL_SYSTEMD=yes || INSTALL_SYSTEMD=no
fi

if [ "$INSTALL_SYSTEMD" = "yes" ]; then
    USER_SYSTEMD_DIR="$HOME/.config/systemd/user"
    mkdir -p "$USER_SYSTEMD_DIR"
    for f in "$SCRIPT_DIR/systemd/"*.service \
              "$SCRIPT_DIR/systemd/"*.path \
              "$SCRIPT_DIR/systemd/"*.timer; do
        [ -f "$f" ] || continue
        base=$(basename "$f")
        sed "s|%h|$HOME|g; s|%u|$USER|g" "$f" > "$USER_SYSTEMD_DIR/$base"
        echo -e "${GREEN}✓${NC} Installed $base"
    done
    echo ""
    echo "To enable the bug reproduction agent:"
    echo "  # Event-driven (runs immediately when a new triage report appears):"
    echo "  systemctl --user enable --now octavia-bug-reproduction.path"
    echo ""
    echo "  # Scheduled fallback (daily at 12:00, catches any missed reports):"
    echo "  systemctl --user enable --now octavia-bug-reproduction.timer"
fi
