#!/usr/bin/env bash
set -euo pipefail

SCRIPT_PATH="${BASH_SOURCE[0]:-}"
SCRIPT_DIR=""
REPO_ROOT=""
if [[ -n "${SCRIPT_PATH}" && -f "${SCRIPT_PATH}" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${SCRIPT_PATH}")" && pwd)"
  REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
fi
OMNIPBX_REPO_URL="${OMNIPBX_REPO_URL:-https://github.com/omnipbx-project/omnipbx.git}"
OMNIPBX_REPO_BRANCH="${OMNIPBX_REPO_BRANCH:-main}"
OMNIPBX_APP_IMAGE="${OMNIPBX_APP_IMAGE:-saroarsabbir/omnipbx}"
INSTALL_ROOT="${OMNIPBX_INSTALL_ROOT:-/opt/omnipbx}"
SERVICE_NAME="omnipbx"
DEPLOY_DIR="${INSTALL_ROOT}/deploy"
RUNTIME_DIR="${DEPLOY_DIR}/runtime"
ENV_FILE="${DEPLOY_DIR}/.env"
ENV_EXAMPLE="${REPO_ROOT}/deploy/.env.example"
SYSTEMD_UNIT="/etc/systemd/system/${SERVICE_NAME}.service"
CLI_LINK="/usr/local/bin/omnipbxctl"
FRIENDLY_CLI_LINK="/usr/local/bin/omnipbx"
SOURCE_MODE="remote"
APP_VERSION="${OMNIPBX_APP_VERSION:-0.1.0}"

if [[ -f "${REPO_ROOT}/VERSION" && -f "${REPO_ROOT}/deploy/compose.yaml" ]]; then
  SOURCE_MODE="local"
  APP_VERSION="$(tr -d '\n' < "${REPO_ROOT}/VERSION")"
fi

OS_ID=""
OS_VERSION=""
DETECTED_HOST=""
INTERNET_STATUS="Offline or blocked"
DOCKER_READY="false"
FIREWALL_NAME="Not detected"
FIREWALL_STATUS="Not detected"
SELINUX_STATUS="Not installed"
APPARMOR_STATUS="Not installed"
RECOMMENDED_MODE_VALUE="office"
RECOMMENDED_MODE_LABEL="Office or Home PBX"
RECOMMENDED_MODE_REASON="Detected private-network style addressing."
WEB_PORT=""
PUBLIC_HTTP_PORT=""
PUBLIC_HTTPS_PORT=""
SIP_PORT=""
RTP_START=""
RTP_END=""
TURN_PORT="3478"
TURN_MIN_PORT="49160"
TURN_MAX_PORT="49200"
DRY_RUN="false"
DRY_RUN_ROOT=""
INSTALL_STARTED_AT="${SECONDS}"
SETUP_REACHABLE="false"
SERVICE_STATUS="unknown"
RUNNING_CONTAINERS="unknown"
PROGRESS_WIDTH=30

log() {
  printf '\n[%s] %s\n' "$1" "$2"
}

render_progress() {
  local current="$1"
  local total="$2"
  local label="$3"
  local finish_line="${4:-false}"
  local percent filled empty filled_bar empty_bar

  if (( total <= 0 )); then
    total=1
  fi
  if (( current < 0 )); then
    current=0
  elif (( current > total )); then
    current="${total}"
  fi

  percent=$((current * 100 / total))
  filled=$((current * PROGRESS_WIDTH / total))
  empty=$((PROGRESS_WIDTH - filled))
  printf -v filled_bar '%*s' "${filled}" ''
  printf -v empty_bar '%*s' "${empty}" ''
  filled_bar="${filled_bar// /#}"
  empty_bar="${empty_bar// /-}"

  if [[ -t 1 ]]; then
    printf '\r\033[2K[%s%s] %3d%% %s' "${filled_bar}" "${empty_bar}" "${percent}" "${label}"
    if [[ "${finish_line}" == "true" ]]; then
      printf '\n'
    fi
  elif [[ "${finish_line}" == "true" || "${current}" -eq 0 || $((current % 10)) -eq 0 ]]; then
    printf '[%s%s] %3d%% %s\n' "${filled_bar}" "${empty_bar}" "${percent}" "${label}"
  fi
}

install_progress() {
  local current="$1"
  local total="$2"
  local label="$3"
  render_progress "${current}" "${total}" "${label}" true
}

fail() {
  echo "Installer failed: $*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Missing required command: $1"
}

usage() {
  cat <<'EOF'
Usage: install.sh [--dry-run]

Options:
  --dry-run   Run installer checks and generate temporary artifacts without
              changing /opt, systemd, or starting containers.
EOF
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run)
        DRY_RUN="true"
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        fail "Unknown argument: $1"
        ;;
    esac
  done
}

