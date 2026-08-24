#!/bin/sh
# AAP Bridge - installer
#
# One command, two ways to run AAP Bridge. It asks which you want, checks what
# it needs, installs it, and walks you through configuring a workspace.
#
#   curl -LsSf https://raw.githubusercontent.com/redhat-cop/aap-bridge/main/scripts/install.sh | sh
#
#   1. Command line - installs the `aap-bridge` command with uv.
#   2. Containers   - builds the CLI, API engine, and Web UI images, and runs
#                     them with PostgreSQL under Podman.
#
# Choosing without being asked:
#   sh install.sh --cli            (or --containers)
#   AAP_BRIDGE_MODE=cli            (or container)
#
# Environment overrides:
#   AAP_BRIDGE_SOURCE=<dir>      Install from a local checkout instead of git
#   AAP_BRIDGE_REF=main          Git ref to install from
#   AAP_BRIDGE_WORKSPACE=<dir>   Workspace to create (default: $HOME/aap-migration)
#   AAP_BRIDGE_YES=1             Skip the confirmation prompt
#   AAP_BRIDGE_NO_INIT=1         Install only; skip the setup walkthrough (CLI)
#   AAP_BRIDGE_REBUILD=1         Rebuild images even if they are current
#   AAP_BRIDGE_SKIP_BUILD=1      Reuse images already present locally
#   AAP_BRIDGE_NO_START=1        Build and configure only; do not start services
#   AAP_BRIDGE_VERBOSE=1         Show command output and implementation detail
#
# Note: AAP Bridge does not yet publish to PyPI or a container registry, so
# both journeys build from source. Once artifacts are published, both become a
# download.

set -eu

# To install from somewhere else - a fork, a branch under review, or a local
# checkout - override these rather than editing them:
#   AAP_BRIDGE_REPO=git@example.com:you/aap-bridge.git
#   AAP_BRIDGE_REF=my-branch
#   AAP_BRIDGE_SOURCE=$PWD   (skips the clone entirely)
REPO_URL="${AAP_BRIDGE_REPO:-https://github.com/redhat-cop/aap-bridge.git}"
REF="${AAP_BRIDGE_REF:-main}"

PY_VERSION="3.12"
TMPROOT="${TMPDIR:-/tmp}"

CLI_IMAGE="localhost/aap-bridge:latest"
API_IMAGE="localhost/aap-bridge-api:latest"
UI_IMAGE="localhost/aap-bridge-ui:latest"

# Registry images the container journey builds on and runs. Kept in sync by
# hand with Containerfile, Containerfile.ui, and deploy/compose.user.yml: the
# preflight has to know them before any source is fetched, which is the whole
# point of checking them first.
REGISTRY="registry.redhat.io"
BASE_IMAGE="registry.redhat.io/ubi9/ubi-minimal:latest"
NODE_IMAGE="registry.redhat.io/ubi9/nodejs-20-minimal:latest"
DB_IMAGE="registry.redhat.io/rhel9/postgresql-15"

# The images run as uid 998. Rootless Podman maps the host user onto that uid
# with keep-id, so files a container writes into the mounted workspace are
# owned by the person running the installer. Without it a container cannot
# write to the workspace at all.
CONTAINER_UID=998

# Default host ports the compose stack publishes. Each is overridable in the
# workspace .env, so a machine already using one does not have to give it up.
DEFAULT_DB_PORT=15432
DEFAULT_API_PORT=8000
DEFAULT_UI_PORT=8080

# Label carrying the source revision an image was built from, so a re-run can
# tell "already built" from "built months ago out of different code".
REVISION_LABEL="io.aap-bridge.source-revision"

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    BOLD=$(printf '\033[1m'); RED=$(printf '\033[31m')
    GREEN=$(printf '\033[32m'); YELLOW=$(printf '\033[33m')
    DIM=$(printf '\033[2m'); RESET=$(printf '\033[0m')
else
    BOLD=''; RED=''; GREEN=''; YELLOW=''; DIM=''; RESET=''
fi

# Three symbols carry the whole visual model:
#   ✔ ready    ! optional issue / degraded    ✘ cannot continue
ok()   { printf '  %s✔%s %s\n' "$GREEN" "$RESET" "$1"; }
warn() { printf '  %s!%s %s\n' "$YELLOW" "$RESET" "$1"; }
step() { printf '  %s→%s %s\n' "$DIM" "$RESET" "$1"; }
die()  { printf '\n  %s✘ %s%s\n\n' "$RED" "$1" "$RESET" >&2; exit 1; }

case "${AAP_BRIDGE_VERBOSE:-0}" in
    0|""|false|no) VERBOSE=0 ;;
    *) VERBOSE=1 ;;
esac

# Implementation detail: resolved paths, exact versions, image references.
# Useful when something breaks, noise on the happy path.
detail() { [ "$VERBOSE" = "1" ] && printf '  %s%s%s\n' "$DIM" "$1" "$RESET"; return 0; }

section() { printf '\n%s%s%s\n\n' "$BOLD" "$1" "$RESET"; }

has() { command -v "$1" >/dev/null 2>&1; }

# A stage that takes a while announces itself on one line and then overwrites
# it with its result, so progress is visible while it runs without leaving a
# trail of duplicate lines. Off a TTY, and in verbose mode where command output
# scrolls past underneath, the line stays put instead.
if [ -t 1 ] && [ "$VERBOSE" != "1" ]; then LIVE=1; else LIVE=0; fi

# <symbol> <colour> <label> [note]. A label with no note is a plain result
# line, so a finished stage does not carry the padding its progress line needed.
item() {
    if [ -n "${4:-}" ]; then
        printf '  %s%s%s %-8s %s%s%s' "$2" "$1" "$RESET" "$3" "$DIM" "$4" "$RESET"
    else
        printf '  %s%s%s %s' "$2" "$1" "$RESET" "$3"
    fi
}

item_ok()   { item '✔' "$GREEN" "$1" "${2:-}"; printf '\n'; }
item_fail() { item '✘' "$RED" "$1" "${2:-}"; printf '\n'; }
item_skip() { item '•' "$DIM" "$1" "${2:-}"; printf '\n'; }

item_begin() {
    item '→' "$DIM" "$1" "${2:-}"
    [ "$LIVE" = "1" ] || printf '\n'
    return 0
}

# --- Long stages ------------------------------------------------------------
#
# An image build runs for minutes with its output in the log, so the line has
# to prove the installer is alive. A frame and an elapsed time do that, and say
# more than a written estimate: the estimate is wrong on most machines, whereas
# "3m12s and counting" is what is actually happening.

# POSIX only guarantees whole seconds, so check before relying on a fraction.
if sleep 0.1 2>/dev/null; then SPIN_DELAY=0.1; else SPIN_DELAY=1; fi

spinner_frame() {
    case "$1" in
        0) printf '⠋' ;; 1) printf '⠙' ;; 2) printf '⠹' ;; 3) printf '⠸' ;;
        4) printf '⠼' ;; 5) printf '⠴' ;; 6) printf '⠦' ;; *) printf '⠧' ;;
    esac
}

elapsed() {
    _e=$(( $2 - $1 ))
    if [ "$_e" -ge 60 ]; then
        printf '%dm%02ds' $(( _e / 60 )) $(( _e % 60 ))
    else
        printf '%ds' "$_e"
    fi
}

# --- Captured output --------------------------------------------------------

# Everything a command prints goes here rather than to the screen. Build tools
# are chatty, and some of what they emit (pip's root-user advisory, npm audit
# notices) is expected inside an image build and alarming outside one.
LOG=$(mktemp "${TMPROOT}/aap-bridge-install.XXXXXX") || LOG="/dev/null"
RC_FILE="${TMPROOT}/aap-bridge-status.$$"

# Once there is a workspace, the log belongs in it: that is where the user is
# told to look, and where it survives the installer exiting.
adopt_log() {
    [ -n "${1:-}" ] || return 0
    mkdir -p "$1/logs" 2>/dev/null || return 0
    _dest="$1/logs/install.log"
    if [ "$LOG" != "/dev/null" ] && [ -f "$LOG" ] && [ "$LOG" != "$_dest" ]; then
        cat "$LOG" >> "$_dest" 2>/dev/null || true
        rm -f "$LOG"
    fi
    LOG="$_dest"
    return 0
}

