#!/usr/bin/env bash
# Recreate the manager container with the current clab-backup-ui/.env, without rebuilding
# the image: the capture and Grafana setups call this after changing settings. Saved data
# and the VM password are retained. Works from any directory.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
[[ $# -eq 0 ]] || { echo 'Usage: sudo bash deploy/recreate-manager.sh (no options).' >&2; exit 64; }
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(dirname -- "$script_dir")
compose=(docker compose -f "$repo_dir/clab-backup-ui/compose.yml")
[[ -f "$repo_dir/clab-backup-ui/.env" ]] && compose+=(--env-file "$repo_dir/clab-backup-ui/.env")
existing=$("${compose[@]}" ps --all --quiet backup-ui 2>/dev/null || true)
if [[ -z "$existing" ]]; then
  printf 'No manager container exists for %s yet; it is created with the current settings by:\n  sudo bash %q\n' "$repo_dir" "$script_dir/start-manager.sh"
  exit 0
fi
"${compose[@]}" up -d --no-build --no-deps backup-ui
"${compose[@]}" ps
echo 'Manager recreated with the current clab-backup-ui/.env; saved data and the VM password are retained.'
