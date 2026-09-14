#!/usr/bin/env bash
# Install or upgrade the browser Wireshark capture stack, part of every installation
# (deploy/install.sh and start-manager.sh run it), or remove it with --remove.
# Manager data is never touched. Works from any directory.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
remove=false; recreate=true
for option in "$@"; do
  case "$option" in
    --remove) remove=true;;
    --no-recreate) recreate=false;;
    *) echo 'Options: --remove (stop the capture services and set CAPTURE_PROVIDER=disabled), --no-recreate (leave the manager container alone; start-manager.sh recreates it itself).' >&2; exit 64;;
  esac
done
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(dirname -- "$script_dir")
/usr/bin/python3 "$script_dir/verify-release.py" --runtime "$repo_dir"
docker compose version >/dev/null
docker info >/dev/null
env_file="$repo_dir/clab-backup-ui/.env"
compose=(docker compose -f "$script_dir/compose.capture.yml")
if $remove; then
  if [[ -f "$env_file" ]]; then
    "${compose[@]}" --env-file "$env_file" down --remove-orphans || true
  fi
  /usr/bin/python3 "$script_dir/setup_capture.py" "$env_file" --remove
  echo 'Browser capture services removed; CAPTURE_PROVIDER=disabled in clab-backup-ui/.env (the session token is kept for a later reinstall).'
else
  # Pull before touching settings. The fixed upstream image includes Linux Wireshark,
  # cshargextcap and noVNC; nothing is installed on the browser's workstation.
  image='ghcr.io/srl-labs/wireshark-vnc-docker@sha256:682c8bd42282c44f991e0d6015ce3303e5a3aa08a1e2c2b6937fd554ddb31186'
  docker pull "$image"
  /usr/bin/python3 "$script_dir/setup_capture.py" "$env_file"
  # Recreate every service: an upgrade can rename the project network, and a plain
  # 'up' would only restart the old Edgeshark containers on the removed network.
  "${compose[@]}" --env-file "$env_file" up -d --build --force-recreate --remove-orphans
  echo 'Browser capture services installed: Edgeshark on 127.0.0.1:5001 and the session service on 127.0.0.1:5801. No workstation plugin or tunnel is needed.'
fi
if $recreate; then
  # The manager reads CAPTURE_* from its environment, so it must be recreated to notice.
  bash "$script_dir/recreate-manager.sh"
else
  echo 'The manager picks up the capture settings when start-manager.sh creates it.'
fi
echo 'See docs/CAPTURE.md.'