logged() {
    if [ "$VERBOSE" = "1" ]; then
        # The status file carries the command's exit code out of the pipeline;
        # POSIX sh has no pipefail and $? would be tee's.
        { "$@" 2>&1; printf '%s' "$?" > "$RC_FILE"; } | tee -a "$LOG" | sed 's/^/    /'
        [ "$(cat "$RC_FILE")" = "0" ]
    else
        "$@" >> "$LOG" 2>&1
    fi
}

# run_fg <label> <activity> <command...>
#
# Same before-and-after line as run_stage, but the command keeps the terminal.
# For anything that might prompt - sudo, an ssh key passphrase - since a
# background job that reads from the terminal is stopped by SIGTTIN and hangs
# with no visible reason.
run_fg() {
    _flabel="$1"; _fact="$2"; shift 2
    item_begin "$_flabel" "$_fact"
    _frc=0
    logged "$@" || _frc=$?
    [ "$LIVE" = "1" ] && printf '\r\033[K'
    return "$_frc"
}

# run_stage <label> <activity> <command...>
#
# Runs the command with its output captured, animating the line until it
# finishes. Returns the command's exit status; the line is left cleared, for
# the caller to replace with a result. The command gets no terminal - use
# run_fg for anything that may prompt.
run_stage() {
    _slabel="$1"; _sact="$2"; shift 2

    if [ "$LIVE" != "1" ]; then
        item_begin "$_slabel" "$_sact"
        _src=0
        logged "$@" || _src=$?
        return "$_src"
    fi

    logged "$@" < /dev/null &
    _spid=$!
    _sstart=$(date +%s)
    _sframe=0
    while kill -0 "$_spid" 2>/dev/null; do
        printf '\r\033[K  %s%s%s %-8s %s%s  %s%s' \
            "$DIM" "$(spinner_frame "$_sframe")" "$RESET" "$_slabel" \
            "$DIM" "$_sact" "$(elapsed "$_sstart" "$(date +%s)")" "$RESET"
        _sframe=$(( (_sframe + 1) % 8 ))
        sleep "$SPIN_DELAY"
    done
    _src=0
    wait "$_spid" || _src=$?
    printf '\r\033[K'
    return "$_src"
}

log_tail() {
    if [ "$VERBOSE" != "1" ] && [ -s "$LOG" ]; then
        printf '\n%sLast lines of the log:%s\n' "$DIM" "$RESET"
        tail -n 12 "$LOG" 2>/dev/null | sed "s/^/  ${DIM}/;s/\$/${RESET}/"
    fi
    return 0
}

# ---------------------------------------------------------------------------
# Path helpers
#
# $HOME is used where it exists but never assumed: a daemon or minimal
# container may not set it, and `set -u` would abort on a bare reference.
# ---------------------------------------------------------------------------

