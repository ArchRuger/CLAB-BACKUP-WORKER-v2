#!/usr/bin/env bash
# One host-side entry point for fresh setup and upgrades. Existing passwords are retained.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
password_args=(); operations=false; operation_args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --reset-password) password_args+=(--reset-password); shift;;
    --enable-operations) operations=true; shift;;
    --lab-root) [[ $# -ge 2 ]] || exit 64; operation_args+=("$1" "$2"); operations=true; shift 2;;
    --allow-downloads) operation_args+=("$1"); operations=true; shift;;
    *) echo 'Options: --reset-password, --enable-operations, --lab-root PATH, --allow-downloads. Public keys are no longer used.' >&2; exit 64;;
  esac
done
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(dirname -- "$script_dir")
command -v docker >/dev/null || { echo 'Install Docker first; see FRESH-VM-GUIDE.md.' >&2; exit 1; }
docker compose version >/dev/null
docker info >/dev/null
bash "$script_dir/setup-discovery.sh" "${password_args[@]}"
# Fail before recreation if the installed helper cannot return file-transfer data.
# Only the version is printed: its response may contain inventory credentials.
expected=$(tr -d '\r\n' < "$repo_dir/clab-backup-ui/VERSION")
/usr/local/sbin/clab-manager-inspect | /usr/bin/python3 "$script_dir/verify-helper.py" "$expected"
if $operations || [[ -f /etc/clab-manager/operations.json ]]; then
  bash "$script_dir/setup-operations.sh" "${operation_args[@]}"
  printf '%s\n' '{"mode":"capabilities"}' | /usr/local/sbin/clab-manager-operate | /usr/bin/python3 "$script_dir/verify-operations.py" "$expected"
fi
bash "$script_dir/setup-vm.sh"
cd -- "$repo_dir"
docker compose -f clab-backup-ui/compose.yml build --pull --no-cache
# Avoid starting a second manager over data owned by a docker-run installation.
running_containers=$(docker ps -q)
for container in $running_containers; do
  uses_data=$(docker inspect --format '{{json .Mounts}}' "$container" | /usr/bin/python3 -c '
import json, sys
mounts = json.load(sys.stdin)
print("yes" if any(m.get("Source", "").rstrip("/") == "/srv/containerlab-node-manager/data" for m in mounts) else "no")
')
  [[ "$uses_data" == yes ]] || continue
  project=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$container")
  service=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$container")
  if [[ "$project" != containerlab-node-manager || "$service" != backup-ui ]]; then
    echo 'Another running container uses the manager data. Follow the Docker-run migration in FRESH-VM-GUIDE.md before starting Compose.' >&2
    exit 1
  fi
done
docker compose -f clab-backup-ui/compose.yml up -d --force-recreate
docker compose -f clab-backup-ui/compose.yml ps
echo 'Open the manager on TCP 8081 (or your configured UI_PORT). Saved data and existing discovery password are retained.'
echo 'The UI opens directly without a login. VM and device SSH credentials remain in persistent storage.'
