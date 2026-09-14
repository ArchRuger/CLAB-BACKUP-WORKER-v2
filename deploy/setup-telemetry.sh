#!/usr/bin/env bash
# Install or upgrade the Grafana dashboards and lab maps, part of every installation
# (deploy/install.sh and start-manager.sh run it), or remove them with --remove.
# Manager data is never touched. Works from any directory.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
remove=false; recreate=true
for option in "$@"; do
  case "$option" in
    --remove) remove=true;;
    --no-recreate) recreate=false;;
    *) echo 'Options: --remove (stop the dashboards, clear their session data and set TELEMETRY_STACK=disabled), --no-recreate (leave the manager container alone; start-manager.sh recreates it itself).' >&2; exit 64;;
  esac
done
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(dirname -- "$script_dir")
/usr/bin/python3 "$script_dir/verify-release.py" --runtime "$repo_dir"
docker compose version >/dev/null
docker info >/dev/null
env_file="$repo_dir/clab-backup-ui/.env"
config_dir=/srv/containerlab-node-manager/telemetry
compose=(docker compose -f "$script_dir/compose.telemetry.yml")
if $remove; then
  if [[ -f "$env_file" ]]; then
    "${compose[@]}" --env-file "$env_file" down --volumes --remove-orphans || true
  fi
  /usr/bin/python3 "$script_dir/setup_telemetry.py" "$env_file" "$config_dir" --remove
  rm -rf "$config_dir/plugins"
  echo 'Grafana dashboards removed; TELEMETRY_STACK=disabled in clab-backup-ui/.env (the admin password is kept for a later reinstall).'
else
  # The generated lab maps live inside the manager data directory, so it must exist first.
  [[ -d /srv/containerlab-node-manager/data ]] || bash "$script_dir/setup-vm.sh"
  /usr/bin/python3 "$script_dir/setup_telemetry.py" "$env_file" "$config_dir"
  "${compose[@]}" --env-file "$env_file" pull
  # The Flow panel that renders the manager-generated lab maps: installed once, pinned, kept on disk.
  /usr/bin/python3 "$script_dir/setup_telemetry.py" "$env_file" "$config_dir" --plugin
  # Recreate every service so a changed port or password takes effect.
  "${compose[@]}" --env-file "$env_file" up -d --force-recreate --remove-orphans
  # A service that starts and then crash-loops (a rejected flag, an unreadable scrape
  # configuration, a busy port) must fail here, not as errors on every dashboard panel.
  if ! /usr/bin/python3 "$script_dir/setup_telemetry.py" "$env_file" --wait; then
    echo 'The telemetry services did not become ready. Last log lines:' >&2
    "${compose[@]}" --env-file "$env_file" ps >&2 || true
    "${compose[@]}" --env-file "$env_file" logs --tail=20 >&2 || true
    exit 1
  fi
  port=$(grep -E '^TELEMETRY_GRAFANA_PORT=' "$env_file" | tail -1 | cut -d= -f2)
  echo "Grafana dashboards installed on TCP ${port:-3000}; anonymous viewers can read them, admin edits need the password in clab-backup-ui/.env (TELEMETRY_GRAFANA_ADMIN_PASSWORD)."
fi
if $recreate; then
  # The manager reads TELEMETRY_* from its environment, so it must be recreated to notice.
  bash "$script_dir/recreate-manager.sh"
else
  echo 'The manager picks up the telemetry settings when start-manager.sh creates it.'
fi
echo 'See docs/TELEMETRY.md.'