# Collapse the home directory to a literal $HOME for display, so the plan reads
# the same for everyone instead of showing one machine's directory layout.
display_path() {
    if [ -n "${HOME:-}" ]; then
        case "$1" in
            "$HOME") printf '$HOME'; return 0 ;;
            "$HOME"/*) printf '$HOME/%s' "${1#"$HOME"/}"; return 0 ;;
        esac
    fi
    printf '%s' "$1"
}

# Turn user input into an absolute path. `read` does no expansion, so ~ and a
# literal $HOME (which is what display_path prints, and therefore what people
# copy) are handled here. Relative paths resolve against the current directory.
resolve_path() {
    _p="$1"
    if [ -n "${HOME:-}" ]; then
        case "$_p" in
            "~") _p="$HOME" ;;
            "~/"*) _p="$HOME/${_p#\~/}" ;;
            '$HOME') _p="$HOME" ;;
            '$HOME/'*) _p="$HOME/${_p#\$HOME/}" ;;
        esac
    fi
    case "$_p" in
        /*) ;;
        *) _p="$PWD/$_p" ;;
    esac
    printf '%s' "$_p"
}

# ---------------------------------------------------------------------------
# Input helpers
#
# When the script is piped from curl, stdin carries the script itself, so
# answers must come from the controlling terminal instead. Probe by actually
# opening /dev/tty: it can exist but be unusable (cron, containers without a
# controlling terminal), where a plain -r test passes. The probe runs in a
# subshell because a redirection failure on a brace group is fatal in POSIX sh.
# ---------------------------------------------------------------------------

if [ -t 0 ]; then
    INPUT="stdin"
elif ( : < /dev/tty ) 2>/dev/null; then
    INPUT="tty"
else
    INPUT="none"
fi

# ask <prompt> <default> -> sets ANSWER
ask() {
    printf '%s' "$1"
    case "$INPUT" in
        stdin) read -r ANSWER || ANSWER="" ;;
        tty)   read -r ANSWER < /dev/tty || ANSWER="" ;;
        none)  ANSWER=""; printf '\n' ;;
    esac
    # An explicit if, not `[ -z ... ] && ...`: as the last command in the
    # function that returns 1 for a non-empty answer, which under `set -e`
    # aborts the whole script.
    if [ -z "$ANSWER" ]; then
        ANSWER="$2"
    fi
    return 0
}

# Run an interactive command with the terminal attached. Needed for both
# `podman login` and the setup walkthrough when this script came from curl.
with_tty() {
    if [ "$INPUT" = "tty" ]; then
        "$@" < /dev/tty
    else
        "$@"
    fi
}

# ---------------------------------------------------------------------------
# Temporary checkout
#
# Created under /tmp and removed on exit. mktemp rather than a fixed
# /tmp/aap-bridge: a predictable name in a world-writable directory can be
# pre-created by another user as a symlink.
# ---------------------------------------------------------------------------

SRC_DIR=""
cleanup() {
    if [ -n "$SRC_DIR" ] && [ -d "$SRC_DIR" ]; then
        rm -rf "$SRC_DIR"
    fi
    rm -f "$RC_FILE"
    case "$LOG" in
        "${TMPROOT}"/aap-bridge-install.*) rm -f "$LOG" ;;
    esac
    # An EXIT trap's final status replaces the script's exit code.
    return 0
}
trap cleanup EXIT INT TERM

# ---------------------------------------------------------------------------
# Shared setup: source, workspace, consent
# ---------------------------------------------------------------------------

resolve_source_and_workspace() {
    LOCAL_SRC="${AAP_BRIDGE_SOURCE:-}"
    if [ -n "$LOCAL_SRC" ]; then
        LOCAL_SRC=$(resolve_path "$LOCAL_SRC")
        [ -f "$LOCAL_SRC/pyproject.toml" ] || die "No pyproject.toml in $LOCAL_SRC"
    fi

    if [ -n "${AAP_BRIDGE_WORKSPACE:-}" ]; then
        WORKSPACE=$(resolve_path "$AAP_BRIDGE_WORKSPACE")
    elif [ -n "${HOME:-}" ]; then
        WORKSPACE="$HOME/aap-migration"
    else
        WORKSPACE="$PWD/aap-migration"
    fi
}

# Fetch the source into a temporary checkout, or point at the local one.
# Sets SRC. Both journeys build from source, so both need this.
#
# Deliberately leaves no line behind. Where the source came from is the
# installer's business, not a step the user asked for or can act on; the
# progress line exists only so a slow clone does not look like a stall, and
# --verbose still records the repository, ref, and directory.
fetch_source() {
    if [ -n "$LOCAL_SRC" ]; then
        SRC="$LOCAL_SRC"
        detail "building from $LOCAL_SRC, left untouched"
        return 0
    fi
    SRC_DIR=$(mktemp -d "${TMPROOT}/aap-bridge.XXXXXX") \
        || die "Could not create a temporary directory under ${TMPROOT}"
    # Foreground: an SSH clone can ask for a key passphrase.
    if run_fg "Preparing" "installation" \
        git clone --quiet --depth 1 --branch "$REF" "$REPO_URL" "$SRC_DIR/src"
    then
        SRC="$SRC_DIR/src"
        detail "${REPO_URL}@${REF} in ${SRC_DIR}, removed once it is no longer needed"
        return 0
    fi
    log_tail
    die "Could not fetch the AAP Bridge source. Check the repository URL and ref."
}

# A record of how AAP Bridge was installed here, so the uninstaller can
# describe and remove the right things instead of listing everything it knows
# how to look for. Older workspaces have none, and it infers from what it finds.
write_install_record() {
    cat > "$WORKSPACE/.aap-bridge-install" <<RECORD
# How AAP Bridge was installed in this workspace.
# Written by the installer, read by uninstall.sh.
installation_mode=$1
RECORD
}

# --- Which journey ----------------------------------------------------------

# Sets MODE from the arguments, the environment, or a question. Returns 1 when
# the user quits.
choose_journey() {
    MODE="${AAP_BRIDGE_MODE:-}"
    for arg in "$@"; do
        case "$arg" in
            --cli|cli) MODE="cli" ;;
            --containers|--container|containers|container) MODE="container" ;;
            -h|--help)
                printf 'Usage: install.sh [--cli | --containers]\n'
                HELP_ONLY=1
                return 1
                ;;
            *) die "Unknown option: $arg" ;;
        esac
    done

    case "$MODE" in
        cli|container) ;;
        "") ;;
        *) die "AAP_BRIDGE_MODE must be 'cli' or 'container', not '$MODE'" ;;
    esac

    printf '\n%sAAP Bridge - Setup%s\n\n' "$BOLD" "$RESET"
    [ -n "$MODE" ] && return 0

    printf 'AAP Bridge migrates automation content between Ansible Automation\n'
    printf 'Platform instances. There are two ways to run it.\n'
    printf '\n'
    printf '  %s1. Command line%s\n' "$BOLD" "$RESET"
    printf '     Installs the aap-bridge command on this machine\n'
    printf '\n'
    printf '  %s2. Containers%s\n' "$BOLD" "$RESET"
    printf '     Installs and runs the CLI, API engine, Web UI, and PostgreSQL\n'
    printf '     with Podman\n'
    printf '\n'
    printf '  %sq. Quit%s\n' "$BOLD" "$RESET"
    printf '\n'

    if [ "$INPUT" = "none" ]; then
        printf 'No terminal available to choose. Re-run with %s--cli%s or %s--containers%s.\n\n' \
            "$BOLD" "$RESET" "$BOLD" "$RESET"
        FAILED=1
        return 1
    fi

    while :; do
        ask "Choose [1]: " "1"
        case "$ANSWER" in
            1 | [cC][lL][iI]) MODE="cli"; printf '\n'; return 0 ;;
            2 | [cC]*) MODE="container"; printf '\n'; return 0 ;;
            [qQ] | [qQ][uU][iI][tT] | [eE][xX][iI][tT]) return 1 ;;
            *) printf '  %sEnter 1, 2, or q.%s\n' "$DIM" "$RESET" ;;
        esac
    done
}

# --- Workspace and consent --------------------------------------------------
#
# The workspace is chosen and understood before anything is installed. An
# existing one is a normal thing to find - a reinstall, an upgrade, a second
# run after a failure - and the installer should say what it found and ask what
# to do with it, rather than discovering it halfway through and stopping with
# the machine already changed.

describe_plan() {
    printf 'AAP Bridge needs a workspace to store its configuration,\n'
    printf 'AAP API tokens, logs, and migration files.\n'
    printf '\n'
    printf 'Default workspace:\n'
    printf '  %s%s%s\n' "$BOLD" "$(display_path "$WORKSPACE")" "$RESET"
    printf '\n'

    # Where the `aap-bridge` command goes. Both installations put one here: the
    # CLI journey via uv, the container journey as a shim onto the workspace
    # launcher. Which one is underneath is an install-time choice, not
    # something to remember at every invocation.
    if [ -n "${UV_TOOL_BIN_DIR:-}" ]; then
        BIN_DIR="$UV_TOOL_BIN_DIR"
    elif [ -n "${XDG_BIN_HOME:-}" ]; then
        BIN_DIR="$XDG_BIN_HOME"
    elif [ -n "${HOME:-}" ]; then
        BIN_DIR="$HOME/.local/bin"
    else
        BIN_DIR=""
    fi

    if [ "$MODE" != "cli" ]; then
        printf 'The containers AAP Bridge runs in - the CLI, the API engine,\n'
        printf 'the Web UI, and PostgreSQL - are built and started for you.\n'
        printf '\n'
    fi
    if [ -n "$BIN_DIR" ]; then
        printf 'The `aap-bridge` command will also be installed in:\n'
        printf '  %s%s%s\n' "$BOLD" "$(display_path "$BIN_DIR")" "$RESET"
        printf '\n'
    fi
}

# What is already in the chosen directory:
#   new         nothing of ours there
#   configured  .env and config/config.yaml both present
#   partial     one of them, or artifact directories with no configuration
workspace_state() {
    if [ -f "$WORKSPACE/.env" ] && [ -f "$WORKSPACE/config/config.yaml" ]; then
        printf 'configured'
    elif [ -f "$WORKSPACE/.env" ] || [ -f "$WORKSPACE/config/config.yaml" ]; then
        printf 'partial'
    elif [ -d "$WORKSPACE/exports" ] || [ -d "$WORKSPACE/xformed" ]; then
        printf 'partial'
    else
        printf 'new'
    fi
}

workspace_has_migration_data() {
    for _d in exports xformed reports schemas backups; do
        if [ -d "$WORKSPACE/$_d" ] && [ -n "$(ls -A "$WORKSPACE/$_d" 2>/dev/null)" ]; then
            return 0
        fi
    done
    return 1
}

# Ask for a workspace path. Returns 1 when the user quits.
prompt_workspace() {
    printf 'Press Enter to continue, enter another path, or type %sq%s to quit.\n' "$BOLD" "$RESET"
    printf '\n'
    ask "Workspace [$(display_path "$WORKSPACE")]: " "$WORKSPACE"
    case "$ANSWER" in
        [qQ] | [qQ][uU][iI][tT] | [eE][xX][iI][tT]) return 1 ;;
    esac
    _chosen=$(resolve_path "$ANSWER")
    if [ "$_chosen" != "$WORKSPACE" ]; then
        WORKSPACE="$_chosen"
        printf '  %s→%s workspace set to %s%s%s\n' \
            "$DIM" "$RESET" "$BOLD" "$(display_path "$WORKSPACE")" "$RESET"
    fi
    return 0
}

# Show what is in the workspace and decide what to do with it. Sets
# WORKSPACE_ACTION to one of:
#   fresh        configure it from scratch
#   keep         leave the configuration alone; install and verify
#   reconfigure  walk the settings again, keeping the migration data
# Returns 1 to quit, 2 to ask for a different workspace.
decide_workspace_action() {
    WORKSPACE_ACTION="fresh"
    _state=$(workspace_state)
    [ "$_state" = "new" ] && return 0

    section "Checking workspace"
    if [ "$_state" = "configured" ]; then
        ok "Existing AAP Bridge workspace found"
        ok "Configuration found"
        [ -f "$WORKSPACE/.env" ] && ok "AAP credentials found"
        workspace_has_migration_data && ok "Migration data found"
        detail "$WORKSPACE"
    else
        ok "Workspace found"
        if [ -f "$WORKSPACE/.env" ]; then
            ok "AAP credentials found"
        else
            warn "AAP credentials missing"
        fi
        if [ -f "$WORKSPACE/config/config.yaml" ]; then
            ok "Migration configuration found"
        else
            warn "Migration configuration missing"
        fi
    fi

    # Nobody to ask: reuse what is there rather than refusing or overwriting.
    if [ "$INPUT" = "none" ] || [ "${AAP_BRIDGE_YES:-0}" = "1" ]; then
        if [ "$_state" = "configured" ]; then
            WORKSPACE_ACTION="keep"
            detail "existing configuration kept"
        else
            WORKSPACE_ACTION="fresh"
        fi
        return 0
    fi

    if [ "$_state" = "configured" ]; then
        printf '\n%sThis workspace is already configured.%s\n\n' "$BOLD" "$RESET"
        printf '  %s1. Use existing configuration%s\n' "$BOLD" "$RESET"
        printf '     Keep your settings and migration data\n\n'
        printf '  %s2. Reconfigure%s\n' "$BOLD" "$RESET"
        printf '     Update connection settings without deleting migration data\n\n'
        printf '  %s3. Choose another workspace%s\n\n' "$BOLD" "$RESET"
        printf '  %sq. Quit%s\n\n' "$BOLD" "$RESET"

        while :; do
            ask "Choose [1]: " "1"
            case "$ANSWER" in
                1) WORKSPACE_ACTION="keep"; return 0 ;;
                2) WORKSPACE_ACTION="reconfigure"; return 0 ;;
                3) return 2 ;;
                [qQ] | [qQ][uU][iI][tT] | [eE][xX][iI][tT]) return 1 ;;
                *) printf '  %sEnter 1, 2, 3, or q.%s\n' "$DIM" "$RESET" ;;
            esac
        done
    fi

    printf '\n%sThis workspace is partially configured.%s\n\n' "$BOLD" "$RESET"
    printf '  %s1. Complete setup%s\n' "$BOLD" "$RESET"
    printf '     Finish configuring it, keeping any migration data\n\n'
    printf '  %s2. Choose another workspace%s\n\n' "$BOLD" "$RESET"
    printf '  %sq. Quit%s\n\n' "$BOLD" "$RESET"

    while :; do
        ask "Choose [1]: " "1"
        case "$ANSWER" in
            1) WORKSPACE_ACTION="reconfigure"; return 0 ;;
            2) return 2 ;;
            [qQ] | [qQ][uU][iI][tT] | [eE][xX][iI][tT]) return 1 ;;
            *) printf '  %sEnter 1, 2, or q.%s\n' "$DIM" "$RESET" ;;
        esac
    done
}

# Choose the workspace and decide what to do with what is in it. Returns 1 when
# the user quits, so cancelling is an outcome the caller reports rather than an
# exit from the middle of the script.
choose_workspace() {
    WORKSPACE_ACTION="fresh"

    if [ "${AAP_BRIDGE_YES:-0}" = "1" ]; then
        detail "AAP_BRIDGE_YES=1, continuing without prompting"
        decide_workspace_action || true
        return 0
    fi

    if [ "$INPUT" = "none" ]; then
        printf 'No terminal available to confirm. Re-run with %sAAP_BRIDGE_YES=1%s to\n' "$BOLD" "$RESET"
        printf 'proceed non-interactively.\n\n'
        FAILED=1
        return 1
    fi

    # Loops so that "choose another workspace" asks again instead of sending
    # the user back to the command they started with.
    while :; do
        if [ -n "${AAP_BRIDGE_WORKSPACE:-}" ] && [ "${_asked_once:-0}" = "0" ]; then
            # Location pinned by the caller, so only confirm it.
            printf 'Press Enter to continue, or type %sq%s to quit.\n' "$BOLD" "$RESET"
            printf '\n'
            ask "Continue: " ""
            case "$ANSWER" in
                [qQ] | [qQ][uU][iI][tT] | [eE][xX][iI][tT]) return 1 ;;
            esac
        else
            prompt_workspace || return 1
        fi
        _asked_once=1

        decide_workspace_action
        case "$?" in
            0) return 0 ;;
            2) printf '\n' ;;
            *) return 1 ;;
        esac
    done
}

# ===========================================================================
# Journey 1: command line
# ===========================================================================

journey_cli() {
    # Version strings, not just presence: they cost the reader almost nothing
    # and make a screenshot or support thread far more useful later.
    uv_version()     { uv --version 2>/dev/null | awk '{print $2}'; }
    podman_version() { podman --version 2>/dev/null | awk '{print $3}'; }
    git_version()    { git --version 2>/dev/null | awk '{print $3}'; }

    section "Checking your system"

    case "$(uname -s)" in
        Linux|Darwin) ok "$(uname -s) $(uname -m)" ;;
        *)
            printf '  %s✘%s %s %s is not supported\n\n' "$RED" "$RESET" "$(uname -s)" "$(uname -m)"
            printf 'AAP Bridge currently supports Linux and macOS.\n\n'
            printf 'Setup stopped. No changes were made.\n\n'
            exit 1
            ;;
    esac

    NEEDS_UV=0
    NEEDS_GIT=0

    # Git is an implementation detail of fetching the source: the user never
    # interacts with it, so it earns a line only when it is missing. `doctor`
    # and verbose mode still report it.
    if [ -z "$LOCAL_SRC" ] && ! has git; then
        warn "Git not found"
        NEEDS_GIT=1
    else
        detail "Git $(git_version)"
    fi

    if has uv; then
        ok "uv $(uv_version)"
    else
        warn "uv not found"
        NEEDS_UV=1
    fi

    if has podman; then
        ok "Podman $(podman_version)"
    elif has psql; then
        ok "PostgreSQL client available"
    else
        warn "Podman not found - the bundled database will be unavailable"
    fi

    # --- Install missing tools ---------------------------------------------
    #
    # This is an automated installer: it fixes what it can rather than sending
    # the user away with a list of commands. uv comes from its official
    # script. Git needs a package manager and elevated rights, so it is
    # attempted only where that is unambiguous.

    if [ "$NEEDS_UV" = "1" ] || [ "$NEEDS_GIT" = "1" ]; then
        section "Installing required tools"

        if [ "$NEEDS_GIT" = "1" ]; then
            # Foreground: sudo may ask for a password.
            installed_git=0
            if has dnf; then
                run_fg "Git" "installing" sudo dnf install -y git && installed_git=1
            elif has apt-get; then
                run_fg "Git" "installing" sudo sh -c \
                    'apt-get update && apt-get install -y git' && installed_git=1
            elif has brew; then
                run_fg "Git" "installing" brew install git && installed_git=1
            fi
            if [ "$installed_git" = "1" ] && has git; then
                ok "Git $(git_version) installed"
            else
                die "Git is required and could not be installed automatically. Install Git and re-run."
            fi
        fi

        if [ "$NEEDS_UV" = "1" ]; then
            if has curl; then
                run_stage "uv" "installing" sh -c \
                    'curl -LsSf https://astral.sh/uv/install.sh | sh' || true
            elif has wget; then
                run_stage "uv" "installing" sh -c \
                    'wget -qO- https://astral.sh/uv/install.sh | sh' || true
            else
                die "Installing uv needs curl or wget, and neither was found."
            fi
            if [ -n "${HOME:-}" ]; then
                for candidate in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
                    [ -x "$candidate/uv" ] && PATH="$candidate:$PATH" && export PATH
                done
            fi
            has uv || die "uv could not be installed automatically. See https://docs.astral.sh/uv/"
            ok "uv $(uv_version) installed"
        fi
    fi

    # --- Install -----------------------------------------------------------

    section "Installing AAP Bridge"

    fetch_source

    # --force replaces an existing tool's entry points; --reinstall
    # additionally rebuilds the package instead of reusing uv's build cache.
    # Without the latter, re-running the installer against a moved branch can
    # silently install a stale build, since uv caches by URL and revision.
    if ! run_stage "aap-bridge" "installing" \
        uv tool install --force --reinstall --python "$PY_VERSION" "$SRC"
    then
        log_tail
        die "Installation failed. See the output above."
    fi

    # The checkout has served its purpose; remove it before going any further
    # so the temporary directory does not outlive a later failure.
    if [ -n "$SRC_DIR" ]; then
        rm -rf "$SRC_DIR"
        SRC_DIR=""
        detail "temporary checkout removed"
    fi

    if [ -n "$BIN_DIR" ] && [ -x "$BIN_DIR/aap-bridge" ]; then
        PATH="$BIN_DIR:$PATH"; export PATH
    elif [ -n "${HOME:-}" ]; then
        for candidate in "$HOME/.local/bin" "$HOME/.cargo/bin"; do
            [ -x "$candidate/aap-bridge" ] && PATH="$candidate:$PATH" && export PATH
        done
    fi

    has aap-bridge || die "aap-bridge installed but not on PATH. Run: uv tool update-shell"
    ok "$(aap-bridge --version 2>/dev/null | sed 's/aap-bridge, version /aap-bridge /' || echo 'aap-bridge installed') installed"

    if [ -n "$BIN_DIR" ] && ! printf '%s' ":$PATH:" | grep -q ":$BIN_DIR:"; then
        warn "$(display_path "$BIN_DIR") is not on your PATH"
        detail 'add it with:  uv tool update-shell'
    fi

    # The workspace walkthrough lives in `aap-bridge init`. An older build will
    # not have it; fail here with an explanation rather than leaving an empty
    # directory.
    if ! aap-bridge init --help >/dev/null 2>&1; then
        printf '\n'
        warn "this build has no 'aap-bridge init' command"
        detail "source used: ${LOCAL_SRC:-${REPO_URL}@${REF}}"
        if [ -z "$LOCAL_SRC" ]; then
            printf '\n  That ref may predate it. Install from a local checkout with:\n'
            printf '    %sAAP_BRIDGE_SOURCE=/path/to/aap-bridge sh %s%s\n' "$BOLD" "${0:-install.sh}" "$RESET"
        fi
        die "Cannot configure a workspace. The CLI itself is installed and usable."
    fi

    # --- Workspace ---------------------------------------------------------

    if [ "${AAP_BRIDGE_NO_INIT:-0}" = "1" ]; then
        printf '\n%sInstalled.%s Run %saap-bridge init%s in a directory to configure.\n\n' \
            "$GREEN$BOLD" "$RESET" "$BOLD" "$RESET"
        exit 0
    fi

    section "Creating workspace"
    mkdir -p "$WORKSPACE" || die "Could not create $WORKSPACE"
    adopt_log "$WORKSPACE"
    write_install_record cli
    ok "Workspace ready"

    cd "$WORKSPACE" || die "Could not enter $WORKSPACE"

    # Reusing an existing workspace is a reinstall, not a configuration run:
    # there is nothing to ask, only something to confirm still works.
    if [ "$WORKSPACE_ACTION" = "keep" ]; then
        if ! aap-bridge doctor --brief --dir "$WORKSPACE"; then
            printf '\nYour settings are unchanged. Fix what is reported above, or\n'
            printf 'reconfigure with:\n'
            printf '  cd %s\n' "$(display_path "$WORKSPACE")"
            printf '  aap-bridge init --force\n\n'
            exit 1
        fi
        printf '\n%sSetup complete%s\n\n' "$GREEN$BOLD" "$RESET"
        printf '  Workspace:\n'
        printf '    %s%s%s\n\n' "$BOLD" "$(display_path "$WORKSPACE")" "$RESET"
        printf '%sStart your migration%s\n' "$BOLD" "$RESET"
        printf '  aap-bridge\n\n'
        return 0
    fi

    # `init` configures the workspace, starts the bundled database, and
    # verifies that it and both AAP instances are reachable. Setup ends there:
    # starting a migration moves real data between two AAP instances, so it
    # stays an explicit action the user takes, not something the installer does
    # for them.
    #
    # --force only when the user asked to reconfigure, and it rewrites the
    # settings rather than the workspace: exports, transformed data, reports,
    # and logs are left where they are.
    #
    # with_tty, because under `curl | sh` this script's stdin is the pipe the
    # script itself arrived on, and it is at EOF. The installer reads its own
    # answers from /dev/tty; a child that prompts needs the same, or its first
    # question reads EOF and aborts.
    _init_args=""
    [ "$WORKSPACE_ACTION" = "reconfigure" ] && _init_args="--force"

    # shellcheck disable=SC2086  # _init_args is one optional flag
    if ! with_tty aap-bridge init --dir "$WORKSPACE" $_init_args; then
        printf '\n%sSetup needs additional configuration%s\n\n' "$BOLD" "$RESET"
        printf 'AAP Bridge was installed successfully, and your existing files\n'
        printf 'were not changed:\n'
        printf '  %s%s%s\n\n' "$BOLD" "$(display_path "$WORKSPACE")" "$RESET"
        printf 'Finish configuring it with:\n'
        printf '  cd %s\n' "$(display_path "$WORKSPACE")"
        printf '  aap-bridge init\n\n'
        exit 1
    fi
}

# ===========================================================================
# Journey 2: containers
# ===========================================================================

journey_container() {
    podman_version() { podman --version 2>/dev/null | awk '{print $3}'; }
    git_version()    { git --version 2>/dev/null | awk '{print $3}'; }

    section "Checking your system"

    case "$(uname -s)" in
        Linux|Darwin) ok "$(uname -s) $(uname -m)" ;;
        *)
            printf '  %s✘%s %s %s is not supported\n\n' "$RED" "$RESET" "$(uname -s)" "$(uname -m)"
            printf 'AAP Bridge currently supports Linux and macOS.\n\n'
            printf 'Setup stopped. No changes were made.\n\n'
            exit 1
            ;;
    esac

    has podman || die "Podman is required but was not found. See https://podman.io/docs/installation"
    ok "Podman $(podman_version)"

    if podman compose version >/dev/null 2>&1; then
        ok "Podman Compose"
        detail "$(podman compose version 2>/dev/null | head -n 1)"
    else
        die "Podman Compose is not available. Install podman-compose or docker-compose."
    fi

    NEEDS_GIT=0
    if [ -n "$LOCAL_SRC" ] || has git; then
        detail "Git $(git_version)"
    else
        warn "Git not found"
        NEEDS_GIT=1
    fi

    # Rootless Podman is what keep-id assumes. Running as root works, but the
    # mapping flags must be dropped.
    if [ "$(id -u)" -eq 0 ]; then
        PODMAN_USERNS=""
        detail "running as root - user namespace mapping not used"
    else
        PODMAN_USERNS="--userns=keep-id:uid=${CONTAINER_UID},gid=${CONTAINER_UID}"
    fi

    # --- What might have to be built or pulled -----------------------------
    #
    # Whether an image really needs rebuilding cannot be known until the source
    # is fetched and its revision compared with what the local images were
    # built from, so this is deliberately the pessimistic answer: anything that
    # could build, might. Its only job is to decide which registry images to
    # check for.

    MAY_BUILD=1
    if [ "${AAP_BRIDGE_SKIP_BUILD:-0}" = "1" ]; then
        MAY_BUILD=0
        for image in "$CLI_IMAGE" "$API_IMAGE" "$UI_IMAGE"; do
            image_present "$image" \
                || die "AAP_BRIDGE_SKIP_BUILD=1 but $image is missing. Re-run without it."
        done
    fi

    [ -n "$LOCAL_SRC" ] || [ "$MAY_BUILD" = "0" ] || [ "$NEEDS_GIT" = "0" ] \
        || die "Git is required to fetch the source. Install Git and re-run."

    # Registry images this run might have to pull. The base images matter only
    # when something could be built; the database image is needed either way.
    # On a machine that has built before they are all local already, so a
    # re-run still needs nothing from the registry.
    REQUIRED_IMAGES=""
    image_present "$DB_IMAGE" || REQUIRED_IMAGES="$DB_IMAGE"
    if [ "$MAY_BUILD" = "1" ]; then
        image_present "$BASE_IMAGE" || REQUIRED_IMAGES="$REQUIRED_IMAGES $BASE_IMAGE"
        image_present "$NODE_IMAGE" || REQUIRED_IMAGES="$REQUIRED_IMAGES $NODE_IMAGE"
    fi

    # --- Registry access ---------------------------------------------------
    #
    # A missing login is a blocking prerequisite, not a warning. Resolve it
    # here or stop: the alternative is spending minutes on a build that the
    # preflight already knows cannot finish.

    NEEDS_LOGIN=0
    if [ -n "$REQUIRED_IMAGES" ] && ! podman login --get-login "$REGISTRY" >/dev/null 2>&1; then
        NEEDS_LOGIN=1
        warn "Red Hat Registry login required"
    elif [ -z "$REQUIRED_IMAGES" ]; then
        detail "registry access not needed - every image is already local"
    else
        detail "logged in to $REGISTRY"
    fi

    if [ "$NEEDS_LOGIN" = "1" ]; then
        printf '\nAAP Bridge uses container images from %s.\n\n' "$REGISTRY"

        _declined=1
        if [ "$INPUT" != "none" ]; then
            ask "Log in now? [Y/n]: " "y"
            case "$ANSWER" in
                [nN] | [nN][oO] | [qQ] | [qQ][uU][iI][tT]) _declined=1 ;;
                *) _declined=0 ;;
            esac
        fi

        if [ "$_declined" = "0" ]; then
            section "Logging in to Red Hat Registry"
            _attempt=1
            while :; do
                # Hand straight to `podman login` so credentials go to Podman's
                # own store and are never seen, prompted for, or kept here.
                if with_tty podman login "$REGISTRY"; then
                    break
                fi
                _attempt=$((_attempt + 1))
                if [ "$_attempt" -gt 3 ] || [ "$INPUT" = "none" ]; then
                    _declined=1
                    break
                fi
                printf '\n'
                ask "Login failed. Try again? [Y/n]: " "y"
                case "$ANSWER" in
                    [nN] | [nN][oO] | [qQ] | [qQ][uU][iI][tT]) _declined=1; break ;;
                esac
                printf '\n'
            done
        fi

        if [ "$_declined" = "1" ]; then
            printf '\nSetup cannot continue without registry access.\n\n'
            printf 'Run:\n'
            printf '  %spodman login %s%s\n\n' "$BOLD" "$REGISTRY" "$RESET"
            printf 'Then run this installer again.\n\n'
            printf 'No images were built.\n\n'
            exit 1
        fi
    fi

    # --- Checking container images -----------------------------------------
    #
    # Being logged in does not mean every image is reachable: entitlements
    # differ per repository. A manifest lookup costs a round trip and no layer
    # downloads, which is cheap enough to do for all of them before committing
    # to a build.

    section "Checking container images"

    # Checked one at a time, reported as one line: which base image a build
    # needs is the installer's business, and only matters when one is missing -
    # where the failure names it.
    if [ "$MAY_BUILD" = "1" ]; then
        check_image "Application base image" "$BASE_IMAGE"
        check_image "Node.js image" "$NODE_IMAGE"
    fi
    check_image "PostgreSQL image" "$DB_IMAGE"
    ok "Required images available"

    # --- Preparing workspace -----------------------------------------------
    #
    # The workspace is created before the build so its logs directory can hold
    # the build log. A failed build then has somewhere to point, and the
    # workspace is the one thing a re-run can rely on already being there.

    section "Preparing workspace"

    mkdir -p "$WORKSPACE" || die "Could not create $WORKSPACE"
    adopt_log "$WORKSPACE"
    write_install_record container
    ok "Workspace ready"
    detail "$WORKSPACE"

    # The source is needed for anything the workspace is missing, not only for
    # a build: the compose file, the launcher, and the uninstaller all come
    # from it, and a re-run has to be able to replace them.
    NEED_SOURCE=0
    [ "$MAY_BUILD" = "1" ] && NEED_SOURCE=1
    workspace_compose_ok || NEED_SOURCE=1
    [ -x "$WORKSPACE/aap-bridge" ] || NEED_SOURCE=1
    [ -x "$WORKSPACE/uninstall.sh" ] || NEED_SOURCE=1

    if [ "$NEED_SOURCE" = "1" ]; then
        fetch_source
    else
        SRC=""
        detail "no source needed: every image is present and the workspace is complete"
    fi

    # --- Building AAP Bridge -----------------------------------------------
    #
    # Each image is built and reported on its own, and one already built from
    # this exact source revision is kept. A failed run is therefore resumable -
    # what built stays built - without the opposite failure of silently reusing
    # an image that predates the code being installed, which "does the tag
    # exist?" cannot tell apart.

    if [ -n "$LOCAL_SRC" ]; then
        # A working tree changes without any marker changing, so there is
        # nothing trustworthy to compare against. Rebuild, and let the layer
        # cache make it cheap when nothing actually changed.
        REV=""
        detail "building from a local directory - images are always rebuilt"
    else
        REV=$(git -C "$SRC" rev-parse HEAD 2>/dev/null) || REV=""
        detail "source revision ${REV:-unknown}"
    fi

    S_CLI="pending"; S_API="pending"; S_UI="pending"

    section "Building AAP Bridge"

    if [ "${AAP_BRIDGE_SKIP_BUILD:-0}" = "1" ]; then
        S_CLI="reused"; S_API="reused"; S_UI="reused"
        item_ok "CLI" "already built"
        item_ok "API" "already built"
        item_ok "Web UI" "already built"
    else
        build_image "CLI" S_CLI "$CLI_IMAGE" --target base "$SRC" || build_failed
        build_image "API" S_API "$API_IMAGE" --target api "$SRC" || build_failed
        build_image "Web UI" S_UI "$UI_IMAGE" -f "$SRC/Containerfile.ui" "$SRC" || build_failed
    fi

    # --- Workspace files ---------------------------------------------------

    # The end-user compose file has to be in place before the walkthrough runs,
    # and must not be overwritten by it: `aap-bridge init --managed-db` knows
    # the database is provided by this stack and leaves compose.yml alone.
    if [ -n "$SRC" ] && [ -f "$SRC/deploy/compose.user.yml" ]; then
        cp "$SRC/deploy/compose.user.yml" "$WORKSPACE/compose.yml" \
            || die "Could not write $WORKSPACE/compose.yml"
        detail "wrote $WORKSPACE/compose.yml"
    elif workspace_compose_ok; then
        detail "keeping the existing $WORKSPACE/compose.yml"
    else
        die "Could not obtain compose.yml. Re-run to fetch the source again."
    fi

    # Before the checkout is removed, not after: these are copied out of it.
    # Getting that order wrong is what turned a complete build into an install
    # with no way to operate it.
    section "Installing command"
    if ! write_workspace_tools; then
        printf '  %s✘%s Could not install the aap-bridge command\n\n' "$RED" "$RESET"
        printf 'The images were built and your workspace was kept:\n'
        printf '  %s%s%s\n\n' "$BOLD" "$(display_path "$WORKSPACE")" "$RESET"
        printf 'Run this installer again to finish.\n\n'
        exit 1
    fi

    install_command_shim
    if [ -n "$SHIM_PATH" ]; then
        ok "aap-bridge installed"
        detail "$SHIM_PATH -> $WORKSPACE/aap-bridge"
        if ! printf '%s' ":$PATH:" | grep -q ":$BIN_DIR:"; then
            warn "$(display_path "$BIN_DIR") is not on your PATH"
            detail "run it as $(display_path "$WORKSPACE")/aap-bridge until it is"
        fi
    else
        ok "Workspace launcher installed"
        detail "$WORKSPACE/aap-bridge"
    fi

    # The temporary checkout has served its purpose. Remove it now so it does
    # not outlive a later failure.
    if [ -n "$SRC_DIR" ]; then
        rm -rf "$SRC_DIR"
        SRC_DIR=""
    fi

    # --- Configuring migration ---------------------------------------------
    #
    # The same `aap-bridge init` walkthrough the CLI journey runs, so both
    # produce an identical .env and config/config.yaml. --managed-db tells it
    # the database is this compose stack's: it writes the credentials but
    # neither starts nor verifies the service, which happens below.

    if [ "$WORKSPACE_ACTION" = "keep" ] \
        && [ -f "$WORKSPACE/.env" ] && [ -f "$WORKSPACE/config/config.yaml" ]; then
        section "Configuring migration"
        ok "Existing configuration kept"
        detail "reconfigure with: cd $(display_path "$WORKSPACE") && ./aap-bridge init --force --managed-db"
    elif [ "$INPUT" = "none" ]; then
        section "Configuring migration"
        warn "No terminal available for the setup walkthrough"
        printf '\nThe containers are built and your workspace is ready:\n'
        printf '  %s%s%s\n\n' "$BOLD" "$(display_path "$WORKSPACE")" "$RESET"
        printf 'Finish setup from a terminal with:\n'
        printf '  cd %s\n' "$(display_path "$WORKSPACE")"
        printf '  ./aap-bridge init --managed-db\n'
        printf '  podman compose up -d\n\n'
        exit 1
    else
        # An older image will not have the walkthrough; fail here with an
        # explanation rather than leaving a half-configured directory behind.
        if ! podman run --rm "$CLI_IMAGE" init --help 2>/dev/null | grep -q -- '--managed-db'; then
            printf '\n'
            warn "the built image predates 'aap-bridge init --managed-db'"
            detail "built from: ${LOCAL_SRC:-${REPO_URL}@${REF}}"
            printf '\n  Build from a branch that includes it, or configure by hand.\n'
            die "Cannot configure a workspace. The images themselves are built."
        fi

        printf '\n'
        _init_args="--managed-db"
        [ "$WORKSPACE_ACTION" = "reconfigure" ] && _init_args="--managed-db --force"

        # shellcheck disable=SC2086  # both are flag lists, empty or not
        if ! with_tty podman run --rm -it --network host $PODMAN_USERNS \
            -e AAP_BRIDGE_HOST_WORKSPACE="$WORKSPACE" \
            -v "$WORKSPACE":/work:Z -w /work "$CLI_IMAGE" init --dir /work $_init_args
        then
            printf '\n%sSetup needs additional configuration%s\n\n' "$BOLD" "$RESET"
            printf 'The containers are built and your existing files were not\n'
            printf 'changed:\n'
            printf '  %s%s%s\n\n' "$BOLD" "$(display_path "$WORKSPACE")" "$RESET"
            printf 'Run this installer again to finish configuring it.\n\n'
            exit 1
        fi
    fi

    # --- Starting services -------------------------------------------------

    # The workspace .env is the single source of truth for every published
    # port: the engine, the UI's proxy, and the database all read it.
    API_PORT=$(env_port AAP_BRIDGE_API_PORT "$DEFAULT_API_PORT")
    UI_PORT=$(env_port AAP_BRIDGE_UI_PORT "$DEFAULT_UI_PORT")
    DB_PORT=$(env_port AAP_BRIDGE_DB_PORT "$DEFAULT_DB_PORT")

    # Before the early exit below: which ports this workspace uses is part of
    # configuring it, not part of starting it.
    check_ports

    if [ "${AAP_BRIDGE_NO_START:-0}" = "1" ]; then
        section "Setup complete"
        ok "Workspace configured"
        printf '\n%sStart AAP Bridge%s\n' "$BOLD" "$RESET"
        if [ -n "$SHIM_PATH" ]; then
            printf '  aap-bridge start\n\n'
        else
            printf '  cd %s\n' "$(display_path "$WORKSPACE")"
            printf '  ./aap-bridge start\n\n'
        fi
        exit 0
    fi

    section "Starting services"

    if run_stage "Database" "starting" start_db; then
        item_ok "Database"
    else
        item_fail "Database" "did not become ready"
        printf '\nThe migration database did not start.\n\n'
        printf 'Details:\n'
        printf '  %s%s%s\n' "$BOLD" "$(display_path "$LOG")" "$RESET"
        printf '  cd %s && podman compose logs db\n\n' "$(display_path "$WORKSPACE")"
        exit 1
    fi

    if run_stage "API engine" "starting" compose up -d engine; then
        item_ok "API engine"
    else
        item_fail "API engine" "failed to start"
        printf '\nDetails:\n  cd %s && podman compose logs engine\n\n' "$(display_path "$WORKSPACE")"
        exit 1
    fi

    if run_stage "Web UI" "starting" compose up -d ui; then
        item_ok "Web UI"
    else
        item_fail "Web UI" "failed to start"
        printf '\nDetails:\n  cd %s && podman compose logs ui\n\n' "$(display_path "$WORKSPACE")"
        exit 1
    fi

    # --- Verifying setup ---------------------------------------------------
    #
    # Started is not the same as working. The AAP connections were already
    # checked by the walkthrough; what is left is whether the stack answers.

    section "Verifying setup"

    ok "Database accepting connections"

    HEALTHY=1
    if has curl; then
        if run_stage "API" "waiting" wait_for_http "http://localhost:${API_PORT}/docs" 90; then
            ok "API engine responding"
        else
            warn "API engine is not responding yet"
            detail "http://localhost:${API_PORT}"
            HEALTHY=0
        fi
        if run_stage "Web UI" "waiting" wait_for_http "http://localhost:${UI_PORT}/" 60; then
            ok "Web UI responding"
        else
            warn "Web UI is not responding yet"
            HEALTHY=0
        fi
    else
        warn "curl not found - could not check the API and Web UI"
        detail "check them at http://localhost:${UI_PORT}"
    fi

    # --- Done --------------------------------------------------------------

    printf '\n%sSetup complete%s\n\n' "$GREEN$BOLD" "$RESET"

    printf '  %sWeb UI%s     http://localhost:%s\n' "$BOLD" "$RESET" "$UI_PORT"
    printf '  %sWorkspace%s  %s\n' "$BOLD" "$RESET" "$(display_path "$WORKSPACE")"
    printf '\n'

    if [ "$HEALTHY" != "1" ]; then
        printf 'Some services were still starting. Check them with:\n'
        printf '  cd %s\n' "$(display_path "$WORKSPACE")"
        printf '  ./aap-bridge status\n'
        printf '  ./aap-bridge logs engine\n\n'
    fi

    # One command name either way. Without a shim - no bin directory, or one
    # already holding something else - it is the workspace launcher by path,
    # and saying so beats printing a command that will not be found.
    if [ -n "$SHIM_PATH" ]; then
        _cmd="aap-bridge"
    else
        _cmd="./aap-bridge"
        printf 'Run these from your workspace:\n'
        printf '  cd %s\n' "$(display_path "$WORKSPACE")"
        printf '\n'
    fi

    printf '%sRun a migration%s\n' "$BOLD" "$RESET"
    printf '  %-24s start the interactive CLI\n' "$_cmd"
    printf '\n'
    printf '%sCheck your setup%s\n' "$BOLD" "$RESET"
    printf '  %-24s check services and connections\n' "$_cmd doctor"
    printf '\n'
    printf '%sManage AAP Bridge%s\n' "$BOLD" "$RESET"
    printf '  %-24s show running services\n' "$_cmd status"
    printf '  %-24s stop services\n' "$_cmd stop"
    printf '  %-24s start services\n' "$_cmd start"
    printf '  %-24s follow logs\n' "$_cmd logs"
    printf '  %-24s uninstall, keeping your data\n' "$_cmd uninstall"
    printf '\n'
}

# --- Container journey helpers ---------------------------------------------

image_present() { podman image exists "$1" >/dev/null 2>&1; }

image_revision() {
    podman image inspect --format "{{index .Config.Labels \"$REVISION_LABEL\"}}" "$1" 2>/dev/null
}

# An image counts as current only when it was built by this installer from the
# revision now being installed.
image_current() {
    [ -n "$REV" ] || return 1
    image_present "$1" || return 1
    [ "$(image_revision "$1")" = "$REV" ]
}

build_one() {
    _bimage="$1"; shift
    if [ -n "$REV" ]; then
        podman build --label "$REVISION_LABEL=$REV" -t "$_bimage" "$@"
    else
        podman build -t "$_bimage" "$@"
    fi
}

# build_image <label> <state-var> <image> <podman build args...>
build_image() {
    _label="$1"; _var="$2"; _image="$3"; shift 3
    if [ "${AAP_BRIDGE_REBUILD:-0}" != "1" ] && image_current "$_image"; then
        item_ok "$_label" "already built"
        eval "$_var=reused"
        detail "$_image at $REV"
        return 0
    fi
    if run_stage "$_label" "building" build_one "$_image" "$@"; then
        item_ok "$_label"
        eval "$_var=built"
        detail "$_image"
        return 0
    fi
    item_fail "$_label" "failed"
    eval "$_var=failed"
    return 1
}

image_state() {
    case "$1" in
        built)   item_ok "$2" "built" ;;
        reused)  item_ok "$2" "already built" ;;
        failed)  item_fail "$2" "failed" ;;
        *)       item_skip "$2" "not built" ;;
    esac
}

build_failed() {
    printf '\n%sContainer setup could not be completed%s\n\n' "$BOLD" "$RESET"
    image_state "$S_CLI" "CLI"
    image_state "$S_API" "API"
    image_state "$S_UI" "Web UI"
    printf '\nYour workspace has been kept:\n'
    printf '  %s%s%s\n' "$BOLD" "$(display_path "$WORKSPACE")" "$RESET"
    printf '\nImages that built are kept too, so you can fix the problem and\n'
    printf 'run this installer again - it resumes from here.\n'
    printf '\nDetails:\n'
    printf '  %s%s%s\n' "$BOLD" "$(display_path "$LOG")" "$RESET"
    log_tail
    printf '\n'
    exit 1
}

# check_image <label> <reference>
check_image() {
    if image_present "$2"; then
        detail "$1: $2 (already pulled)"
        return 0
    fi
    if run_stage "$1" "checking" podman manifest inspect "$2"; then
        detail "$1: $2"
        return 0
    fi
    printf '  %s✘%s %s\n\n' "$RED" "$RESET" "$1"
    printf '%s is not available to your account.\n\n' "$2"
    printf 'Check your Red Hat subscription entitlements, or log in as a\n'
    printf 'different user with:\n'
    printf '  %spodman login %s%s\n\n' "$BOLD" "$REGISTRY" "$RESET"
    printf 'No images were built.\n\n'
    exit 1
}

# A workspace configured by the CLI journey has a database-only compose.yml,
# which is not the stack.
workspace_compose_ok() {
    [ -f "$WORKSPACE/compose.yml" ] && grep -q 'aap-bridge-ui' "$WORKSPACE/compose.yml" 2>/dev/null
}

compose() { ( cd "$WORKSPACE" && podman compose "$@" ); }

# One setting from the workspace .env, or a default.
env_port() {
    _v=$(sed -n "s/^$1=//p" "$WORKSPACE/.env" 2>/dev/null | tail -n 1)
    printf '%s' "${_v:-$2}"
}

# Whether something is already listening on a host port.
#
# The stack publishes fixed ports, and a container that cannot bind one starts
# and then never answers - which the verification stage reports honestly but
# cannot explain. Saying up front which port is taken turns a mysterious
# half-working install into one obvious sentence.
port_in_use() {
    if has ss; then
        ss -ltn 2>/dev/null | grep -q ":$1[[:space:]]"
    elif has netstat; then
        netstat -ltn 2>/dev/null | grep -q "[:.]$1[[:space:]]"
    else
        return 1
    fi
}

# Rewrite one setting in the workspace .env, in place.
set_env_port() {
    _file="$WORKSPACE/.env"
    if grep -q "^$1=" "$_file" 2>/dev/null; then
        sed -i.bak "s/^$1=.*/$1=$2/" "$_file" && rm -f "$_file.bak"
    else
        printf '%s=%s\n' "$1" "$2" >> "$_file"
    fi
}

