#!/usr/bin/env bash
# One host-side entry point for fresh setup and upgrades. Existing passwords are retained.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
password_args=(); operations=false; operation_args=(); manager_only=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --reset-password) password_args+=(--reset-password); shift;;
    --enable-operations) operations=true; shift;;
    --lab-root) [[ $# -ge 2 ]] || exit 64; operation_args+=("$1" "$2"); operations=true; shift 2;;
    --allow-downloads) operation_args+=("$1"); operations=true; shift;;
    --manager-only) manager_only=true; shift;;
    *) echo 'Options: --reset-password, --enable-operations, --lab-root PATH, --allow-downloads, --manager-only (skip the browser Wireshark stack). Public keys are no longer used.' >&2; exit 64;;
  esac
done
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(dirname -- "$script_dir")
# The runtime lockstep set only: a documentation mismatch is CI's business, not the VM's.
/usr/bin/python3 "$script_dir/verify-release.py" --runtime "$repo_dir"
command -v docker >/dev/null || { echo 'Install Docker first; see docs/FRESH-VM-GUIDE-V2.md.' >&2; exit 1; }
docker compose version >/dev/null
docker info >/dev/null
# The data directory must exist before setup-discovery writes the one-time VM connection seed into it.
bash "$script_dir/setup-vm.sh"
bash "$script_dir/setup-discovery.sh" "${password_args[@]}" --data-dir /srv/containerlab-node-manager/data
# Fail before recreation if the installed helper cannot return file-transfer data.
# Only the version is printed: its response may contain inventory credentials.
expected=$(tr -d '\r\n' < "$repo_dir/clab-backup-ui/VERSION")
/usr/local/sbin/clab-manager-inspect | /usr/bin/python3 "$script_dir/verify-helper.py" "$expected"
gateway_args=()
if $operations || [[ -f /etc/clab-manager/operations.json ]]; then
  bash "$script_dir/setup-operations.sh" "${operation_args[@]}"
  printf '%s\n' '{"mode":"capabilities"}' | /usr/local/sbin/clab-manager-operate | /usr/bin/python3 "$script_dir/verify-operations.py" "$expected"
  gateway_args+=(--operations)
fi
if [[ -f /etc/clab-manager/engineer.json ]]; then
  # setup-operations.sh and a containerlab upgrade reset the lab roots and SUID
  # bit; reapply the recorded engineer (VS Code) access so it survives upgrades.
  bash "$script_dir/setup-engineer-access.sh" --refresh
fi
if [[ -f /etc/clab-manager/git.json ]]; then
  bash "$script_dir/setup-git.sh" --refresh
  printf '%s\n' '{"mode":"list"}' | /usr/local/sbin/clab-manager-git | /usr/bin/python3 -c '
import json, sys
value=json.load(sys.stdin).get("result",{})
if value.get("protocol")!="clab-manager-git-v1" or value.get("version")!=sys.argv[1]:
    sys.exit("Installed Git helper version/protocol does not match this source release.")
print("Git helper version verified; repository bindings retained.")
' "$expected"
  gateway_args+=(--git)
fi
# Root-only helper checks cannot prove the account's forced gateway can invoke
# them. Exercise the same read-only requests under clab-discovery before build.
/usr/bin/python3 "$script_dir/verify-gateway.py" "$expected" "${gateway_args[@]}"
# The browser Wireshark stack is part of every installation and follows the release (the
# session service image carries the version), so an upgrade refreshes it before the manager is
# created with the settings it writes into clab-backup-ui/.env. An explicit 'disabled' written
# by setup-capture.sh --remove is respected. The retired Grafana/Prometheus telemetry stack is
# always cleaned up too (a no-op once nothing of it remains); it runs once here, before the
# image build, and again below after the new manager is up, since the old manager's own
# background loop can recreate its data folder while it is still running.
env_file="$repo_dir/clab-backup-ui/.env"
env_value() { local value=''; if [[ -f "$env_file" ]]; then value=$(grep -E "^$1=" "$env_file" | tail -n 1 | cut -d= -f2- || true); fi; printf '%s' "$value"; }
if ! $manager_only; then
  if [[ $(env_value CAPTURE_PROVIDER) == disabled ]]; then
    echo 'Browser capture is disabled in clab-backup-ui/.env; its stack is left alone (sudo bash deploy/setup-capture.sh re-enables it).'
  else
    bash "$script_dir/setup-capture.sh" --no-recreate
  fi
fi
bash "$script_dir/retire-telemetry.sh" --no-recreate
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
    echo 'Another running container uses the manager data. Follow the Docker-run migration in docs/FRESH-VM-GUIDE-V2.md before starting Compose.' >&2
    exit 1
  fi
done
docker compose -f clab-backup-ui/compose.yml up -d --force-recreate
# The old manager's own telemetry loop can recreate its data folder every few seconds while it
# runs; repeat the retirement now that the new manager (which has no such loop) is up, so nothing
# reappears after the early call above. Idempotent: a no-op once nothing of the old stack remains.
bash "$script_dir/retire-telemetry.sh" --no-recreate
docker compose -f clab-backup-ui/compose.yml ps
echo 'Open the manager on TCP 8081 (or your configured UI_PORT). Saved data and existing discovery password are retained.'
$manager_only || echo 'Wireshark opens from the map (Capture packets).'
printf 'Optional Git setup: as your ordinary VM account, run (without sudo):\n  bash %q\n' "$script_dir/setup-git.sh"
echo 'Use the guided prompts to configure commit name/email and GitHub login, then register. See docs/GIT-SETUP.md.'
echo 'The UI opens directly without a login. VM and device SSH credentials remain in persistent storage.'
printf 'After configuring the VM connection, run the full health report as your ordinary account:\n  bash %q\n' "$script_dir/check-install.sh"
