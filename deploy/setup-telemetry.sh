#!/usr/bin/env bash
# Install/upgrade (or remove with --remove) the optional Grafana dashboards; retain manager data.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
remove=false
case "${1:-}" in
  '') ;;
  --remove) remove=true;;
  *) echo 'Options: --remove (stop the dashboards and clear their session data).' >&2; exit 64;;
esac
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(dirname -- "$script_dir")
/usr/bin/python3 "$script_dir/verify-release.py" "$repo_dir"
docker compose version >/dev/null
docker info >/dev/null
env_file="$repo_dir/clab-backup-ui/.env"
config_dir=/srv/containerlab-node-manager/telemetry
if $remove; then
  if [[ -f "$env_file" ]]; then
    docker compose --env-file "$env_file" -f "$script_dir/compose.telemetry.yml" down --volumes --remove-orphans || true
  fi
  /usr/bin/python3 "$script_dir/setup_telemetry.py" "$env_file" "$config_dir" --remove
  rm -rf "$config_dir/plugins"
  echo 'Recreate the manager (deploy/install.sh, or the compose command below) so it stops offering the Grafana link.'
else
  /usr/bin/python3 "$script_dir/setup_telemetry.py" "$env_file" "$config_dir"
  docker compose --env-file "$env_file" -f "$script_dir/compose.telemetry.yml" pull
  # The Flow panel that renders the manager-generated lab maps: installed once, pinned, kept on disk.
  /usr/bin/python3 "$script_dir/setup_telemetry.py" "$env_file" "$config_dir" --plugin
  # Recreate every service so a changed port or password takes effect.
  docker compose --env-file "$env_file" -f "$script_dir/compose.telemetry.yml" up -d --force-recreate --remove-orphans
  # A service that starts and then crash-loops (a rejected flag, an unreadable scrape
  # configuration, a busy port) must fail here, not as errors on every dashboard panel.
  if ! /usr/bin/python3 "$script_dir/setup_telemetry.py" "$env_file" --wait; then
    echo 'The telemetry services did not become ready. Last log lines:' >&2
    docker compose --env-file "$env_file" -f "$script_dir/compose.telemetry.yml" ps >&2 || true
    docker compose --env-file "$env_file" -f "$script_dir/compose.telemetry.yml" logs --tail=20 >&2 || true
    exit 1
  fi
  port=$(grep -E '^TELEMETRY_GRAFANA_PORT=' "$env_file" | tail -1 | cut -d= -f2)
  echo "Grafana dashboards installed on TCP ${port:-3000}; anonymous viewers can read them, admin edits need the password in clab-backup-ui/.env (TELEMETRY_GRAFANA_ADMIN_PASSWORD)."
fi
echo 'For an already installed matching manager, from this checkout run:'
echo 'sudo docker compose --env-file clab-backup-ui/.env -f clab-backup-ui/compose.yml up -d --no-deps backup-ui'
echo 'See docs/TELEMETRY.md.'