# Offer a free port instead of the one that is taken. Returns the port to use.
choose_free_port() {
    _from=$1
    _n=$((_from + 1))
    while [ "$_n" -lt $((_from + 50)) ]; do
        port_in_use "$_n" || { printf '%s' "$_n"; return 0; }
        _n=$((_n + 1))
    done
    printf '%s' "$_from"
}

# A port that is taken is a problem this installer can solve, and one the user
# would otherwise meet as a service that starts and never answers. Suggest the
# next free port, take any other, and record the answer where everything else
# reads it.
check_ports() {
    section "Checking ports"

    _conflicts=0
    for _entry in "AAP_BRIDGE_DB_PORT:$DB_PORT:database" \
                  "AAP_BRIDGE_API_PORT:$API_PORT:API engine" \
                  "AAP_BRIDGE_UI_PORT:$UI_PORT:Web UI"; do
        _key=${_entry%%:*}
        _rest=${_entry#*:}
        _port=${_rest%%:*}
        _what=${_rest#*:}

        if ! port_in_use "$_port"; then
            detail "port $_port free for the $_what"
            continue
        fi

        _conflicts=$((_conflicts + 1))
        warn "Port $_port is already in use  ${DIM}needed by the $_what${RESET}"

        if [ "$INPUT" = "none" ]; then
            continue
        fi

        _suggested=$(choose_free_port "$_port")
        printf '\n'
        ask "  Port for the $_what [$_suggested]: " "$_suggested"
        _chosen=$ANSWER
        case "$_chosen" in
            ''|*[!0-9]*)
                warn "Not a port number - keeping $_port"
                continue
                ;;
        esac
        if port_in_use "$_chosen"; then
            warn "Port $_chosen is also in use - keeping $_port"
            continue
        fi

        set_env_port "$_key" "$_chosen"
        case "$_key" in
            AAP_BRIDGE_DB_PORT)
                DB_PORT=$_chosen
                # The connection string embeds the port, so it moves too, or
                # the database would be published where nothing looks for it.
                sed -i.bak "s|@localhost:$_port/|@localhost:$_chosen/|" "$WORKSPACE/.env" \
                    && rm -f "$WORKSPACE/.env.bak"
                ;;
            AAP_BRIDGE_API_PORT) API_PORT=$_chosen ;;
            *) UI_PORT=$_chosen ;;
        esac
        ok "$_what will use port $_chosen"
        printf '\n'
    done

    if [ "$_conflicts" = "0" ]; then
        ok "Ports available"
    fi
    return 0
}

