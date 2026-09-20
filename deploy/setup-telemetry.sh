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
  # Grafana is on demand: provisioned and checked above, then stopped. The manager starts it through
  # the VM helper when someone opens it from a lab and stops it again after the idle time.
  "${compose[@]}" --env-file "$env_file" stop grafana
  port=$(grep -E '^TELEMETRY_GRAFANA_PORT=' "$env_file" | tail -1 | cut -d= -f2)
  idle=$(grep -E '^TELEMETRY_GRAFANA_IDLE_MINUTES=' "$env_file" | tail -1 | cut -d= -f2)
  echo "Grafana dashboards installed for TCP ${port:-3000} and stopped again: the manager starts Grafana when you open it from a lab (Tools › Open network dashboard ↗) and stops it after ${idle:-15} minutes without an open dashboard (TELEMETRY_GRAFANA_IDLE_MINUTES in clab-backup-ui/.env; 0 keeps it running once started). Anonymous viewers can read the dashboards; admin edits need the password in clab-backup-ui/.env (TELEMETRY_GRAFANA_ADMIN_PASSWORD)."
fi
if $recreate; then
  # The manager reads TELEMETRY_* from its environment, so it must be recreated to notice.
  bash "$script_dir/recreate-manager.sh"
else
  echo 'The manager picks up the telemetry settings when start-manager.sh creates it.'
fi
echo 'See docs/TELEMETRY.md.'
