#!/usr/bin/env bash
# Run on the Linux VM before starting the standalone manager.
set -euo pipefail
[[ $EUID -eq 0 && $# -eq 1 ]] || { echo 'Usage: sudo bash deploy/migrate-worker-data.sh OLD_CONTAINER_NAME' >&2; exit 1; }
worker=$1
[[ "$worker" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]] || { echo 'Use an exact Docker container name.' >&2; exit 1; }
target=/srv/containerlab-node-manager/data
[[ -d "$target" && ! -L "$target" && ! -L /srv/containerlab-node-manager ]] || { echo 'Run setup-vm.sh first.' >&2; exit 1; }
[[ -z $(find "$target" -mindepth 1 -maxdepth 1 -print -quit) ]] || { echo 'Destination is not empty. Refusing to overwrite saved manager data.' >&2; exit 1; }
docker inspect "$worker" >/dev/null
running=$(docker inspect --format '{{.State.Running}}' "$worker")
docker stop "$worker" >/dev/null
stage=$(mktemp -d /srv/containerlab-node-manager/migration.XXXXXX)
if ! docker cp -a "$worker:/data/." "$stage/" || [[ ! -s "$stage/state.key" || ! -s "$stage/state.enc" ]]; then
  echo "Copy failed or required state files are missing. Partial copy retained at $stage." >&2
  [[ "$running" == true ]] && docker start "$worker" >/dev/null
  exit 1
fi
if ! (cp -a "$stage/." "$target/" && chown -R 10001:10001 "$target" && chmod 0700 "$target"); then
  echo "Destination copy/permissions failed. Recovery copy retained at $stage; destination may be partial." >&2
  [[ "$running" == true ]] && docker start "$worker" >/dev/null
  exit 1
fi
chmod 0700 "$stage"
echo "Data migrated. Recovery copy retained at $stage. Old worker remains stopped."
echo 'Start the standalone manager and verify history before removing the old worker.'