ensure_privileges() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    return 0
  fi

  if [[ "${EUID}" -ne 0 ]]; then
    if [[ -z "${SCRIPT_PATH}" || ! -f "${SCRIPT_PATH}" ]]; then
      fail "Run the streamed installer with sudo, for example: curl -fsSL https://omnipbx.techseba.com | sudo bash"
    fi
    exec sudo bash "$0" "$@"
  fi
}

detect_os() {
  [[ -f /etc/os-release ]] || fail "/etc/os-release not found."
  # shellcheck disable=SC1091
  source /etc/os-release
  OS_ID="${ID:-unknown}"
  OS_VERSION="${VERSION_ID:-unknown}"
}

internet_reachable() {
  if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 5 https://letsencrypt.org >/dev/null 2>&1; then
    return 0
  fi
  if command -v ping >/dev/null 2>&1 && ping -c 1 -W 2 1.1.1.1 >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

command_exists() {
  command -v "$1" >/dev/null 2>&1
}

docker_installed() {
  command_exists docker && docker version >/dev/null 2>&1
}

docker_compose_ready() {
  command_exists docker && docker compose version >/dev/null 2>&1
}

compose_cmd() {
  COMPOSE_PROGRESS=plain docker compose --progress plain "$@"
}

ensure_git_available() {
  if command_exists git; then
    return 0
  fi

  if [[ "${DRY_RUN}" == "true" ]]; then
    log INFO "Dry run: git missing and would be installed for ${OS_ID} ${OS_VERSION}"
    return 0
  fi

  case "${OS_ID}" in
    ubuntu|debian)
      log INFO "Installing git for ${OS_ID} ${OS_VERSION}"
      apt-get update
      apt-get install -y git
      ;;
    *)
      fail "git is required for remote installs. Install git first, then rerun the installer."
      ;;
  esac
}

install_docker() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    log INFO "Dry run: Docker/Compose missing and would be installed for ${OS_ID} ${OS_VERSION}"
    return 0
  fi
  detect_os
  case "${OS_ID}" in
    ubuntu|debian)
      log INFO "Installing Docker and Docker Compose for ${OS_ID} ${OS_VERSION}"
      apt-get update
      if apt-cache show docker-compose-v2 >/dev/null 2>&1; then
        apt-get install -y docker.io docker-compose-v2
      elif apt-cache show docker-compose-plugin >/dev/null 2>&1; then
        apt-get install -y docker.io docker-compose-plugin
      else
        apt-get install -y docker.io
      fi
      systemctl enable --now docker
      ;;
    *)
      fail "Automatic Docker installation currently supports Ubuntu and Debian only."
      ;;
  esac
}

configure_docker_networking() {
  local daemon_config="/etc/docker/daemon.json"
  local result

  if [[ "${DRY_RUN}" == "true" ]]; then
    log INFO "Dry run: would disable Docker's userland proxy for reliable SIP and RTP port handling"
    return 0
  fi

  # docker-proxy rewrites the UDP source port seen by Asterisk. SIP phones then
  # send in-dialog ACKs to a different port and answered calls end after 32s.
  # Merge this setting instead of replacing an administrator's Docker options.
  result="$(python3 - "${daemon_config}" <<'PY'
import json
import os
import sys
import tempfile

path = sys.argv[1]
config = {}
if os.path.exists(path):
    try:
        with open(path, encoding="utf-8") as handle:
            config = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot update {path}: {exc}")
    if not isinstance(config, dict):
        raise SystemExit(f"Cannot update {path}: top-level JSON value must be an object")

if config.get("userland-proxy") is False:
    print("unchanged")
    raise SystemExit(0)

config["userland-proxy"] = False
os.makedirs(os.path.dirname(path), mode=0o755, exist_ok=True)
fd, temp_path = tempfile.mkstemp(prefix="daemon.json.", dir=os.path.dirname(path), text=True)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(config, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(temp_path, 0o644)
    os.replace(temp_path, path)
except BaseException:
    try:
        os.unlink(temp_path)
    except FileNotFoundError:
        pass
    raise
print("changed")
PY
)"

  if [[ "${result}" == "changed" ]]; then
    if command_exists dockerd; then
      dockerd --validate --config-file="${daemon_config}" >/dev/null
    fi
    log INFO "Restarting Docker with SIP-safe UDP forwarding"
    systemctl restart docker
  fi
}

