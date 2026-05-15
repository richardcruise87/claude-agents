#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="${VENV_PATH:-$HOME/.venv/claude-agents}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

UPDATE_MODE=false
INSTALL_SYSTEMD=""
SETUP_NOTIFICATIONS=""
SETUP_CREDENTIALS=""
SELECTED_AGENTS=()
CREDS_FILE="$HOME/.config/claude-agents/credentials.env"

ALL_AGENTS=("bug-triage" "code-review" "bug-reproduction" "ci-failure" "devstack-test" "jira-triage" "fix-proposal" "fix-verification")

get_agent_dir() {
    case $1 in
        bug-triage)       echo "bug-triage-agent" ;;
        code-review)      echo "code-review-agent" ;;
        bug-reproduction) echo "bug-reproduction-agent" ;;
        ci-failure)       echo "ci-failure-agent" ;;
        devstack-test)    echo "devstack-test-agent" ;;
        jira-triage)      echo "jira-triage-agent" ;;
        fix-proposal)     echo "fix-proposal-agent" ;;
        fix-verification) echo "fix-verification-agent" ;;
    esac
}

usage() {
    echo "Usage: $(basename "$0") [OPTIONS] [AGENT...]"
    echo ""
    echo "Install or update Claude Agents."
    echo ""
    echo "Options:"
    echo "  --update          Update mode: git pull + reinstall + reload services"
    echo "  --systemd           Install systemd unit files without prompting"
    echo "  --no-systemd        Skip systemd installation without prompting"
    echo "  --notifications     Set up notifications without prompting"
    echo "  --no-notifications  Skip notification setup without prompting"
    echo "  --credentials       Set up credentials file without prompting"
    echo "  --no-credentials    Skip credentials setup without prompting"
    echo "  --venv PATH         Virtual environment path (default: ~/.venv/claude-agents)"
    echo "  -h, --help          Show this help message"
    echo ""
    echo "Agents (default: all):"
    echo "  bug-triage        Bug Triage Agent"
    echo "  code-review       Code Review Agent"
    echo "  bug-reproduction  Bug Reproduction Agent"
    echo "  ci-failure        CI Failure Agent"
    echo "  devstack-test     DevStack Test Agent"
    echo "  jira-triage       JIRA Triage Agent"
    echo "  fix-proposal      Fix Proposal Agent"
    echo "  fix-verification  Fix Verification Agent"
    echo ""
    echo "Examples:"
    echo "  $(basename "$0")                              # Install all agents"
    echo "  $(basename "$0") bug-triage code-review       # Install specific agents"
    echo "  $(basename "$0") --update                     # Update all agents"
    echo "  $(basename "$0") --update ci-failure          # Update specific agent"
    echo "  $(basename "$0") --systemd --notifications    # Install all, enable both"
    echo "  $(basename "$0") --no-systemd bug-triage      # Install without systemd"
}

while [[ $# -gt 0 ]]; do
    case $1 in
        --update)            UPDATE_MODE=true; shift ;;
        --systemd)           INSTALL_SYSTEMD=yes; shift ;;
        --no-systemd)        INSTALL_SYSTEMD=no; shift ;;
        --notifications)     SETUP_NOTIFICATIONS=yes; shift ;;
        --no-notifications)  SETUP_NOTIFICATIONS=no; shift ;;
        --credentials)       SETUP_CREDENTIALS=yes; shift ;;
        --no-credentials)    SETUP_CREDENTIALS=no; shift ;;
        --venv)              VENV_PATH="$2"; shift 2 ;;
        -h|--help)        usage; exit 0 ;;
        bug-triage|code-review|bug-reproduction|ci-failure|devstack-test|jira-triage|fix-proposal|fix-verification)
                          SELECTED_AGENTS+=("$1"); shift ;;
        *)
            echo -e "${RED}ERROR${NC}: Unknown argument: $1"
            echo ""
            usage
            exit 1
            ;;
    esac
done

