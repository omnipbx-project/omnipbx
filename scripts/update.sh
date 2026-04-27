#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE=""
ENV_FILE=""
RUNTIME_DIR=""
STATUS_FILE=""
CHECK_FILE=""
VERSION_FILE=""
CHECK_ONLY="false"
FORCE="false"
NON_INTERACTIVE="false"
CURRENT_VERSION=""
TARGET_VERSION=""
LOCAL_BRANCH=""
UPSTREAM_REF=""
REMOTE_NAME=""
REMOTE_URL=""
LOCAL_COMMIT=""
REMOTE_COMMIT=""
COMMITS_AHEAD="0"
COMMITS_BEHIND="0"
REPO_DIRTY="false"
GIT_READY="false"
TRACKED_UPSTREAM="false"
CHECK_MESSAGE=""
CHECK_ERROR=""

log() {
  printf '\n[%s] %s\n' "$1" "$2"
}

fail() {
  local message="$1"
  write_status "error" "${message}" "${TARGET_VERSION:-}" "${STARTED_AT:-}" "$(_utc_now)"
  echo "Update failed: ${message}" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: update.sh [--project-root PATH] [--check-only] [--force] [--non-interactive]

Options:
  --project-root PATH   OmniPBX install root. Defaults to the script parent directory.
  --check-only          Check the tracked git branch without applying an update.
  --force               Restart the stack even if the local branch is already current.
  --non-interactive     Skip confirmation prompts.
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --project-root)
        PROJECT_ROOT="$2"
        shift 2
        ;;
      --check-only)
        CHECK_ONLY="true"
        shift
        ;;
      --force)
        FORCE="true"
        shift
        ;;
      --non-interactive)
        NON_INTERACTIVE="true"
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        echo "Unknown argument: $1" >&2
        usage >&2
        exit 2
        ;;
    esac
  done
}

ensure_privileges() {
  if [[ "${CHECK_ONLY}" == "true" ]]; then
    return 0
  fi
  if [[ "${EUID}" -ne 0 ]]; then
    exec sudo bash "$0" "$@"
  fi
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Missing required command: $1" >&2
    exit 2
  }
}

setup_paths() {
  PROJECT_ROOT="$(cd "${PROJECT_ROOT}" && pwd)"
  COMPOSE_FILE="${PROJECT_ROOT}/deploy/compose.yaml"
  ENV_FILE="${PROJECT_ROOT}/deploy/.env"
  RUNTIME_DIR="${OMNIPBX_RUNTIME_DIR:-${PROJECT_ROOT}/deploy/runtime}"
  STATUS_FILE="${RUNTIME_DIR}/update-status.json"
  CHECK_FILE="${RUNTIME_DIR}/update-check.json"
  VERSION_FILE="${PROJECT_ROOT}/VERSION"

  [[ -f "${COMPOSE_FILE}" ]] || {
    echo "Compose file not found: ${COMPOSE_FILE}" >&2
    exit 2
  }
  mkdir -p "${RUNTIME_DIR}"
}

_utc_now() {
  python3 - <<'PY'
from datetime import UTC, datetime
print(datetime.now(UTC).isoformat().replace("+00:00", "Z"))
PY
}

current_version() {
  if [[ -f "${VERSION_FILE}" ]]; then
    tr -d '\n' < "${VERSION_FILE}"
    return 0
  fi
  python3 - "${ENV_FILE}" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
if env_path.exists():
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key == "OMNIPBX_APP_VERSION":
            print(value.strip())
            raise SystemExit(0)
print("0.0.0")
PY
}

git_output() {
  GIT_TERMINAL_PROMPT=0 git -C "${PROJECT_ROOT}" "$@"
}

set_check_failure() {
  local message="$1"
  local detail="${2:-}"
  GIT_READY="${3:-false}"
  TRACKED_UPSTREAM="${4:-false}"
  CHECK_MESSAGE="${message}"
  CHECK_ERROR="${detail}"
}

read_version_at_ref() {
  local ref="$1"
  local version
  version="$(git_output show "${ref}:VERSION" 2>/dev/null | tr -d '\n' || true)"
  if [[ -n "${version}" ]]; then
    printf '%s\n' "${version}"
  else
    printf '%s\n' "${CURRENT_VERSION}"
  fi
}

