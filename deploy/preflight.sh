#!/usr/bin/env bash
set -euo pipefail

ROOT="${1:-/home/data2/research_os}"
PORT="${RESEARCH_OS_PORT:-30888}"
SAFE_DOCKER_SUBNET="${RESEARCH_OS_DOCKER_SUBNET:-10.89.0.0/24}"
SAFE_DOCKER_NETWORK="${RESEARCH_OS_DOCKER_NETWORK:-research_os_safe_default}"
LAB_ROUTE_PROBES="${RESEARCH_OS_LAB_ROUTE_PROBES:-172.19.65.113 172.18.168.43 172.18.168.44 172.18.35.126}"
FORBIDDEN_DOCKER_ROUTE_CIDRS="${RESEARCH_OS_FORBIDDEN_DOCKER_ROUTE_CIDRS:-172.18.0.0/16 172.19.0.0/16}"

echo "== Research OS preflight =="
echo "root=$ROOT"
echo "port=$PORT"

if ss -ltn | awk '{print $4}' | grep -q ":${PORT}$"; then
  if docker ps \
    --filter "label=com.docker.compose.project=research_os" \
    --filter "name=research_os-nginx" \
    --format '{{.Ports}}' | grep -q ":${PORT}->"; then
    echo "OK: port ${PORT} is already used by running Research OS nginx"
  else
    echo "ERROR: port ${PORT} is already in use by another process"
    exit 1
  fi
else
  echo "OK: port available"
fi

safe_network_config="$(docker inspect "$SAFE_DOCKER_NETWORK" --format '{{json .IPAM.Config}}' 2>/dev/null || true)"
python3 - "$SAFE_DOCKER_SUBNET" "$safe_network_config" <<'PY'
import ipaddress
import json
import subprocess
import sys

planned = ipaddress.ip_network(sys.argv[1], strict=False)
safe_network_config = sys.argv[2]
safe_network_subnets = set()
if safe_network_config:
    try:
        for item in json.loads(safe_network_config):
            subnet = item.get("Subnet")
            if subnet:
                safe_network_subnets.add(ipaddress.ip_network(subnet, strict=False))
    except json.JSONDecodeError:
        pass
routes = subprocess.check_output(["ip", "-4", "route"], text=True)

for line in routes.splitlines():
    if not line or line.startswith("default "):
        continue
    destination = line.split()[0]
    try:
        route = ipaddress.ip_network(destination, strict=False)
    except ValueError:
        continue
    if planned.overlaps(route):
        if route == planned and planned in safe_network_subnets:
            continue
        print(f"ERROR: planned Docker subnet {planned} overlaps host route:")
        print(line)
        sys.exit(1)
PY

python3 - "$FORBIDDEN_DOCKER_ROUTE_CIDRS" <<'PY'
import ipaddress
import subprocess
import sys

forbidden = [ipaddress.ip_network(item, strict=False) for item in sys.argv[1].split()]
routes = subprocess.check_output(["ip", "-4", "route"], text=True)

for line in routes.splitlines():
    if not line or line.startswith("default "):
        continue
    parts = line.split()
    destination = parts[0]
    if "dev" not in parts:
        continue
    dev = parts[parts.index("dev") + 1]
    if not (dev.startswith("br-") or dev == "docker0"):
        continue
    try:
        route = ipaddress.ip_network(destination, strict=False)
    except ValueError:
        continue
    for blocked in forbidden:
        if route.overlaps(blocked):
            print("ERROR: Docker bridge route overlaps a forbidden lab subnet:")
            print(line)
            print(f"blocked={blocked}")
            sys.exit(1)
PY

for target in $LAB_ROUTE_PROBES; do
  route_line="$(ip route get "$target" 2>/dev/null | head -n 1 || true)"
  if echo "$route_line" | grep -Eq ' dev (br-|docker0\b)'; then
    echo "ERROR: route to ${target} uses a Docker bridge:"
    echo "$route_line"
    echo "Refusing to deploy because this can break SSH for lab clients."
    exit 1
  fi
done

stale_network="$(docker inspect research_os_default --format '{{json .IPAM.Config}}' 2>/dev/null || true)"
if echo "$stale_network" | grep -q '172.19.0.0/16'; then
  echo "ERROR: stale research_os_default network uses 172.19.0.0/16."
  echo "Remove it from the server console before deploying. Do not run remote network cleanup."
  exit 1
fi

mkdir -p "$ROOT"
echo "OK: root exists"
echo "OK: lab client routes do not use Docker bridges"
echo "OK: planned Docker subnet ${SAFE_DOCKER_SUBNET} has no unsafe route overlap"
echo "OK: Docker bridge routes do not overlap forbidden lab subnets"