detect_ip_addresses() {
  local collected=""
  if command_exists hostname; then
    collected+="$(hostname -I 2>/dev/null || true)"$'\n'
  fi
  if command_exists ip; then
    collected+="$(ip -o -4 addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1)"$'\n'
    collected+="$(ip route get 1.1.1.1 2>/dev/null | awk '/src/ {for (i = 1; i <= NF; i++) if ($i == "src") print $(i+1)}')"$'\n'
  fi
  COLLECTED_IPS="${collected}" python3 - <<'PY'
import ipaddress
import os
import socket

addresses = {"127.0.0.1"}
for line in os.environ.get("COLLECTED_IPS", "").splitlines():
    for token in line.replace(",", " ").split():
        candidate = token.strip()
        if not candidate:
            continue
        try:
            ip = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if not ip.is_loopback:
            addresses.add(candidate)

for family in (socket.AF_INET, socket.AF_INET6):
    try:
        for result in socket.getaddrinfo(socket.gethostname(), None, family, socket.SOCK_STREAM):
            ip = result[4][0]
            if ip and ip != "::1" and not ip.startswith("127."):
                addresses.add(ip)
    except OSError:
        pass

print("\n".join(sorted(addresses)))
PY
}

is_private_address() {
  python3 - "$1" <<'PY'
import ipaddress, sys
try:
    ip = ipaddress.ip_address(sys.argv[1])
    print("true" if ip.is_private or ip.is_loopback else "false")
except ValueError:
    print("false")
PY
}

detect_host() {
  local route_host=""
  if command_exists ip; then
    route_host="$(ip route get 1.1.1.1 2>/dev/null | awk '/src/ {for (i = 1; i <= NF; i++) if ($i == "src") print $(i+1); exit}')"
  fi
  if [[ -n "${route_host}" && "${route_host}" != "127.0.0.1" && "${route_host}" != "::1" ]]; then
    DETECTED_HOST="${route_host}"
    return 0
  fi

  local first_host=""
  while IFS= read -r ip; do
    [[ -z "${ip}" ]] && continue
    if [[ "${ip}" != "127.0.0.1" && "${ip}" != "::1" ]]; then
      first_host="${ip}"
      break
    fi
  done < <(detect_ip_addresses)
  DETECTED_HOST="${first_host:-127.0.0.1}"
}

choose_recommended_mode() {
  if [[ "$(is_private_address "${DETECTED_HOST}")" == "true" ]]; then
    RECOMMENDED_MODE_VALUE="office"
    RECOMMENDED_MODE_LABEL="Office or Home PBX"
    RECOMMENDED_MODE_REASON="Detected a private-network address, so a local office deployment is the safest starting point."
  else
    RECOMMENDED_MODE_VALUE="public_server"
    RECOMMENDED_MODE_LABEL="Public Internet or Cloud"
    RECOMMENDED_MODE_REASON="Detected a public-facing address, so a public server deployment is likely the right fit."
  fi
}

port_in_use() {
  local proto="$1"
  local port="$2"
  if [[ "${proto}" == "tcp" ]]; then
    ss -ltn "( sport = :${port} )" 2>/dev/null | tail -n +2 | grep -q .
  else
    ss -lun "( sport = :${port} )" 2>/dev/null | tail -n +2 | grep -q .
  fi
}

find_free_port() {
  local proto="$1"
  local start="$2"
  local port="${start}"
  while [[ "${port}" -lt $((start + 200)) ]]; do
    if ! port_in_use "${proto}" "${port}"; then
      echo "${port}"
      return 0
    fi
    port=$((port + 1))
  done
  return 1
}

range_conflicts() {
  local start="$1"
  local end="$2"
  local current
  for ((current=start; current<=end; current++)); do
    if port_in_use udp "${current}"; then
      return 0
    fi
  done
  return 1
}

find_free_udp_range() {
  local start="$1"
  local width="$2"
  local candidate="${start}"
  while [[ "${candidate}" -lt $((start + 5000)) ]]; do
    local candidate_end=$((candidate + width - 1))
    if ! range_conflicts "${candidate}" "${candidate_end}"; then
      echo "${candidate}:${candidate_end}"
      return 0
    fi
    candidate=$((candidate + width))
  done
  return 1
}

detect_firewall() {
  if command_exists ufw; then
    local ufw_line
    ufw_line="$(ufw status 2>/dev/null | head -n 1 || true)"
    if [[ -n "${ufw_line}" ]]; then
      FIREWALL_NAME="ufw"
      FIREWALL_STATUS="${ufw_line#Status: }"
      return
    fi
  fi

  if command_exists systemctl && systemctl is-active --quiet firewalld 2>/dev/null; then
    FIREWALL_NAME="firewalld"
    FIREWALL_STATUS="active"
    return
  fi

  FIREWALL_NAME="none"
  FIREWALL_STATUS="not detected"
}