collect_git_status() {
  CURRENT_VERSION="$(current_version)"
  TARGET_VERSION="${CURRENT_VERSION}"
  LOCAL_BRANCH=""
  UPSTREAM_REF=""
  REMOTE_NAME=""
  REMOTE_URL=""
  LOCAL_COMMIT=""
  REMOTE_COMMIT=""
  COMMITS_AHEAD="0"
  COMMITS_BEHIND="0"
  REPO_DIRTY="false"
  GIT_READY="false"
  TRACKED_UPSTREAM="false"
  CHECK_MESSAGE=""
  CHECK_ERROR=""

  if ! git_output rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    set_check_failure "This OmniPBX install is not a git checkout, so git-based updates are unavailable."
    return 0
  fi

  GIT_READY="true"
  LOCAL_BRANCH="$(git_output rev-parse --abbrev-ref HEAD)"
  LOCAL_COMMIT="$(git_output rev-parse --short=12 HEAD)"
  REPO_DIRTY="$(
    if [[ -n "$(git_output status --porcelain --untracked-files=no)" ]]; then
      echo "true"
    else
      echo "false"
    fi
  )"

  if [[ "${LOCAL_BRANCH}" == "HEAD" ]]; then
    set_check_failure "This OmniPBX install is on a detached git HEAD. Check out a branch to enable updates." "" "true" "false"
    return 0
  fi

  if ! UPSTREAM_REF="$(git_output rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null)"; then
    set_check_failure "This OmniPBX install does not have an upstream tracking branch configured." "" "true" "false"
    return 0
  fi

  TRACKED_UPSTREAM="true"
  REMOTE_NAME="${UPSTREAM_REF%%/*}"
  REMOTE_URL="$(git_output remote get-url "${REMOTE_NAME}")"

  if ! git_output fetch --prune "${REMOTE_NAME}" >/dev/null 2>&1; then
    set_check_failure "Unable to compare this OmniPBX install with its upstream git branch right now." "git fetch failed for ${REMOTE_NAME}" "true" "true"
    return 0
  fi

  if ! REMOTE_COMMIT="$(git_output rev-parse --short=12 "${UPSTREAM_REF}" 2>/dev/null)"; then
    set_check_failure "Unable to compare this OmniPBX install with its upstream git branch right now." "Could not resolve ${UPSTREAM_REF}" "true" "true"
    return 0
  fi

  TARGET_VERSION="$(read_version_at_ref "${UPSTREAM_REF}")"
  LOCAL_COUNTS="$(git_output rev-list --left-right --count "HEAD...${UPSTREAM_REF}")"
  COMMITS_AHEAD="${LOCAL_COUNTS%% *}"
  COMMITS_BEHIND="${LOCAL_COUNTS##* }"

  if [[ "${COMMITS_BEHIND}" -gt 0 && "${COMMITS_AHEAD}" -eq 0 ]]; then
    CHECK_MESSAGE="${UPSTREAM_REF} is ${COMMITS_BEHIND} commit(s) ahead of this install."
  elif [[ "${COMMITS_BEHIND}" -gt 0 && "${COMMITS_AHEAD}" -gt 0 ]]; then
    CHECK_MESSAGE="This OmniPBX branch has diverged from ${UPSTREAM_REF}. Manual git cleanup is required before updating."
  elif [[ "${COMMITS_AHEAD}" -gt 0 ]]; then
    CHECK_MESSAGE="This OmniPBX install has ${COMMITS_AHEAD} local commit(s) ahead of ${UPSTREAM_REF}."
  else
    CHECK_MESSAGE="OmniPBX is up to date on ${UPSTREAM_REF}."
  fi

  if [[ "${REPO_DIRTY}" == "true" ]]; then
    CHECK_MESSAGE="${CHECK_MESSAGE} Local tracked changes are present."
  fi
}

write_check_cache() {
  python3 - "${CHECK_FILE}" "${CURRENT_VERSION}" "${TARGET_VERSION}" "${GIT_READY}" "${TRACKED_UPSTREAM}" "${LOCAL_BRANCH}" "${UPSTREAM_REF}" "${REMOTE_NAME}" "${REMOTE_URL}" "${LOCAL_COMMIT}" "${REMOTE_COMMIT}" "${COMMITS_BEHIND}" "${COMMITS_AHEAD}" "${REPO_DIRTY}" "${CHECK_ERROR}" "${CHECK_MESSAGE}" "$(_utc_now)" <<'PY'
from __future__ import annotations

from pathlib import Path
import json
import sys

path = Path(sys.argv[1])
payload = {
    "current_version": sys.argv[2],
    "latest_version": sys.argv[3],
    "git_ready": sys.argv[4] == "true",
    "tracked_upstream": sys.argv[5] == "true",
    "local_branch": sys.argv[6],
    "upstream_ref": sys.argv[7],
    "remote_name": sys.argv[8],
    "remote_url": sys.argv[9],
    "local_commit": sys.argv[10],
    "remote_commit": sys.argv[11],
    "commits_behind": int(sys.argv[12]),
    "commits_ahead": int(sys.argv[13]),
    "repo_dirty": sys.argv[14] == "true",
    "update_available": sys.argv[4] == "true" and sys.argv[5] == "true" and int(sys.argv[12]) > 0,
    "check_error": sys.argv[15],
    "message": sys.argv[16],
    "last_checked_at": sys.argv[17],
}
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
}

write_status() {
  local state="$1"
  local message="$2"
  local target_version="$3"
  local started_at="$4"
  local finished_at="$5"
  python3 - "${STATUS_FILE}" "${CURRENT_VERSION}" "${state}" "${message}" "${target_version}" "${started_at}" "${finished_at}" "${JOB_CONTAINER_ID:-}" <<'PY'
from __future__ import annotations

from datetime import UTC, datetime
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
payload = {
    "current_version": sys.argv[2],
    "state": sys.argv[3],
    "message": sys.argv[4],
    "target_version": sys.argv[5],
    "started_at": sys.argv[6],
    "finished_at": sys.argv[7],
    "job_container_id": sys.argv[8],
    "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
}
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
}

