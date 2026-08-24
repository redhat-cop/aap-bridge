#!/bin/sh
# AAP Bridge - uninstaller
#
# Removes AAP Bridge and keeps your migration work, or removes both if you say
# so explicitly. Handles either installation: the containers, the `aap-bridge`
# command, or both.
#
#   curl -LsSf https://raw.githubusercontent.com/redhat-cop/aap-bridge/main/scripts/uninstall.sh | sh
#
# or, from a workspace the installer created:
#
#   ./aap-bridge uninstall

# Environment overrides:
#   AAP_BRIDGE_WORKSPACE=<dir>   Workspace to act on (default: $HOME/aap-migration)
#   AAP_BRIDGE_VERBOSE=1         Show command output and implementation detail
#
# There is no flag to remove everything without being asked. Deleting a
# workspace destroys API tokens and migration state that nothing else holds, so
# it is typed out in full or it does not happen.

set -eu

# The images this installer builds, and only these. The base images they are
# built from - UBI, Node.js, PostgreSQL - are shared with anything else on the
# machine that uses them, so removing those is not ours to do.
CLI_IMAGE="localhost/aap-bridge:latest"
API_IMAGE="localhost/aap-bridge-api:latest"
UI_IMAGE="localhost/aap-bridge-ui:latest"

# ---------------------------------------------------------------------------
# Output helpers - the same vocabulary as the installer.
# ---------------------------------------------------------------------------

if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
    BOLD=$(printf '\033[1m'); RED=$(printf '\033[31m')
    GREEN=$(printf '\033[32m'); YELLOW=$(printf '\033[33m')
    DIM=$(printf '\033[2m'); RESET=$(printf '\033[0m')
else
    BOLD=''; RED=''; GREEN=''; YELLOW=''; DIM=''; RESET=''
fi

ok()      { printf '  %s✔%s %s\n' "$GREEN" "$RESET" "$1"; }
warn()    { printf '  %s!%s %s\n' "$YELLOW" "$RESET" "$1"; }
absent()  { printf '  %s•%s %s\n' "$DIM" "$RESET" "$1"; }
die()     { printf '\n  %s✘ %s%s\n\n' "$RED" "$1" "$RESET" >&2; exit 1; }
section() { printf '\n%s%s%s\n\n' "$BOLD" "$1" "$RESET"; }

case "${AAP_BRIDGE_VERBOSE:-0}" in
    0|""|false|no) VERBOSE=0 ;;
    *) VERBOSE=1 ;;
esac

detail() { [ "$VERBOSE" = "1" ] && printf '  %s%s%s\n' "$DIM" "$1" "$RESET"; return 0; }

has() { command -v "$1" >/dev/null 2>&1; }

# --- Live steps -------------------------------------------------------------
#
# Removal is several seconds of stopping containers and deleting images. A
# report printed only once it is all over cannot be told apart from a hang, so
# each step appears as it starts and turns into its result in place:
#
#   →/⠹ starting or running     ✔ done     ! done, with a caveat     ✘ failed
#
# One line per step, rewritten rather than reprinted, so what is left on screen
# afterwards is the list of what happened and nothing else.

if [ -t 1 ] && [ "$VERBOSE" != "1" ]; then LIVE=1; else LIVE=0; fi

# POSIX only guarantees whole seconds, so check before relying on a fraction.
if sleep 0.1 2>/dev/null; then SPIN_DELAY=0.1; else SPIN_DELAY=1; fi

spinner_frame() {
    case "$1" in
        0) printf '⠋' ;; 1) printf '⠙' ;; 2) printf '⠹' ;; 3) printf '⠸' ;;
        4) printf '⠼' ;; 5) printf '⠴' ;; 6) printf '⠦' ;; *) printf '⠧' ;;
    esac
}

# "4 services", "1 container" - the counts tie each step back to what the check
# above reported finding.
plural() {
    if [ "$1" = "1" ]; then printf '1 %s' "$2"; else printf '%s %ss' "$1" "$2"; fi
}

STEP_ERROR=""

