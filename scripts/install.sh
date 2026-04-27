#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
INSTALL_ROOT="${OMNIPBX_INSTALL_ROOT:-/opt/omnipbx}"
SERVICE_NAME="omnipbx"
DEPLOY_DIR="${INSTALL_ROOT}/deploy"
RUNTIME_DIR="${DEPLOY_DIR}/runtime"
ENV_FILE="${DEPLOY_DIR}/.env"
ENV_EXAMPLE="${REPO_ROOT}/deploy/.env.example"
SYSTEMD_UNIT="/etc/systemd/system/${SERVICE_NAME}.service"
APP_VERSION="$(tr -d '\n' < "${REPO_ROOT}/VERSION")"

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
DRY_RUN="false"
DRY_RUN_ROOT=""

log() {
  printf '\n[%s] %s\n' "$1" "$2"
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

  if command_exists systemctl && systemctl is-active --quiet firewalld; then
    FIREWALL_NAME="firewalld"
    FIREWALL_STATUS="active"
    return
  fi

  FIREWALL_NAME="none"
  FIREWALL_STATUS="not detected"
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
  log INFO "Copying OmniPBX into ${INSTALL_ROOT}"
  mkdir -p "${INSTALL_ROOT}"
  if command_exists rsync; then
    rsync -a --delete \
      --exclude 'deploy/.env' \
      --exclude 'deploy/runtime' \
      "${REPO_ROOT}/" "${INSTALL_ROOT}/"
  else
    rm -rf "${INSTALL_ROOT}/apps" "${INSTALL_ROOT}/deploy" "${INSTALL_ROOT}/docs" "${INSTALL_ROOT}/scripts" "${INSTALL_ROOT}/README.md" "${INSTALL_ROOT}/VERSION"
    mkdir -p "${INSTALL_ROOT}"
    if [[ -d "${REPO_ROOT}/.git" ]]; then
      cp -a "${REPO_ROOT}/.git" "${INSTALL_ROOT}/.git"
    fi
    cp -a "${REPO_ROOT}/apps" "${INSTALL_ROOT}/apps"
    cp -a "${REPO_ROOT}/deploy" "${INSTALL_ROOT}/deploy"
    cp -a "${REPO_ROOT}/docs" "${INSTALL_ROOT}/docs"
    cp -a "${REPO_ROOT}/scripts" "${INSTALL_ROOT}/scripts"
    cp -a "${REPO_ROOT}/README.md" "${INSTALL_ROOT}/README.md"
    cp -a "${REPO_ROOT}/VERSION" "${INSTALL_ROOT}/VERSION"
  fi
  mkdir -p "${RUNTIME_DIR}/caddy"
}

write_env_file() {
  local postgres_password
  postgres_password="$(random_secret)"
  cat > "${ENV_FILE}" <<EOF
COMPOSE_PROJECT_NAME=omnipbx
ASTERISK_VERSION=22.9.0
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
]
print(json.dumps(ports))
PY
)"
  ips_json="$(python3 - <<'PY'
import json, socket
addresses = {"127.0.0.1"}
for family in (socket.AF_INET, socket.AF_INET6):
    try:
        for result in socket.getaddrinfo(socket.gethostname(), None, family, socket.SOCK_STREAM):
            ip = result[4][0]
            if ip and ip != "::1" and not ip.startswith("127."):
                addresses.add(ip)
    except OSError:
        pass
print(json.dumps(sorted(addresses)))
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
ExecStart=/usr/bin/docker compose -f ${DEPLOY_DIR}/compose.yaml up -d --build postgres app caddy
ExecStop=/usr/bin/docker compose -f ${DEPLOY_DIR}/compose.yaml down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable --now "${SERVICE_NAME}.service"
}

wait_for_setup() {
  local url="http://127.0.0.1:${WEB_PORT}/setup"
  local attempt
  for attempt in $(seq 1 60); do
    if curl -fsS --max-time 3 "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
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

  if command_exists systemctl && systemctl is-active --quiet docker; then
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
  WEB_PORT="$(find_free_port tcp 18000)" || fail "Could not find a free setup UI port."
  PUBLIC_HTTP_PORT="$(find_free_port tcp 80)" || fail "Could not find a free public HTTP port."
  PUBLIC_HTTPS_PORT="$(find_free_port tcp 443)" || fail "Could not find a free public HTTPS port."
  SIP_PORT="$(find_free_port udp 5060)" || fail "Could not find a free SIP port."
  local rtp_range
  rtp_range="$(find_free_udp_range 10000 101)" || fail "Could not find a free RTP range."
  RTP_START="${rtp_range%%:*}"
  RTP_END="${rtp_range##*:}"
}

main() {
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

  if ! docker_installed || ! docker_compose_ready; then
    install_docker
  fi

  ensure_docker_ready

  detect_firewall
  detect_security_frameworks
  choose_ports
  copy_project
  write_env_file
  write_preflight_json
  if [[ "${DRY_RUN}" == "true" ]]; then
    log INFO "Dry run: skipping image pull and container startup"
  else
    log INFO "Pulling required container images"
    docker compose -f "${DEPLOY_DIR}/compose.yaml" pull postgres caddy >/dev/null 2>&1 || true
  fi
  write_systemd_unit

  if [[ "${DRY_RUN}" != "true" ]]; then
    if ! wait_for_setup; then
      fail "OmniPBX containers started, but the setup UI did not become reachable in time."
    fi
  fi

  if [[ "${DRY_RUN}" == "true" ]]; then
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
    log OK "OmniPBX installer completed"
    echo "Setup URL: http://${DETECTED_HOST}:${WEB_PORT}/setup"
    echo "Local fallback: http://127.0.0.1:${WEB_PORT}/setup"
    echo "Recommended mode: ${RECOMMENDED_MODE_LABEL}"
    echo "Firewall: ${FIREWALL_NAME} (${FIREWALL_STATUS})"
    echo "Docker: ready"
  fi
}

main "$@"
