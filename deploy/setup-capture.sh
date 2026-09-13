#!/usr/bin/env bash
# Install/upgrade only the optional browser capture stack; retain manager data.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(dirname -- "$script_dir")
/usr/bin/python3 "$script_dir/verify-release.py" "$repo_dir"
docker compose version >/dev/null
docker info >/dev/null
# Pull before touching settings. A fixed upstream image includes Linux Wireshark,
# cshargextcap and noVNC; nothing is installed on the browser's workstation.
image='ghcr.io/srl-labs/wireshark-vnc-docker@sha256:682c8bd42282c44f991e0d6015ce3303e5a3aa08a1e2c2b6937fd554ddb31186'
docker pull "$image"
/usr/bin/python3 "$script_dir/setup_capture.py" "$repo_dir/clab-backup-ui/.env"
# Recreate every service: an upgrade can rename the project network, and a plain
# 'up' would only restart the old Edgeshark containers on the removed network.
docker compose --env-file "$repo_dir/clab-backup-ui/.env" -f "$script_dir/compose.capture.yml" up -d --build --force-recreate --remove-orphans
echo 'Browser capture services installed. Recreate/upgrade the manager using deploy/install.sh to load the settings.'
echo 'For an already installed matching manager, from this checkout run:'
echo 'sudo docker compose --env-file clab-backup-ui/.env -f clab-backup-ui/compose.yml up -d --no-deps backup-ui'
echo 'No workstation plugin or capture-port SSH tunnel is needed. See CAPTURE.md.'