configure_firewall() {
  if [[ "${FIREWALL_NAME}" == "none" ]]; then
    return 0
  fi

  log INFO "Configuring firewall (${FIREWALL_NAME}) for OmniPBX"

  local tcp_ports=("${WEB_PORT}" "${PUBLIC_HTTP_PORT}" "${PUBLIC_HTTPS_PORT}" "${TURN_PORT}")
  local udp_ports=("${SIP_PORT}" "${TURN_PORT}")
  local rtp_range="${RTP_START}:${RTP_END}"
  local turn_range="${TURN_MIN_PORT}:${TURN_MAX_PORT}"

  if [[ "${DRY_RUN}" == "true" ]]; then
    log INFO "Dry run: would open TCP ports ${tcp_ports[*]} and UDP ports ${udp_ports[*]}, ${rtp_range}, ${turn_range}"
    return 0
  fi

  case "${FIREWALL_NAME}" in
    ufw)
      for port in "${tcp_ports[@]}"; do
        ufw allow "${port}/tcp" >/dev/null
      done
      for port in "${udp_ports[@]}"; do
        ufw allow "${port}/udp" >/dev/null
      done
      ufw allow "${RTP_START}:${RTP_END}/udp" >/dev/null
      ufw allow "${TURN_MIN_PORT}:${TURN_MAX_PORT}/udp" >/dev/null
      ;;
    firewalld)
      for port in "${tcp_ports[@]}"; do
        firewall-cmd --permanent --add-port="${port}/tcp" >/dev/null
      done
      for port in "${udp_ports[@]}"; do
        firewall-cmd --permanent --add-port="${port}/udp" >/dev/null
      done
      firewall-cmd --permanent --add-port="${RTP_START}-${RTP_END}/udp" >/dev/null
      firewall-cmd --permanent --add-port="${TURN_MIN_PORT}-${TURN_MAX_PORT}/udp" >/dev/null
      firewall-cmd --reload >/dev/null
      ;;
  esac
}

detect_security_frameworks() {
  if command_exists getenforce; then
    SELINUX_STATUS="$(getenforce 2>/dev/null || echo unknown)"
  fi

  if command_exists systemctl && systemctl is-active --quiet apparmor; then
    APPARMOR_STATUS="active"
  elif [[ -d /sys/module/apparmor ]]; then
    APPARMOR_STATUS="loaded"
  fi
}

random_secret() {
  if command_exists openssl; then
    openssl rand -hex 18
  else
    tr -dc 'A-Za-z0-9' </dev/urandom | head -c 36
  fi
}

copy_project() {
  log INFO "Preparing OmniPBX in ${INSTALL_ROOT}"
  mkdir -p "${INSTALL_ROOT}"
  if [[ "${SOURCE_MODE}" == "remote" ]]; then
    ensure_git_available
    if [[ "${DRY_RUN}" == "true" ]]; then
      log INFO "Dry run: would clone ${OMNIPBX_REPO_URL} (${OMNIPBX_REPO_BRANCH}) into ${INSTALL_ROOT}"
      mkdir -p "${INSTALL_ROOT}/deploy" "${INSTALL_ROOT}/scripts" "${RUNTIME_DIR}/caddy"
      if [[ -n "${REPO_ROOT}" ]]; then
        cp -a "${REPO_ROOT}/deploy/compose.yaml" "${INSTALL_ROOT}/deploy/compose.yaml" 2>/dev/null || true
        cp -a "${REPO_ROOT}/deploy/.env.example" "${INSTALL_ROOT}/deploy/.env.example" 2>/dev/null || true
      fi
      return 0
    fi
    if [[ -d "${INSTALL_ROOT}/.git" ]]; then
      log INFO "Existing OmniPBX install found; updating git checkout and reusing existing configuration."
      git -C "${INSTALL_ROOT}" fetch --prune origin
      git -C "${INSTALL_ROOT}" checkout "${OMNIPBX_REPO_BRANCH}"
      git -C "${INSTALL_ROOT}" pull --ff-only origin "${OMNIPBX_REPO_BRANCH}"
    else
      rm -rf "${INSTALL_ROOT:?}/"*
      git clone --branch "${OMNIPBX_REPO_BRANCH}" --single-branch "${OMNIPBX_REPO_URL}" "${INSTALL_ROOT}"
    fi
    APP_VERSION="$(tr -d '\n' < "${INSTALL_ROOT}/VERSION")"
    mkdir -p "${RUNTIME_DIR}/caddy"
    return 0
  fi

  if command_exists rsync; then
    rsync -a --delete \
      --exclude 'deploy/.env' \
      --exclude 'deploy/runtime' \
      "${REPO_ROOT}/" "${INSTALL_ROOT}/"
  else
    rm -rf "${INSTALL_ROOT}/apps" "${INSTALL_ROOT}/deploy" "${INSTALL_ROOT}/docs" "${INSTALL_ROOT}/scripts" "${INSTALL_ROOT}/omnipbx" "${INSTALL_ROOT}/README.md" "${INSTALL_ROOT}/VERSION"
    mkdir -p "${INSTALL_ROOT}"
    if [[ -d "${REPO_ROOT}/.git" ]]; then
      cp -a "${REPO_ROOT}/.git" "${INSTALL_ROOT}/.git"
    fi
    cp -a "${REPO_ROOT}/apps" "${INSTALL_ROOT}/apps"
    mkdir -p "${INSTALL_ROOT}/deploy"
    for item in "${REPO_ROOT}/deploy/"*; do
      base_item="$(basename "${item}")"
      if [[ "${base_item}" != "runtime" && "${base_item}" != ".env" ]]; then
        cp -a "${item}" "${INSTALL_ROOT}/deploy/"
      fi
    done
    cp -a "${REPO_ROOT}/docs" "${INSTALL_ROOT}/docs"
    cp -a "${REPO_ROOT}/scripts" "${INSTALL_ROOT}/scripts"
    cp -a "${REPO_ROOT}/omnipbx" "${INSTALL_ROOT}/omnipbx"
    cp -a "${REPO_ROOT}/README.md" "${INSTALL_ROOT}/README.md"
    cp -a "${REPO_ROOT}/VERSION" "${INSTALL_ROOT}/VERSION"
  fi
  mkdir -p "${RUNTIME_DIR}/caddy"
}

