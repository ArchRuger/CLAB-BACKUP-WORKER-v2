#!/usr/bin/env bash
# Run on the Linux VM: sudo bash deploy/setup-vm.sh
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
base=/srv/containerlab-node-manager
[[ ! -L "$base" && ! -L "$base/data" ]] || { echo 'Refusing a symlink at the persistent data path.' >&2; exit 1; }
install -d -o root -g root -m 0755 "$base"
install -d -o 10001 -g 10001 -m 0700 "$base/data"
echo "Persistent directory ready: $base/data (UID/GID 10001, mode 0700)."
echo 'Existing files were retained. Migrate any old worker data before starting a fresh manager.'
