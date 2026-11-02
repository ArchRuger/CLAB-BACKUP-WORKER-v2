#!/usr/bin/env bash
# Recovery of a lost administrator password (docs/sign-on/DESIGN.md 9.5, EXPOSURE.md 7.1). Works from
# any directory: sudo bash deploy/manager-recover-admin.sh (no options).
#
# Finds the manager container exactly as recreate-manager.sh does (source build, or a prepared image
# from deploy/image.env), refuses with the start command when it is not running, runs `python -m app.recover` inside it and prints its output unchanged: the
# recovery code and how long it is valid. app.recover changes no account; it opens the setup page for
# 15 minutes so one new administrator can be created. When it succeeds, this script prints one line of
# its own, last: the address of that page, https://<primary>:<UI_PORT>/setup?recover=1, with the
# certificate's primary name from setup-tls.sh --primary and UI_PORT from the env file the chosen route
# uses (default 8443; the port is left out at 443). The container does not know the VM's TLS port,
# which is why the address is built here. The exit status is app.recover's.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
[[ $# -eq 0 ]] || { echo 'Usage: sudo bash deploy/manager-recover-admin.sh (no options).' >&2; exit 64; }
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(dirname -- "$script_dir")

source_compose=(docker compose -f "$repo_dir/clab-backup-ui/compose.yml")
[[ -f "$repo_dir/clab-backup-ui/.env" ]] && source_compose+=(--env-file "$repo_dir/clab-backup-ui/.env")

image_env="$repo_dir/deploy/image.env"
manager_image=''
[[ -f "$image_env" ]] && manager_image=$(grep -E '^MANAGER_IMAGE=' "$image_env" | tail -n 1 | cut -d= -f2- || true)

existing=$("${source_compose[@]}" ps --all --quiet backup-ui 2>/dev/null | head -n 1 || true)
if [[ -z "$existing" ]]; then
  printf 'No manager container exists for %s; start it with:\n  sudo bash %q\n' "$repo_dir" "$script_dir/start-manager.sh" >&2
  exit 1
fi
# app.recover runs inside the container, so a stopped, paused or restarting one is refused here with the
# way out instead of docker's daemon error.
state=$(docker inspect --format '{{.State.Status}}' "$existing" 2>/dev/null || true)
if [[ "$state" != running ]]; then
  printf 'The manager container %s is %s, not running; the recovery runs inside it. Start the manager with:\n  sudo bash %q\nthen rerun this script.\n' \
    "$existing" "${state:-in an unknown state}" "$script_dir/start-manager.sh" >&2
  exit 1
fi

env_file="$repo_dir/clab-backup-ui/.env"
route='the source-build installation (clab-backup-ui/compose.yml)'
if [[ -n "$manager_image" ]]; then
  running_image=$(docker inspect --format '{{.Config.Image}}' "$existing" 2>/dev/null || true)
  source_version=$(tr -d '\r\n' < "$repo_dir/clab-backup-ui/VERSION")
  local_source_image=$(docker images --quiet "clab-backup:$source_version" 2>/dev/null || true)
  if [[ "$running_image" == "$manager_image" || -z "$local_source_image" ]]; then
    env_file="$image_env"
    route='the prepared-image installation (deploy/image.env, deploy/compose.image.yml)'
  fi
fi
echo "Recovering through the manager of $route."

status=0
docker exec "$existing" python -m app.recover || status=$?
(( status == 0 )) || exit "$status"

# The env_value reader of start-manager.sh, on the chosen route's file.
env_value() { local value=''; if [[ -f "$env_file" ]]; then value=$(grep -E "^(export )?$1=" "$env_file" | tail -n 1 | cut -d= -f2- || true); fi; printf '%s' "$value"; }
port=$(env_value UI_PORT)
port=${port:-8443}
if [[ ! $port =~ ^[0-9]{1,5}$ ]] || (( 10#$port < 1 || 10#$port > 65535 )); then
  echo "UI_PORT in $env_file is not a port number; the address below assumes 8443." >&2
  port=8443
fi
port=$((10#$port))
primary=$(bash "$script_dir/setup-tls.sh" --primary 2>/dev/null | head -n 1 | tr -d '\r') || primary=''
[[ $primary =~ ^[A-Za-z0-9.:-]+$ ]] || primary='<VM address>'
[[ $primary != *:* ]] || primary="[$primary]"
authority=$primary
(( port == 443 )) || authority="$primary:$port"
echo "Open https://$authority/setup?recover=1 within 15 minutes and create one new administrator."