install_cli_helper() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    log INFO "Dry run: skipping CLI helper links at ${CLI_LINK} and ${FRIENDLY_CLI_LINK}"
    return 0
  fi

  chmod +x "${INSTALL_ROOT}/scripts/omnipbxctl"
  chmod +x "${INSTALL_ROOT}/omnipbx"
  ln -sf "${INSTALL_ROOT}/scripts/omnipbxctl" "${CLI_LINK}"
  ln -sf "${INSTALL_ROOT}/omnipbx" "${FRIENDLY_CLI_LINK}"
}

write_env_file() {
  local postgres_password="${POSTGRES_PASSWORD:-}"
  local turn_credential="${OMNIPBX_TURN_CREDENTIAL:-}"
  if [[ -f "${ENV_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
    postgres_password="${POSTGRES_PASSWORD:-${postgres_password}}"
    turn_credential="${OMNIPBX_TURN_CREDENTIAL:-${turn_credential}}"
  fi
  postgres_password="${postgres_password:-$(random_secret)}"
  turn_credential="${turn_credential:-$(random_secret)}"
  cat > "${ENV_FILE}" <<EOF
COMPOSE_PROJECT_NAME=omnipbx
ASTERISK_VERSION=22.9.0
OMNIPBX_APP_IMAGE=${OMNIPBX_APP_IMAGE}
OMNIPBX_APP_VERSION=${APP_VERSION}
OMNIPBX_WEB_PORT=${WEB_PORT}
OMNIPBX_PUBLIC_HTTP_PORT=${PUBLIC_HTTP_PORT}
OMNIPBX_PUBLIC_HTTPS_PORT=${PUBLIC_HTTPS_PORT}
POSTGRES_DB=omnipbx
POSTGRES_USER=omnipbx
POSTGRES_PASSWORD=${postgres_password}
ASTERISK_SIP_PORT=${SIP_PORT}
ASTERISK_RTP_START=${RTP_START}
ASTERISK_RTP_END=${RTP_END}
OMNIPBX_TURN_PORT=${TURN_PORT}
OMNIPBX_TURN_MIN_PORT=${TURN_MIN_PORT}
OMNIPBX_TURN_MAX_PORT=${TURN_MAX_PORT}
OMNIPBX_TURN_USERNAME=omnipbx
OMNIPBX_TURN_CREDENTIAL=${turn_credential}
OMNIPBX_TURN_REALM=${DETECTED_HOST}
OMNIPBX_TURN_EXTERNAL_IP=${DETECTED_HOST}
EOF
}

write_preflight_json() {
  local ports_json ips_json
  ports_json="$(python3 - <<PY
import json
ports = [
    {"label": "Setup UI", "proto": "tcp", "requested": 18000, "selected": int("${WEB_PORT}"), "status": "free" if 18000 == int("${WEB_PORT}") else "adjusted"},
    {"label": "Public HTTP", "proto": "tcp", "requested": 80, "selected": int("${PUBLIC_HTTP_PORT}"), "status": "free" if 80 == int("${PUBLIC_HTTP_PORT}") else "conflicted"},
    {"label": "Public HTTPS", "proto": "tcp", "requested": 443, "selected": int("${PUBLIC_HTTPS_PORT}"), "status": "free" if 443 == int("${PUBLIC_HTTPS_PORT}") else "conflicted"},
    {"label": "SIP", "proto": "udp", "requested": 5060, "selected": int("${SIP_PORT}"), "status": "free" if 5060 == int("${SIP_PORT}") else "conflicted"},
    {"label": "RTP", "proto": "udp", "requested": "10000-10100", "selected": "${RTP_START}-${RTP_END}", "status": "free" if "${RTP_START}-${RTP_END}" == "10000-10100" else "conflicted"},
    {"label": "TURN", "proto": "tcp/udp", "requested": 3478, "selected": int("${TURN_PORT}"), "status": "free" if 3478 == int("${TURN_PORT}") else "conflicted"},
    {"label": "TURN relay", "proto": "udp", "requested": "49160-49200", "selected": "${TURN_MIN_PORT}-${TURN_MAX_PORT}", "status": "free" if "${TURN_MIN_PORT}-${TURN_MAX_PORT}" == "49160-49200" else "conflicted"},
]
print(json.dumps(ports))
PY
)"
  ips_json="$(DETECTED_HOST_VALUE="${DETECTED_HOST}" DETECTED_IPS="$(detect_ip_addresses)" python3 - <<'PY'
import json, os

addresses = []
seen = set()

def add(value):
    value = (value or "").strip()
    if value and value not in seen:
        seen.add(value)
        addresses.append(value)

add(os.environ.get("DETECTED_HOST_VALUE"))
for line in os.environ.get("DETECTED_IPS", "").splitlines():
    add(line)
add("127.0.0.1")
print(json.dumps(addresses))
PY
)"
  python3 - <<PY
import json
from pathlib import Path

payload = {
    "hostname": "${HOSTNAME:-$(hostname)}",
    "detected_host": "${DETECTED_HOST}",
    "ip_addresses": json.loads(${ips_json@Q}),
    "internet_status": "${INTERNET_STATUS}",
    "docker_ready": json.loads(${DOCKER_READY@Q}),
    "firewall_name": "${FIREWALL_NAME}",
    "firewall_status": "${FIREWALL_STATUS}",
    "selinux_status": "${SELINUX_STATUS}",
    "apparmor_status": "${APPARMOR_STATUS}",
    "ports": json.loads(${ports_json@Q}),
    "recommended_mode": {
        "value": "${RECOMMENDED_MODE_VALUE}",
        "label": "${RECOMMENDED_MODE_LABEL}",
        "reason": "${RECOMMENDED_MODE_REASON}",
    },
}
path = Path("${RUNTIME_DIR}/host-preflight.json")
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
PY
}