# step_run <running label> <done label> <command...>
#
# Returns the command's status. On failure the reason is left in STEP_ERROR for
# the caller to show, since only the caller knows whether it is fatal.
step_run() {
    _running="$1"; _done="$2"; shift 2
    _errfile="${TMPDIR:-/tmp}/aap-bridge-uninstall.$$"

    if [ "$LIVE" != "1" ]; then
        printf '  %s→%s %s\n' "$DIM" "$RESET" "$_running"
        _rc=0
        "$@" >"$_errfile" 2>&1 || _rc=$?
    else
        "$@" >"$_errfile" 2>&1 &
        _pid=$!
        _start=$(date +%s)
        _frame=0
        while kill -0 "$_pid" 2>/dev/null; do
            _elapsed=$(( $(date +%s) - _start ))
            # Only worth showing once a step is slow enough to wonder about.
            if [ "$_elapsed" -ge 5 ]; then
                printf '\r\033[K  %s%s%s %s  %s%ss%s' "$DIM" "$(spinner_frame "$_frame")" \
                    "$RESET" "$_running" "$DIM" "$_elapsed" "$RESET"
            else
                printf '\r\033[K  %s%s%s %s' "$DIM" "$(spinner_frame "$_frame")" \
                    "$RESET" "$_running"
            fi
            _frame=$(( (_frame + 1) % 8 ))
            sleep "$SPIN_DELAY"
        done
        _rc=0
        wait "$_pid" || _rc=$?
        printf '\r\033[K'
    fi

    if [ "$_rc" = "0" ]; then
        STEP_ERROR=""
        ok "$_done"
    else
        # Prefer the lines that say what went wrong over whatever the command
        # printed on its way there: a partly-successful `podman rmi` reports
        # every tag it did remove before the one it could not.
        STEP_ERROR=$(grep -i 'error' "$_errfile" 2>/dev/null | tail -n 2)
        [ -n "$STEP_ERROR" ] || STEP_ERROR=$(tail -n 2 "$_errfile" 2>/dev/null)
        printf '  %s✘%s %s\n' "$RED" "$RESET" "$_running"
    fi
    rm -f "$_errfile"
    return "$_rc"
}

# Stop here, saying why and what was therefore left alone. Removing things in
# an order where each step depends on the last means a failure has to halt: the
# alternative is deleting a workspace whose containers are still running.
halt() {
    if [ -n "$STEP_ERROR" ]; then
        printf '\n'
        printf '%s\n' "$STEP_ERROR" | sed "s/^[[:space:]]*/    ${DIM}/;s/\$/${RESET}/"
    fi
    printf '\n%sRemoval stopped.%s\n\n' "$BOLD" "$RESET"
    printf '%s\n\n' "$1"
    # Reports and returns; the caller decides to stop. Nothing calls exit from
    # the middle of this script - see the note above main.
    return 1
}

