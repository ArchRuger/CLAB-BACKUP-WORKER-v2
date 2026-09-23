#!/usr/bin/env bash
# Retire the Grafana/Prometheus telemetry stack that deploy/setup-telemetry.sh used to install:
# remove its Compose-labelled containers, volumes and pinned images, archive (or with --purge
# delete) its configuration and generated lab maps, and strip TELEMETRY_* from
# clab-backup-ui/.env. Idempotent: a VM that never installed the stack, or one already retired,
# reports nothing to do. Manager lab data is never touched. Works from any directory.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
recreate=true
python_args=()
for option in "$@"; do
  case "$option" in
    --purge) python_args+=(--purge);;
    --dry-run) python_args+=(--dry-run);;
    --no-recreate) recreate=false;;
    *) echo 'Options: --purge (delete the archived configuration and lab maps instead of moving them), --dry-run (report only, change nothing), --no-recreate (leave the manager container alone; start-manager.sh recreates it itself).' >&2; exit 64;;
  esac
done
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(dirname -- "$script_dir")
/usr/bin/python3 "$script_dir/verify-release.py" --runtime "$repo_dir"
docker compose version >/dev/null
docker info >/dev/null
/usr/bin/python3 "$script_dir/retire_telemetry.py" "${python_args[@]}"
if $recreate; then
  # The manager reads TELEMETRY_* from its environment, so it must be recreated to notice they are gone.
  bash "$script_dir/recreate-manager.sh"
else
  echo 'The manager keeps its current environment until start-manager.sh or recreate-manager.sh runs.'
fi