write_systemd_unit() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    log INFO "Dry run: skipping systemd unit creation at ${SYSTEMD_UNIT}"
    return 0
  fi
  cat > "${SYSTEMD_UNIT}" <<EOF
[Unit]
Description=OmniPBX Docker Stack
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${INSTALL_ROOT}
Environment=COMPOSE_PROGRESS=plain
ExecStart=/usr/bin/docker compose --progress plain -f ${DEPLOY_DIR}/compose.yaml up -d postgres app caddy turn
ExecStop=/usr/bin/docker compose --progress plain -f ${DEPLOY_DIR}/compose.yaml down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable "${SERVICE_NAME}.service" >/dev/null
  log INFO "Starting OmniPBX containers"
  systemctl restart --no-block "${SERVICE_NAME}.service"

  local attempt state progress
  for attempt in $(seq 1 600); do
    state="$(systemctl is-active "${SERVICE_NAME}.service" 2>/dev/null || true)"
    case "${state}" in
      active)
        render_progress 100 100 "Starting services" true
        return 0
        ;;
      failed)
        render_progress 100 100 "Service startup failed" true
        systemctl status "${SERVICE_NAME}.service" --no-pager -l || true
        return 1
        ;;
    esac
    progress="${attempt}"
    if (( progress > 95 )); then
      progress=95
    fi
    render_progress "${progress}" 100 "Starting services (${attempt}s)"
    sleep 1
  done

  render_progress 100 100 "Service startup timed out" true
  systemctl status "${SERVICE_NAME}.service" --no-pager -l || true
  return 1
}

wait_for_setup() {
  local url="http://127.0.0.1:${WEB_PORT}/setup"
  local attempt
  render_progress 0 60 "Waiting for setup page"
  for attempt in $(seq 1 60); do
    if curl -fsS --max-time 3 "${url}" >/dev/null 2>&1; then
      render_progress 60 60 "Setup page is ready" true
      return 0
    fi
    render_progress "${attempt}" 60 "Waiting for setup page"
    sleep 2
  done
  render_progress 60 60 "Setup page did not become ready" true
  return 1
}