# `podman compose up -d` returns once containers have *started*, not once the
# service inside is ready. Poll for readiness instead, so nothing is reported
# working before it is.
wait_for_db() {
    _deadline=$(( $(date +%s) + 120 ))
    while :; do
        _cid=$(compose ps -q db 2>/dev/null | head -n 1) || _cid=""
        if [ -n "$_cid" ] && podman exec "$_cid" pg_isready -q >/dev/null 2>&1; then
            return 0
        fi
        [ "$(date +%s)" -ge "$_deadline" ] && return 1
        sleep 2
    done
}

start_db() { compose up -d db && wait_for_db; }

wait_for_http() {
    _deadline=$(( $(date +%s) + "$2" ))
    while :; do
        if curl -fsS -o /dev/null --max-time 5 "$1" 2>/dev/null; then
            return 0
        fi
        [ "$(date +%s)" -ge "$_deadline" ] && return 1
        sleep 2
    done
}

# The workspace's own management interface: `./aap-bridge status|start|stop|
# logs|uninstall`, and any CLI command passed straight through. Podman Compose
# stays underneath, but AAP Bridge owns how it is operated.
# The launcher and the uninstaller both come out of the source that has
# already been fetched. There is deliberately no second download: the run that
# produced this comment fetched the installer, cloned the source, and built
# three images, and then failed on an extra HTTP request for a file it was
# already holding a copy of.
#
# Returns 1 if either is missing, because both are part of the installation
# rather than extras - `aap-bridge` is how the thing is operated.
write_workspace_tools() {
    if [ -n "$SRC" ] && [ -f "$SRC/deploy/aap-bridge" ] && [ -f "$SRC/scripts/uninstall.sh" ]; then
        cp "$SRC/deploy/aap-bridge" "$WORKSPACE/aap-bridge" || return 1
        chmod +x "$WORKSPACE/aap-bridge" || return 1

        # Uninstall lives next to it, so removing AAP Bridge never means going
        # back to find the URL the installer came from.
        cp "$SRC/scripts/uninstall.sh" "$WORKSPACE/uninstall.sh" || return 1
        chmod +x "$WORKSPACE/uninstall.sh" || return 1
        return 0
    fi

    # No source fetched this run, which only happens when both are already
    # here - anything missing makes the source required. Nothing to do is a
    # success.
    if [ -x "$WORKSPACE/aap-bridge" ] && [ -x "$WORKSPACE/uninstall.sh" ]; then
        detail "keeping the launcher and uninstaller already in the workspace"
        return 0
    fi
    return 1
}