confirm_update() {
  if [[ "${NON_INTERACTIVE}" == "true" ]]; then
    return 0
  fi
  printf 'Apply OmniPBX update from %s to %s? [y/N] ' "${CURRENT_VERSION}" "${TARGET_VERSION}"
  read -r reply
  [[ "${reply}" =~ ^[Yy]$ ]]
}

set_env_value() {
  local key="$1"
  local value="$2"
  python3 - "${ENV_FILE}" "${key}" "${value}" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
key = sys.argv[2]
value = sys.argv[3]
lines = []
found = False
if env_path.exists():
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        if raw_line.startswith(f"{key}="):
            lines.append(f"{key}={value}")
            found = True
        else:
            lines.append(raw_line)
if not found:
    lines.append(f"{key}={value}")
env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
PY
}

restart_stack() {
  docker compose -f "${COMPOSE_FILE}" pull postgres app caddy
  docker compose -f "${COMPOSE_FILE}" up -d postgres app caddy
}

main() {
  parse_args "$@"
  ensure_privileges "$@"
  need_cmd python3
  need_cmd git
  setup_paths
  collect_git_status
  write_check_cache

  if [[ "${CHECK_ONLY}" == "true" ]]; then
    echo "${CHECK_MESSAGE}"
    [[ -n "${CHECK_ERROR}" ]] && echo "${CHECK_ERROR}" >&2
    if [[ "${GIT_READY}" == "true" && "${TRACKED_UPSTREAM}" == "true" ]]; then
      echo "Local branch: ${LOCAL_BRANCH}"
      echo "Tracking: ${UPSTREAM_REF}"
      echo "Local commit: ${LOCAL_COMMIT}"
      echo "Remote commit: ${REMOTE_COMMIT}"
      echo "Commits behind: ${COMMITS_BEHIND}"
      echo "Commits ahead: ${COMMITS_AHEAD}"
      echo "Repo dirty: ${REPO_DIRTY}"
    fi
    exit 0
  fi

  need_cmd docker

  [[ "${GIT_READY}" == "true" ]] || fail "${CHECK_MESSAGE}"
  [[ "${TRACKED_UPSTREAM}" == "true" ]] || fail "${CHECK_MESSAGE}"

  if [[ "${REPO_DIRTY}" == "true" ]]; then
    fail "Local tracked changes are present in ${PROJECT_ROOT}. Commit or revert them before updating."
  fi

  if [[ "${COMMITS_AHEAD}" -gt 0 && "${COMMITS_BEHIND}" -gt 0 ]]; then
    fail "This OmniPBX branch has diverged from ${UPSTREAM_REF}. Manual git cleanup is required before updating."
  fi

  if [[ "${COMMITS_BEHIND}" -eq 0 && "${FORCE}" != "true" ]]; then
    write_status "idle" "OmniPBX is already up to date on ${UPSTREAM_REF}." "" "" ""
    echo "OmniPBX is already up to date on ${UPSTREAM_REF}."
    exit 0
  fi

  if ! confirm_update; then
    write_status "idle" "Manual update was cancelled." "" "" ""
    echo "Update cancelled."
    exit 0
  fi

  STARTED_AT="$(_utc_now)"
  write_status "updating" "Pulling the latest OmniPBX changes from ${UPSTREAM_REF}." "${TARGET_VERSION}" "${STARTED_AT}" ""

  log INFO "Pulling the latest OmniPBX changes from ${UPSTREAM_REF}"
  if [[ "${FORCE}" == "true" && "${COMMITS_BEHIND}" -eq 0 ]]; then
    git_output fetch --prune "${REMOTE_NAME}" >/dev/null 2>&1 || fail "Failed to refresh ${REMOTE_NAME} before rebuild."
  else
    git_output pull --ff-only "${REMOTE_NAME}" "${UPSTREAM_REF#*/}" || fail "git pull --ff-only failed for ${UPSTREAM_REF}."
  fi

  CURRENT_VERSION="$(current_version)"
  set_env_value "OMNIPBX_APP_VERSION" "${CURRENT_VERSION}"

  write_status "updating" "Pulling images and restarting OmniPBX on ${UPSTREAM_REF}." "${CURRENT_VERSION}" "${STARTED_AT}" ""
  log INFO "Pulling images and restarting OmniPBX"
  restart_stack || fail "Docker Compose could not restart the OmniPBX stack."

  collect_git_status
  write_check_cache
  write_status "success" "OmniPBX updated successfully from ${UPSTREAM_REF}." "${CURRENT_VERSION}" "${STARTED_AT}" "$(_utc_now)"
  log OK "OmniPBX updated to ${CURRENT_VERSION}"
}

main "$@"