prepare_install_root() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    DRY_RUN_ROOT="$(mktemp -d /tmp/omnipbx-installer-dry-run.XXXXXX)"
    INSTALL_ROOT="${DRY_RUN_ROOT}/opt/omnipbx"
    DEPLOY_DIR="${INSTALL_ROOT}/deploy"
    RUNTIME_DIR="${DEPLOY_DIR}/runtime"
    ENV_FILE="${DEPLOY_DIR}/.env"
    log INFO "Dry run sandbox: ${DRY_RUN_ROOT}"
  fi
}

ensure_docker_ready() {
  if command_exists docker && docker info >/dev/null 2>&1; then
    DOCKER_READY="true"
    return 0
  fi

  if command_exists systemctl && systemctl is-active --quiet docker 2>/dev/null; then
    DOCKER_READY="true"
    if [[ "${DRY_RUN}" == "true" ]]; then
      log INFO "Dry run: Docker service is active, but this shell cannot query docker info directly."
      return 0
    fi
  fi

  if [[ "${DRY_RUN}" == "true" ]]; then
    DOCKER_READY="false"
    log WARN "Dry run: Docker is not responding for this user, so startup steps will be reported only."
    return 0
  fi

  fail "Docker is installed but not responding."
}

choose_ports() {
  if [[ -f "${ENV_FILE}" ]]; then
    # shellcheck disable=SC1090
    source "${ENV_FILE}"
    if [[ -n "${OMNIPBX_WEB_PORT:-}" && -n "${OMNIPBX_PUBLIC_HTTP_PORT:-}" && -n "${OMNIPBX_PUBLIC_HTTPS_PORT:-}" && -n "${ASTERISK_SIP_PORT:-}" && -n "${ASTERISK_RTP_START:-}" && -n "${ASTERISK_RTP_END:-}" ]]; then
      WEB_PORT="${OMNIPBX_WEB_PORT}"
      PUBLIC_HTTP_PORT="${OMNIPBX_PUBLIC_HTTP_PORT}"
      PUBLIC_HTTPS_PORT="${OMNIPBX_PUBLIC_HTTPS_PORT}"
      SIP_PORT="${ASTERISK_SIP_PORT}"
      RTP_START="${ASTERISK_RTP_START}"
      RTP_END="${ASTERISK_RTP_END}"
      TURN_PORT="${OMNIPBX_TURN_PORT:-${TURN_PORT}}"
      TURN_MIN_PORT="${OMNIPBX_TURN_MIN_PORT:-${TURN_MIN_PORT}}"
      TURN_MAX_PORT="${OMNIPBX_TURN_MAX_PORT:-${TURN_MAX_PORT}}"
      log INFO "Reusing existing OmniPBX ports from ${ENV_FILE}"
      return 0
    fi
  fi

  WEB_PORT="$(find_free_port tcp 18000)" || fail "Could not find a free setup UI port."
  PUBLIC_HTTP_PORT="$(find_free_port tcp 80)" || fail "Could not find a free public HTTP port."
  PUBLIC_HTTPS_PORT="$(find_free_port tcp 443)" || fail "Could not find a free public HTTPS port."
  SIP_PORT="$(find_free_port udp 5060)" || fail "Could not find a free SIP port."
  local rtp_range
  rtp_range="$(find_free_udp_range 10000 101)" || fail "Could not find a free RTP range."
  RTP_START="${rtp_range%%:*}"
  RTP_END="${rtp_range##*:}"
}

open_browser() {
  local url="http://127.0.0.1:${WEB_PORT}/setup"

  # If we're not in a dry run and have a display, try to open the browser
  if [[ "${DRY_RUN}" != "true" && -n "${DISPLAY:-}" ]]; then
    log INFO "Opening browser to ${url}"
    # Try to open as the original user if we are sudo
    local opener="xdg-open"
    if [[ -n "${SUDO_USER:-}" ]]; then
      sudo -u "${SUDO_USER}" "${opener}" "${url}" >/dev/null 2>&1 || true
    else
      "${opener}" "${url}" >/dev/null 2>&1 || true
    fi
  fi
}

print_success_banner() {
  local url="http://${DETECTED_HOST}:${WEB_PORT}/setup"
  local local_url="http://127.0.0.1:${WEB_PORT}/setup"

  echo -e "\n\033[1;32m================================================================\033[0m"
  echo -e "\033[1;32m              OmniPBX Installation Successful!                  \033[0m"
  echo -e "\033[1;32m================================================================\033[0m"
  echo -e "\nYour PBX is now ready for initial setup."
  echo -e "\n\033[1mPrimary Setup URL:\033[0m ${url}"
  echo -e "\033[1mLocal Fallback:\033[0m    ${local_url}"
  echo -e "\n\033[1mNext Steps:\033[0m"
  echo -e " 1. Open the URL above in your web browser."
  echo -e " 2. Follow the on-screen instructions to create your admin account."
  echo -e " 3. Configure your extensions and trunks."
  echo -e "\n\033[1mMaintenance:\033[0m"
  echo -e " Use the '\033[1momnipbx\033[0m' command for start, stop, unlock, logs, and updates."
  echo -e "\033[1;32m================================================================\033[0m\n"
}