#: Marks a launcher this installer wrote into a bin directory, so a re-run can
#: replace its own shim and leave anything else alone.
SHIM_MARKER="# AAP Bridge container launcher"

# Put `aap-bridge` on PATH for the container installation too.
#
# How AAP Bridge is deployed is a choice made once at install time; having to
# remember it at every invocation - `aap-bridge` here, `./aap-bridge` from one
# particular directory there - is the installation leaking into daily use. The
# shim is three lines and delegates to the workspace launcher.
#
# Sets SHIM_PATH when one is in place. Never overwrites a file it did not
# write: an existing `aap-bridge` is more likely the CLI installation than
# something to clobber.
install_command_shim() {
    SHIM_PATH=""
    [ -n "$BIN_DIR" ] || return 0

    if [ -e "$BIN_DIR/aap-bridge" ] && ! grep -q "$SHIM_MARKER" "$BIN_DIR/aap-bridge" 2>/dev/null; then
        detail "$BIN_DIR/aap-bridge exists and was not written by this installer - left alone"
        return 0
    fi

    mkdir -p "$BIN_DIR" 2>/dev/null || return 0
    cat > "$BIN_DIR/aap-bridge" <<SHIM || return 0
#!/bin/sh
$SHIM_MARKER
# Runs the AAP Bridge launcher in $WORKSPACE, from wherever you are.
# AAP_BRIDGE_WORKSPACE, or --workspace <dir>, points it at another workspace.
exec "$WORKSPACE/aap-bridge" "\$@"
SHIM
    chmod +x "$BIN_DIR/aap-bridge" 2>/dev/null || return 0
    SHIM_PATH="$BIN_DIR/aap-bridge"
    return 0
}

# ---------------------------------------------------------------------------
# Everything above is a definition. Execution starts on the last line, so that
# a `curl ... | sh` bootstrap has read the whole script before anything can
# finish: a shell that exits while curl is still writing leaves it reporting
# "Failure writing output to destination" over a run the user cancelled on
# purpose.
#
# For the same reason, quitting at any prompt returns through main rather than
# calling exit from the middle of the script, and every one of them ends in the
# same sentence. A non-zero status is reserved for something going wrong.
# ---------------------------------------------------------------------------

main() {
    resolve_source_and_workspace

    HELP_ONLY=0
    FAILED=0

    if ! choose_journey "$@"; then
        [ "$HELP_ONLY" = "1" ] && return 0
        [ "$FAILED" = "1" ] && return 1
        printf '\nSetup cancelled.\n\n'
        return 0
    fi

    describe_plan

    if ! choose_workspace; then
        [ "$FAILED" = "1" ] && return 1
        printf '\nSetup cancelled.\n\n'
        return 0
    fi

    case "$MODE" in
        cli)       journey_cli ;;
        container) journey_container ;;
    esac
}

main "$@"
