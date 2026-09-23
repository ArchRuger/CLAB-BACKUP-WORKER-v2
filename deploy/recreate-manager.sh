#!/usr/bin/env bash
# Recreate the manager container with the current settings, without rebuilding the
# image: the capture setup calls this after changing settings. Saved data and the
# VM password are retained. Works from any directory.
#
# Detects a prepared-image installation: when deploy/image.env exists and sets
# MANAGER_IMAGE, and either the existing container already runs that image or no
# source-built clab-backup:<VERSION> image exists locally, recreate from
# deploy/compose.image.yml instead of the source-build compose file.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
[[ $# -eq 0 ]] || { echo 'Usage: sudo bash deploy/recreate-manager.sh (no options).' >&2; exit 64; }
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(dirname -- "$script_dir")

source_compose=(docker compose -f "$repo_dir/clab-backup-ui/compose.yml")
[[ -f "$repo_dir/clab-backup-ui/.env" ]] && source_compose+=(--env-file "$repo_dir/clab-backup-ui/.env")

image_env="$repo_dir/deploy/image.env"
manager_image=''
[[ -f "$image_env" ]] && manager_image=$(grep -E '^MANAGER_IMAGE=' "$image_env" | tail -n 1 | cut -d= -f2- || true)

existing=$("${source_compose[@]}" ps --all --quiet backup-ui 2>/dev/null || true)
if [[ -z "$existing" ]]; then
  printf 'No manager container exists for %s yet; it is created with the current settings by:\n  sudo bash %q\n' "$repo_dir" "$script_dir/start-manager.sh"
  exit 0
fi

compose=("${source_compose[@]}")
route='the source-build installation (clab-backup-ui/compose.yml)'
if [[ -n "$manager_image" ]]; then
  running_image=$(docker inspect --format '{{.Config.Image}}' "$existing" 2>/dev/null || true)
  source_version=$(tr -d '\r\n' < "$repo_dir/clab-backup-ui/VERSION")
  local_source_image=$(docker images --quiet "clab-backup:$source_version" 2>/dev/null || true)
  if [[ "$running_image" == "$manager_image" || -z "$local_source_image" ]]; then
    compose=(docker compose --env-file "$image_env" -f "$repo_dir/deploy/compose.image.yml")
    route='the prepared-image installation (deploy/image.env, deploy/compose.image.yml)'
  fi
fi
echo "Recreating the manager from $route."
"${compose[@]}" up -d --no-build --no-deps backup-ui
"${compose[@]}" ps
echo 'Manager recreated with the current settings; saved data and the VM password are retained.'