collect_verification_summary() {
  if [[ "${DRY_RUN}" == "true" ]]; then
    return 0
  fi

  if command_exists systemctl; then
    SERVICE_STATUS="$(systemctl is-active "${SERVICE_NAME}.service" 2>/dev/null || echo inactive)"
  fi

  if command_exists docker; then
    RUNNING_CONTAINERS="$(docker compose -f "${DEPLOY_DIR}/compose.yaml" ps --services --filter status=running 2>/dev/null | tr '\n' ' ' | sed 's/[[:space:]]*$//' || true)"
    RUNNING_CONTAINERS="${RUNNING_CONTAINERS:-none}"
  fi

  if curl -fsS --max-time 3 "http://127.0.0.1:${WEB_PORT}/setup" >/dev/null 2>&1; then
    SETUP_REACHABLE="true"
  fi
}

print_verification_summary() {
  local duration=$((SECONDS - INSTALL_STARTED_AT))
  echo "Verification:"
  echo " Service: ${SERVICE_STATUS}"
  echo " Containers: ${RUNNING_CONTAINERS}"
  echo " Setup URL reachable: ${SETUP_REACHABLE}"
  echo " Install time: ${duration}s"
}

main() {
  local progress_total=9
  parse_args "$@"
  ensure_privileges "$@"
  need_cmd python3
  detect_os
  prepare_install_root
  detect_host
  choose_recommended_mode

  if internet_reachable; then
    INTERNET_STATUS="Online"
  fi
  install_progress 1 "${progress_total}" "Host checks complete"

  if ! docker_installed || ! docker_compose_ready; then
    install_docker
  fi

  configure_docker_networking
  ensure_docker_ready
  install_progress 2 "${progress_total}" "Docker is ready"

  detect_firewall
  detect_security_frameworks
  choose_ports
  configure_firewall
  install_progress 3 "${progress_total}" "Ports and firewall are ready"
  copy_project
  install_cli_helper
  install_progress 4 "${progress_total}" "Project files are ready"
  write_env_file
  write_preflight_json
  install_progress 5 "${progress_total}" "Configuration is ready"
  if [[ "${DRY_RUN}" == "true" ]]; then
    log INFO "Dry run: skipping image pull and container startup"
  else
    log INFO "Pulling required container images"
    compose_cmd -f "${DEPLOY_DIR}/compose.yaml" pull postgres app caddy turn
  fi
  if [[ "${DRY_RUN}" == "true" ]]; then
    install_progress 6 "${progress_total}" "Image download is planned"
  else
    install_progress 6 "${progress_total}" "Container images are ready"
  fi
  write_systemd_unit
  if [[ "${DRY_RUN}" == "true" ]]; then
    install_progress 7 "${progress_total}" "Service startup is planned"
  else
    install_progress 7 "${progress_total}" "Services are started"
  fi

  if [[ "${DRY_RUN}" != "true" ]]; then
    if ! wait_for_setup; then
      fail "OmniPBX containers started, but the setup UI did not become reachable in time."
    fi
  fi
  if [[ "${DRY_RUN}" == "true" ]]; then
    install_progress 8 "${progress_total}" "Setup check is planned"
  else
    install_progress 8 "${progress_total}" "Setup page is ready"
  fi

  if [[ "${DRY_RUN}" == "true" ]]; then
    install_progress 9 "${progress_total}" "Dry-run plan verified"
    log OK "OmniPBX installer dry run completed"
    echo "Dry run sandbox: ${DRY_RUN_ROOT}"
    echo "Generated env file: ${ENV_FILE}"
    echo "Generated preflight file: ${RUNTIME_DIR}/host-preflight.json"
    echo "Planned setup URL: http://${DETECTED_HOST}:${WEB_PORT}/setup"
    echo "Planned local fallback: http://127.0.0.1:${WEB_PORT}/setup"
    echo "Recommended mode: ${RECOMMENDED_MODE_LABEL}"
    echo "Firewall: ${FIREWALL_NAME} (${FIREWALL_STATUS})"
    echo "Docker ready: ${DOCKER_READY}"
  else
    collect_verification_summary
    install_progress 9 "${progress_total}" "Installation verified"
    print_success_banner
    print_verification_summary
    open_browser
  fi
}

main "$@"