if [ ${#SELECTED_AGENTS[@]} -eq 0 ]; then
    SELECTED_AGENTS=("${ALL_AGENTS[@]}")
fi

echo "=============================================="
if $UPDATE_MODE; then
    echo "  Claude Agents - Update"
else
    echo "  Claude Agents - Setup"
fi
echo "=============================================="
echo ""

STEP=1

# Step: git pull (update mode only)
if $UPDATE_MODE; then
    echo -e "${BLUE}Step ${STEP}: Pulling latest changes from git${NC}"
    cd "$SCRIPT_DIR"
    git pull
    echo -e "${GREEN}✓${NC} Git pull complete"
    echo ""
    STEP=$((STEP + 1))
fi

# Step: Create/validate venv
echo -e "${BLUE}Step ${STEP}: Virtual environment${NC}"
if [ -d "$VENV_PATH" ]; then
    echo -e "${GREEN}✓${NC} Using existing virtual environment at $VENV_PATH"
else
    if $UPDATE_MODE; then
        echo -e "${RED}ERROR${NC}: Virtual environment not found at $VENV_PATH"
        echo "Run without --update first to create the virtual environment:"
        echo "  $(basename "$0")"
        exit 1
    fi
    echo "Creating virtual environment at $VENV_PATH..."
    python3 -m venv "$VENV_PATH"
    echo -e "${GREEN}✓${NC} Virtual environment created"
fi
STEP=$((STEP + 1))
echo ""

# Step: Install agents_lib
echo -e "${BLUE}Step ${STEP}: Installing shared library (agents_lib)${NC}"
"$VENV_PATH/bin/pip" install -q -e "$SCRIPT_DIR/agents_lib/"
echo -e "${GREEN}✓${NC} agents_lib installed"
STEP=$((STEP + 1))
echo ""

# Step: Systemd decision (install mode only, ask once before the main loop)
if ! $UPDATE_MODE && [ -z "$INSTALL_SYSTEMD" ]; then
    echo -e "${BLUE}Step ${STEP}: Systemd services (optional)${NC}"
    echo "Systemd unit files enable automated scheduling for each agent."
    echo -n "Install systemd unit files? [y/N] "
    read -r _response
    [[ "$_response" =~ ^[Yy]$ ]] && INSTALL_SYSTEMD=yes || INSTALL_SYSTEMD=no
    STEP=$((STEP + 1))
    echo ""
fi

# Ensure INSTALL_SYSTEMD is always set before the agent loop (update mode
# skips the step-3 prompt, so it may still be empty here — default to no).
[ -z "$INSTALL_SYSTEMD" ] && INSTALL_SYSTEMD=no

# Step: Install agents
echo -e "${BLUE}Step ${STEP}: Installing agents${NC}"
for agent in "${SELECTED_AGENTS[@]}"; do
    agent_dir=$(get_agent_dir "$agent")
    if [ ! -d "$SCRIPT_DIR/$agent_dir" ]; then
        echo -e "  ${YELLOW}⚠${NC} Skipping $agent (directory $agent_dir not found)"
        continue
    fi
    if [ ! -f "$SCRIPT_DIR/$agent_dir/install.sh" ]; then
        echo -e "  ${YELLOW}⚠${NC} Skipping $agent (no install.sh found in $agent_dir)"
        continue
    fi
    [ "$INSTALL_SYSTEMD" = "yes" ] && _sd_flag="--systemd" || _sd_flag="--no-systemd"
    echo -e "  ${BLUE}→${NC} $agent"
    bash "$SCRIPT_DIR/$agent_dir/install.sh" --venv "$VENV_PATH" "$_sd_flag" 2>&1 | sed -u 's/^/    /'
done
STEP=$((STEP + 1))
echo ""

# Step: Notifications (install mode only)
if ! $UPDATE_MODE; then
    NOTIF_JSON="$SCRIPT_DIR/notifications.json"
    echo -e "${BLUE}Step ${STEP}: Notifications (optional)${NC}"

    if [ "$SETUP_NOTIFICATIONS" = "yes" ]; then
        : # Flag passed — proceed below
    elif [ "$SETUP_NOTIFICATIONS" = "no" ]; then
        : # Flag passed — skip below
    elif [ -f "$NOTIF_JSON" ]; then
        echo -e "${GREEN}✓${NC} notifications.json already exists"
        SETUP_NOTIFICATIONS=existing
    else
        echo "Agents can notify you (email, Slack, ntfy.sh, desktop) when reports are ready."
        echo -n "Set up notifications? [y/N] "
        read -r _response
        [[ "$_response" =~ ^[Yy]$ ]] && SETUP_NOTIFICATIONS=yes || SETUP_NOTIFICATIONS=no
    fi

    if [ "$SETUP_NOTIFICATIONS" = "yes" ]; then
        cp "$SCRIPT_DIR/notifications.sample.json" "$NOTIF_JSON"
        echo -e "${GREEN}✓${NC} Created notifications.json — edit it to configure channels"
    fi

    # Enable notifications in each agent's config.json when setting up or if already configured
    if [ "$SETUP_NOTIFICATIONS" = "yes" ] || [ "$SETUP_NOTIFICATIONS" = "existing" ]; then
        for agent in "${SELECTED_AGENTS[@]}"; do
            agent_dir=$(get_agent_dir "$agent")
            config_file="$SCRIPT_DIR/$agent_dir/config.json"
            if [ -f "$config_file" ]; then
                python3 - <<PYEOF
import json
with open('$config_file') as f:
    cfg = json.load(f)
if not cfg.get('notifications', {}).get('enabled'):
    cfg.setdefault('notifications', {})['enabled'] = True
    with open('$config_file', 'w') as f:
        json.dump(cfg, f, indent=2)
    print('    Enabled notifications in $agent_dir/config.json')
PYEOF
            fi
        done
    fi

    STEP=$((STEP + 1))
    echo ""
fi

# Step: Credentials file (install mode only)
if ! $UPDATE_MODE; then
    echo -e "${BLUE}Step ${STEP}: Credentials (optional)${NC}"

    if [ "$SETUP_CREDENTIALS" = "yes" ]; then
        : # Flag passed — proceed below
    elif [ "$SETUP_CREDENTIALS" = "no" ]; then
        : # Flag passed — skip below
    elif [ -f "$CREDS_FILE" ]; then
        echo -e "${GREEN}✓${NC} Credentials file already exists: $CREDS_FILE"
        echo -n "Update credentials? [y/N] "
        read -r _response
        [[ "$_response" =~ ^[Yy]$ ]] && SETUP_CREDENTIALS=yes || SETUP_CREDENTIALS=existing
    else
        echo "Sensitive credentials (Gerrit, Launchpad) can be stored in a"
        echo "chmod 600 file instead of in the systemd service files."
        echo -n "Set up credentials file? [y/N] "
        read -r _response
        [[ "$_response" =~ ^[Yy]$ ]] && SETUP_CREDENTIALS=yes || SETUP_CREDENTIALS=no
    fi

    if [ "$SETUP_CREDENTIALS" = "yes" ]; then
        mkdir -p "$(dirname "$CREDS_FILE")"

        # Seed file with current values if it exists, otherwise blank
        if [ ! -f "$CREDS_FILE" ]; then
            cat > "$CREDS_FILE" << 'CREDSEOF'
# Claude Agents credentials
# Loaded by all agent systemd services via EnvironmentFile=
# Permissions: 600 (readable only by you)
#
# Leave a value blank to skip it — agents that don't use a credential
# simply ignore the unset variable.

# ── Gerrit / OpenDev ────────────────────────────────────────────────────────
# Used by: code-review, ci-failure, devstack-test agents
# Generate at: https://review.opendev.org/settings/#HTTPCredentials
GERRIT_USERNAME=
GERRIT_HTTP_PASSWORD=

# ── Launchpad OAuth ─────────────────────────────────────────────────────────
# Used by: bug-triage, fix-proposal, fix-verification agents
# Generate with: python3 scripts/get_launchpad_token.py
LAUNCHPAD_CONSUMER_KEY=
LAUNCHPAD_ACCESS_TOKEN=
LAUNCHPAD_ACCESS_TOKEN_SECRET=
CREDSEOF
        fi
        chmod 600 "$CREDS_FILE"

        echo ""
        echo "Enter credentials (press Enter to leave existing value unchanged):"
        echo ""

        # Helper: prompt for a credential, update the file if a value is given
        _set_cred() {
            local key="$1" prompt="$2"
            local current
            current=$(grep -E "^${key}=" "$CREDS_FILE" | cut -d= -f2-)
            if [ -n "$current" ]; then
                echo -n "  $prompt [currently set, Enter to keep]: "
            else
                echo -n "  $prompt [Enter to skip]: "
            fi
            read -r _val
            if [ -n "$_val" ]; then
                # Replace or append the key=value line
                if grep -q "^${key}=" "$CREDS_FILE"; then
                    sed -i "s|^${key}=.*|${key}=${_val}|" "$CREDS_FILE"
                else
                    echo "${key}=${_val}" >> "$CREDS_FILE"
                fi
                echo -e "    ${GREEN}✓${NC} $key saved"
            fi
        }

        echo "  Gerrit / OpenDev:"
        _set_cred GERRIT_USERNAME        "Gerrit username"
        _set_cred GERRIT_HTTP_PASSWORD   "Gerrit HTTP password"
        echo ""
        echo "  Launchpad OAuth:"
        _set_cred LAUNCHPAD_CONSUMER_KEY          "Consumer key"
        _set_cred LAUNCHPAD_ACCESS_TOKEN          "Access token"
        _set_cred LAUNCHPAD_ACCESS_TOKEN_SECRET   "Access token secret"
        echo ""
        echo -e "${GREEN}✓${NC} Credentials saved to $CREDS_FILE (chmod 600)"
    fi

    STEP=$((STEP + 1))
    echo ""
fi

# Reload systemd if files were installed or in update mode
if [ "$INSTALL_SYSTEMD" = "yes" ] || $UPDATE_MODE; then
    echo -e "${BLUE}Step ${STEP}: Reloading systemd daemon${NC}"
    systemctl --user daemon-reload
    echo -e "${GREEN}✓${NC} Systemd daemon reloaded"
    STEP=$((STEP + 1))
    echo ""
fi

# Update mode: check/restart running services
if $UPDATE_MODE; then
    echo -e "${BLUE}Step ${STEP}: Checking running services${NC}"
    RUNNING_SERVICES=()
    for svc in octavia-bug-triage.timer octavia-code-review.timer \
               octavia-ci-failure.timer octavia-bug-reproduction.path \
               octavia-devstack-test.path; do
        if systemctl --user is-active --quiet "$svc" 2>/dev/null; then
            RUNNING_SERVICES+=("$svc")
        fi
    done

    if [ ${#RUNNING_SERVICES[@]} -gt 0 ]; then
        echo "Running services:"
        for svc in "${RUNNING_SERVICES[@]}"; do
            echo "  - $svc"
        done
        echo ""
        echo -n "Restart running services to apply updates? [y/N] "
        read -r _response
        if [[ "$_response" =~ ^[Yy]$ ]]; then
            for svc in "${RUNNING_SERVICES[@]}"; do
                systemctl --user restart "$svc"
                echo -e "${GREEN}✓${NC} Restarted $svc"
            done
        fi
    else
        echo "No services currently running."
    fi
    echo ""
fi

echo "=============================================="
if $UPDATE_MODE; then
    echo -e "${GREEN}✓ Update complete!${NC}"
else
    echo -e "${GREEN}✓ Setup complete!${NC}"
fi
echo "=============================================="
echo ""

if ! $UPDATE_MODE; then
    echo "Next steps:"
    echo ""
    echo "1. Edit configuration files for each agent:"
    for agent in "${SELECTED_AGENTS[@]}"; do
        agent_dir=$(get_agent_dir "$agent")
        if [ -f "$SCRIPT_DIR/$agent_dir/config.json" ]; then
            echo "     $SCRIPT_DIR/$agent_dir/config.json"
        fi
    done
    echo ""

    if [ "$SETUP_NOTIFICATIONS" = "yes" ]; then
        echo "2. Edit notification channels:"
        echo "     $SCRIPT_DIR/notifications.json"
        echo ""
        NEXT=3
    else
        NEXT=2
    fi

    if [ "$SETUP_CREDENTIALS" = "yes" ]; then
        echo "${NEXT}. Edit credentials (Gerrit / Launchpad):"
        echo "     $CREDS_FILE"
        echo ""
        NEXT=$((NEXT + 1))
    elif [ "$SETUP_CREDENTIALS" != "existing" ]; then
        echo "${NEXT}. (Optional) Store credentials securely:"
        echo "     $(basename "$0") --credentials"
        echo ""
        NEXT=$((NEXT + 1))
    fi

    if [ "$INSTALL_SYSTEMD" = "yes" ]; then
        echo "${NEXT}. Enable and start services:"
        NEXT=$((NEXT + 1))
        for agent in "${SELECTED_AGENTS[@]}"; do
            case $agent in
                bug-triage)
                    echo "     systemctl --user enable --now octavia-bug-triage.timer" ;;
                code-review)
                    echo "     systemctl --user enable --now octavia-code-review.timer" ;;
                ci-failure)
                    echo "     systemctl --user enable --now octavia-ci-failure.timer" ;;
                bug-reproduction)
                    echo "     systemctl --user enable --now octavia-bug-reproduction.path" ;;
                devstack-test)
                    echo "     systemctl --user enable --now octavia-devstack-test.path" ;;
                jira-triage)
                    echo "     systemctl --user enable --now octavia-jira-triage.timer" ;;
                fix-proposal)
                    echo "     systemctl --user enable --now octavia-fix-proposal.timer" ;;
                fix-verification)
                    echo "     systemctl --user enable --now octavia-fix-verification.timer" ;;
            esac
        done
        echo ""
        echo "${NEXT}. Persist services across logout:"
        echo "     loginctl enable-linger $USER"
    else
        echo "${NEXT}. Run agents manually:"
        for agent in "${SELECTED_AGENTS[@]}"; do
            case $agent in
                bug-triage)       echo "     $VENV_PATH/bin/octavia-triage-bugs" ;;
                code-review)      echo "     $VENV_PATH/bin/octavia-review-agent" ;;
                ci-failure)       echo "     $VENV_PATH/bin/octavia-ci-agent" ;;
                bug-reproduction) echo "     $VENV_PATH/bin/octavia-reproduce-bugs" ;;
                devstack-test)    echo "     $VENV_PATH/bin/octavia-devstack-test" ;;
                jira-triage)      echo "     $VENV_PATH/bin/octavia-jira-triage" ;;
                fix-proposal)     echo "     $VENV_PATH/bin/octavia-propose-fix" ;;
                fix-verification) echo "     $VENV_PATH/bin/octavia-verify-fix" ;;
            esac
        done
        echo ""
        echo "   Or re-run with --systemd to install scheduling:"
        echo "     $(basename "$0") --systemd ${SELECTED_AGENTS[*]}"
    fi
fi