display_path() {
    if [ -n "${HOME:-}" ]; then
        case "$1" in
            "$HOME") printf '$HOME'; return 0 ;;
            "$HOME"/*) printf '$HOME/%s' "${1#"$HOME"/}"; return 0 ;;
        esac
    fi
    printf '%s' "$1"
}

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

# When piped from curl, stdin carries the script, so answers come from the
# controlling terminal instead.
if [ -t 0 ]; then
    INPUT="stdin"
elif ( : < /dev/tty ) 2>/dev/null; then
    INPUT="tty"
else
    INPUT="none"
fi

ask() {
    printf '%s' "$1"
    case "$INPUT" in
        stdin) read -r ANSWER || ANSWER="" ;;
        tty)   read -r ANSWER < /dev/tty || ANSWER="" ;;
        none)  ANSWER=""; printf '\n' ;;
    esac
    if [ -z "$ANSWER" ]; then
        ANSWER="$2"
    fi
    return 0
}

# ---------------------------------------------------------------------------
# What is actually here
# ---------------------------------------------------------------------------

resolve_workspace() {
    if [ -n "${AAP_BRIDGE_WORKSPACE:-}" ]; then
        WORKSPACE=$(resolve_path "$AAP_BRIDGE_WORKSPACE")
    elif [ -f "$PWD/compose.yml" ] && [ -f "$PWD/.env" ]; then
        # Run from inside a workspace, which is what ./aap-bridge uninstall does.
        WORKSPACE="$PWD"
    elif [ -n "${HOME:-}" ]; then
        WORKSPACE="$HOME/aap-migration"
    else
        WORKSPACE="$PWD/aap-migration"
    fi
}

compose() { ( cd "$WORKSPACE" && podman compose "$@" ); }

# A compose file is enough to ask compose what it owns. Deliberately not
# matched against the service names of the full stack: the CLI installation
# writes a database-only compose.yml, and that database is AAP Bridge's to
# clean up too.
workspace_has_compose() { [ -f "$WORKSPACE/compose.yml" ]; }

image_present() { [ "$HAS_PODMAN" = "1" ] && podman image exists "$1" >/dev/null 2>&1; }

# Containers this workspace's compose project owns, running or not.
container_ids() {
    [ "$HAS_PODMAN" = "1" ] || return 0
    workspace_has_compose || return 0
    compose ps -a -q 2>/dev/null || true
}

running_container_ids() {
    [ "$HAS_PODMAN" = "1" ] || return 0
    workspace_has_compose || return 0
    compose ps -q 2>/dev/null || true
}

installed_command() {
    has aap-bridge && command -v aap-bridge || printf ''
}

#: The container installation puts a small `aap-bridge` on PATH that delegates
#: to the workspace launcher. It is a file to delete, not a uv tool to
#: uninstall, and telling them apart is the difference between removing it and
#: reporting that it could not be removed.
SHIM_MARKER="# AAP Bridge container launcher"

command_is_shim() {
    [ -n "$COMMAND_PATH" ] && grep -q "$SHIM_MARKER" "$COMMAND_PATH" 2>/dev/null
}

count_lines() {
    if [ -z "$1" ]; then printf '0'; else printf '%s' "$1" | grep -c . ; fi
}

# How AAP Bridge was installed here: "cli", "container", or "unknown".
#
# The installer records it, because the two installations have genuinely
# different parts and listing the other one's is noise - a CLI installation
# never had application images, so "No AAP Bridge images" answers a question
# nobody asked. Workspaces created before the record existed are inferred from
# what is actually there.
read_install_mode() {
    _record="$WORKSPACE/.aap-bridge-install"
    if [ -f "$_record" ]; then
        _mode=$(sed -n 's/^installation_mode=//p' "$_record" 2>/dev/null | tail -n 1)
        case "$_mode" in
            cli|container) printf '%s' "$_mode"; return 0 ;;
        esac
    fi

    if [ -f "$WORKSPACE/compose.yml" ] \
        && grep -q 'aap-bridge-ui' "$WORKSPACE/compose.yml" 2>/dev/null; then
        printf 'container'
    elif [ "$IMAGE_COUNT" -gt 0 ]; then
        printf 'container'
    elif [ -n "$COMMAND_PATH" ]; then
        printf 'cli'
    else
        printf 'unknown'
    fi
}

# Which of the four states this machine is in. Treating them as states rather
# than as a pile of independent checks is what makes every path - including
# running the uninstaller twice - have an obvious answer.
#
#   installed   some part of the runtime is here
#   data-only   the runtime is gone, the migration workspace is not
#   removed     nothing left at all
install_state() {
    if [ "$CONTAINER_COUNT" -gt 0 ] || [ "$IMAGE_COUNT" -gt 0 ] || [ -n "$COMMAND_PATH" ]; then
        printf 'installed'
    elif [ "$WORKSPACE_FOUND" = "1" ]; then
        printf 'data-only'
    else
        printf 'removed'
    fi
}

# Sets everything the rest of the script decides from, and shows it.
check_installation() {
    HAS_PODMAN=0
    has podman && HAS_PODMAN=1

    WORKSPACE_FOUND=0
    [ -d "$WORKSPACE" ] && WORKSPACE_FOUND=1

    CONTAINER_COUNT=$(count_lines "$(container_ids)")
    RUNNING_COUNT=$(count_lines "$(running_container_ids)")

    IMAGES=""
    for image in "$CLI_IMAGE" "$API_IMAGE" "$UI_IMAGE"; do
        image_present "$image" && IMAGES="$IMAGES $image"
    done
    IMAGE_COUNT=0
    for _ in $IMAGES; do IMAGE_COUNT=$((IMAGE_COUNT + 1)); done

    COMMAND_PATH=$(installed_command)
    INSTALL_MODE=$(read_install_mode)

    printf 'Checking AAP Bridge\n\n'

    if [ "$WORKSPACE_FOUND" = "1" ]; then
        ok "Workspace found"
        detail "$WORKSPACE"
    else
        absent "No workspace at $(display_path "$WORKSPACE")"
    fi

    if [ "$RUNNING_COUNT" -gt 0 ]; then
        ok "$(plural "$RUNNING_COUNT" "running service")"
    elif [ "$CONTAINER_COUNT" -gt 0 ]; then
        absent "No running services"
    else
        absent "No AAP Bridge containers"
    fi

    if [ "$CONTAINER_COUNT" -gt 0 ]; then
        ok "$(plural "$CONTAINER_COUNT" container) found"
    fi

    # Only report on the parts this installation has. The check answers "is my
    # installation intact?", not "here is everything AAP Bridge knows how to
    # look for".
    if [ "$IMAGE_COUNT" -gt 0 ]; then
        ok "$(plural "$IMAGE_COUNT" "AAP Bridge image") found"
        for image in $IMAGES; do detail "$image"; done
    elif [ "$INSTALL_MODE" = "container" ]; then
        absent "No AAP Bridge images"
    fi

    if [ -n "$COMMAND_PATH" ]; then
        ok "aap-bridge command installed"
        detail "$COMMAND_PATH"
    else
        absent "No aap-bridge command installed"
    fi
}

# ---------------------------------------------------------------------------
# What to remove
# ---------------------------------------------------------------------------

# Sets MODE. Returns 1 when the user cancels, 2 when there is no terminal to
# ask on - a cancel is an outcome, an unanswerable prompt is a failure.
choose_mode() {
    printf '\n%sChoose what you want to remove:%s\n\n' "$BOLD" "$RESET"
    printf '  %s1. Uninstall AAP Bridge%s\n' "$BOLD" "$RESET"
    case "$INSTALL_MODE" in
        cli)       printf '     Remove the aap-bridge command and the bundled database\n' ;;
        container) printf '     Remove the AAP Bridge containers, images, and command\n' ;;
        *)         printf '     Remove the parts of AAP Bridge found above\n' ;;
    esac
    printf '     Keep your migration workspace and data\n\n'
    printf '  %s2. Remove AAP Bridge and all data%s\n' "$BOLD" "$RESET"
    printf '     Permanently remove everything, including configuration,\n'
    printf '     API tokens, and migration data\n\n'
    printf '  %sq. Cancel%s\n\n' "$BOLD" "$RESET"

    MODE="uninstall"
    if [ "$INPUT" = "none" ]; then
        printf 'No terminal available to choose. Run this from a terminal.\n\n'
        return 2
    fi

    while :; do
        ask "Choose [1]: " "1"
        case "$ANSWER" in
            1) MODE="uninstall"; return 0 ;;
            2) MODE="remove"; return 0 ;;
            [qQ] | [qQ][uU][iI][tT] | [eE][xX][iI][tT])
                printf '\nCancelled. Nothing was removed.\n\n'
                return 1
                ;;
            *) printf '  %sEnter 1, 2, or q.%s\n' "$DIM" "$RESET" ;;
        esac
    done
}

# Removing everything destroys the only copy of the API tokens and the
# migration state. A y/n prompt is too easy to answer without reading.
confirm_remove() {
    printf '\n%sAAP Bridge - Remove Everything%s\n\n' "$BOLD" "$RESET"
    printf 'This will permanently remove:\n\n'
    # Only what is actually here. Listing containers and images that were
    # already gone makes the warning easier to dismiss, which is the opposite
    # of what a warning before an irreversible step is for.
    [ "$CONTAINER_COUNT" -gt 0 ] && printf '  • AAP Bridge containers\n'
    [ "$IMAGE_COUNT" -gt 0 ] && printf '  • AAP Bridge images\n'
    [ -n "$COMMAND_PATH" ] && printf '  • The aap-bridge command\n'
    workspace_has_compose && printf '  • PostgreSQL migration state\n'
    if [ "$WORKSPACE_FOUND" = "1" ]; then
        printf '  • Configuration and API tokens\n'
        printf '  • Exports, transformed data, reports, and logs\n'
    fi
    printf '\n'
    if [ "$WORKSPACE_FOUND" = "1" ]; then
        printf 'Workspace:\n'
        printf '  %s%s%s\n\n' "$BOLD" "$WORKSPACE" "$RESET"
    fi
    printf '%sThis cannot be undone.%s\n\n' "$BOLD" "$RESET"

    ask "Type REMOVE to continue: " ""
    if [ "$ANSWER" != "REMOVE" ]; then
        printf '\nCancelled. Nothing was removed.\n\n'
        return 1
    fi
    return 0
}

# ---------------------------------------------------------------------------
# Do it
#
# Each step is one command, so a failure lands on the step that caused it and
# the steps after it do not run. Steps with nothing to do are skipped rather
# than reported: the check above already said what was there.
# ---------------------------------------------------------------------------

run_removal() {
    if [ "$MODE" = "remove" ]; then
        section "Removing AAP Bridge"
    else
        section "Uninstalling AAP Bridge"
    fi

    if [ "$RUNNING_COUNT" -gt 0 ]; then
        step_run "Stopping $(plural "$RUNNING_COUNT" service)" \
                 "$(plural "$RUNNING_COUNT" service) stopped" \
                 compose stop \
            || { halt "Nothing has been removed."; return 1; }
    fi

    if [ "$CONTAINER_COUNT" -gt 0 ]; then
        step_run "Removing $(plural "$CONTAINER_COUNT" container)" \
                 "$(plural "$CONTAINER_COUNT" container) removed" \
                 compose down \
            || { halt "The images, command, and workspace have not been removed."; return 1; }
    fi

    # `down -v` removes the named volume holding PostgreSQL's data, which is the
    # difference between the two modes as far as the stack is concerned. It runs
    # even when no containers were left, because the volume outlives them: a
    # stack that was already brought down still has its database data on disk,
    # and reporting "completely removed" over it would be false. It has to
    # happen before the workspace goes, since compose reads the compose file to
    # know which volumes are the project's.
    if [ "$MODE" = "remove" ] && workspace_has_compose; then
        step_run "Removing database data" "Database data removed" \
                 compose down -v \
            || { halt "The images, command, and workspace have not been removed."; return 1; }
    fi

    if [ "$IMAGE_COUNT" -gt 0 ]; then
        # shellcheck disable=SC2086  # IMAGES is a deliberate space-separated list
        step_run "Removing $(plural "$IMAGE_COUNT" "AAP Bridge image")" \
                 "$(plural "$IMAGE_COUNT" "AAP Bridge image") removed" \
                 podman rmi $IMAGES \
            || { halt "The command and workspace have not been removed."; return 1; }
    fi

    # A command that will not uninstall is a nuisance, not a reason to stop: it
    # leaves nothing in an inconsistent state, and the path is printed so it can
    # be dealt with by hand.
    if [ -n "$COMMAND_PATH" ]; then
        if command_is_shim; then
            if ! step_run "Removing the aap-bridge command" "Command removed" \
                          rm -f "$COMMAND_PATH"; then
                warn "The aap-bridge command is still installed at $COMMAND_PATH"
            fi
        elif has uv; then
            if ! step_run "Removing the aap-bridge command" "Command removed" \
                          uv tool uninstall aap-bridge; then
                warn "The aap-bridge command is still installed at $COMMAND_PATH"
            fi
        else
            warn "The aap-bridge command is still installed at $COMMAND_PATH"
            detail "uv is not available to remove it"
        fi
    fi

    if [ "$MODE" = "remove" ] && [ "$WORKSPACE_FOUND" = "1" ]; then
        # Refuse anything that is not recognisably a workspace: this is an
        # rm -rf of a path that arrived from an environment variable.
        if [ -f "$WORKSPACE/.env" ] || [ -f "$WORKSPACE/config/config.yaml" ]; then
            if ! step_run "Removing the workspace" "Workspace removed" \
                          rm -rf "$WORKSPACE"; then
                warn "The workspace is still at $WORKSPACE"
            fi
        else
            warn "$(display_path "$WORKSPACE") does not look like an AAP Bridge workspace"
            detail "no .env and no config/config.yaml - left alone"
        fi
    fi

    return 0
}

# ---------------------------------------------------------------------------
# What is left
# ---------------------------------------------------------------------------

report_result() {
    if [ "$MODE" = "remove" ]; then
        printf '\n%sAAP Bridge has been completely removed.%s\n\n' "$GREEN$BOLD" "$RESET"
        # Only worth saying when there were container images in play at all.
        if [ "$IMAGE_COUNT" -gt 0 ] || [ "$CONTAINER_COUNT" -gt 0 ]; then
            printf 'Base container images were kept because other applications may use them:\n'
            printf '  • UBI\n'
            printf '  • Node.js\n'
            printf '  • PostgreSQL\n\n'
        fi
        return 0
    fi

    printf '\n%sUninstall complete%s\n\n' "$GREEN$BOLD" "$RESET"

    if [ "$WORKSPACE_FOUND" = "1" ]; then
        printf 'Your migration workspace was kept:\n\n'
        printf '  %s%s%s\n\n' "$BOLD" "$(display_path "$WORKSPACE")" "$RESET"
        printf 'It still contains:\n'
        ok "Configuration and API tokens"
        ok "Migration files"
        ok "Database data"
        printf '\nReinstall AAP Bridge anytime to continue using this workspace.\n\n'
    else
        printf 'No migration workspace was present, so nothing was kept.\n\n'
    fi
    return 0
}

already_uninstalled_notice() {
    printf '\n%sAAP Bridge is already uninstalled.%s\n\n' "$BOLD" "$RESET"
}

# The runtime is gone but the migration workspace is not. "Already uninstalled"
# would be wrong here - it implies nothing is left to deal with, and what is
# left is the user's tokens and migration data. Nor is sending them to `rm -rf`
# acceptable when this script already knows how to remove it safely.
#
# Returns 1 when the data is kept, so nothing further runs.
offer_data_removal() {
    printf '\n%sAAP Bridge is not installed.%s\n\n' "$BOLD" "$RESET"
    printf 'Migration data is still available at:\n'
    printf '  %s%s%s\n\n' "$BOLD" "$(display_path "$WORKSPACE")" "$RESET"
    printf '%sChoose what you want to do:%s\n\n' "$BOLD" "$RESET"
    printf '  %s1. Keep migration data%s\n' "$BOLD" "$RESET"
    printf '     You can reuse it if you reinstall AAP Bridge\n\n'
    printf '  %s2. Remove all migration data%s\n' "$BOLD" "$RESET"
    printf '     Permanently delete configuration, API tokens,\n'
    printf '     migration files, and database data\n\n'
    printf '  %sq. Cancel%s\n\n' "$BOLD" "$RESET"

    if [ "$INPUT" = "none" ]; then
        printf 'No terminal available to choose. Run this from a terminal.\n\n'
        return 2
    fi

    while :; do
        ask "Choose [1]: " "1"
        case "$ANSWER" in
            1)
                printf '\n%sMigration data kept.%s\n\n' "$BOLD" "$RESET"
                printf '  %s%s%s\n\n' "$BOLD" "$(display_path "$WORKSPACE")" "$RESET"
                return 1
                ;;
            2) MODE="remove"; return 0 ;;
            [qQ] | [qQ][uU][iI][tT] | [eE][xX][iI][tT])
                printf '\nCancelled. Nothing was removed.\n\n'
                return 1
                ;;
            *) printf '  %sEnter 1, 2, or q.%s\n' "$DIM" "$RESET" ;;
        esac
    done
}

# ---------------------------------------------------------------------------
# Everything above is a definition. Execution starts here, at the very end of
# the file, so that a `curl ... | sh` bootstrap has already been read in full
# before anything can finish: a script that exits while curl is still writing
# leaves it reporting "Failed writing body" over a run that went perfectly.
#
# For the same reason, expected outcomes - nothing installed, a cancelled
# prompt - return through main rather than calling exit from the middle of the
# script. A non-zero status is reserved for something actually going wrong.
# ---------------------------------------------------------------------------

# Run a prompt and translate its outcome into main's return value: a cancel is
# a successful run that did nothing, an unanswerable prompt is a failure.
answered() {
    "$@" && return 0
    case "$?" in
        1) return 0 ;;
        *) return 1 ;;
    esac
}

main() {
    resolve_workspace

    section "AAP Bridge - Uninstall"
    check_installation

    # Nothing to do is a normal outcome, not an error. Running the uninstaller
    # when you are not sure whether AAP Bridge is still installed should be
    # completely safe, and should say so plainly rather than handing back a
    # pile of Podman failures.
    case "$(install_state)" in
        removed)
            already_uninstalled_notice
            return 0
            ;;
        data-only)
            # Only the migration data is left; the choice is about that alone.
            answered offer_data_removal || return $?
            confirm_remove || return 0
            ;;
        *)
            answered choose_mode || return $?
            if [ "$MODE" = "remove" ]; then
                confirm_remove || return 0
            fi
            ;;
    esac

    run_removal || return 1
    report_result
}

main "$@"
