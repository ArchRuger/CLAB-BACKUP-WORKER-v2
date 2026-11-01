#!/usr/bin/env bash
# The manager's TLS certificate in /srv/containerlab-node-manager/tls (docs/INSTALL.md "TLS and the
# certificate"). Without an option (start-manager.sh runs this): make sure a self-signed certificate
# exists with its key, is not expiring and names the VM's addresses and names; a provided certificate,
# or one this tool did not make, is never touched, and when it cannot serve this step fails so the
# launcher stops before it recreates a manager that cannot start. Works from any directory.
#   --renew               a new self-signed certificate now (new key, new fingerprint)
#   --cert PATH --key PATH install an operator's certificate (full chain, leaf first; unencrypted key)
#   --self-signed         switch back from a provided certificate and generate
#   --name NAME           (repeatable) names and addresses the certificate must also carry; --name '' clears them
#   --prepare             recreate-manager.sh's step: settle the ports and check the files; never generates
#   --route source|image  the env file the caller's compose command reads (default source: clab-backup-ui/.env)
#   --show                print subject, names, expiry, mode, fingerprint and the primary name (no root)
#   --primary             print the primary name alone (no root)
#   --fingerprint         print the SHA-256 fingerprint alone (no root)
#   --no-recreate         leave the manager container alone (start-manager.sh recreates it itself)
# Every writing mode ends with the fingerprint and, when the certificate changed and a manager
# container exists, recreates the manager so uvicorn loads the new files.
set -euo pipefail
usage() {
  echo 'Options: --renew, --cert PATH --key PATH, --self-signed, --name NAME (repeatable), --prepare, --route source|image, --show, --primary, --fingerprint, --no-recreate.' >&2
  exit 64
}
mode=ensure; recreate=true; cert=''; key=''; names=(); have_names=false; renew=false; self_signed=false; route=source
while [[ $# -gt 0 ]]; do
  case "$1" in
    --renew) renew=true; shift;;
    --self-signed) self_signed=true; shift;;
    --cert) [[ $# -ge 2 ]] || usage; cert=$2; shift 2;;
    --key) [[ $# -ge 2 ]] || usage; key=$2; shift 2;;
    --name) [[ $# -ge 2 ]] || usage; names+=("$2"); have_names=true; shift 2;;
    --prepare) [[ $mode == ensure ]] || usage; mode=prepare; shift;;
    --route) [[ $# -ge 2 ]] || usage; route=$2; shift 2;;
    --show) [[ $mode == ensure ]] || usage; mode=show; shift;;
    --primary) [[ $mode == ensure ]] || usage; mode=primary; shift;;
    --fingerprint) [[ $mode == ensure ]] || usage; mode=fingerprint; shift;;
    --no-recreate) recreate=false; shift;;
    *) usage;;
  esac
done
case "$route" in source|image) ;; *) usage;; esac
# One writing mode at a time; --renew with --self-signed is the switch back from a provided certificate.
if $renew || $self_signed; then
  [[ $mode == ensure && -z $cert && -z $key && $have_names == false ]] || usage
  if $self_signed; then mode=self-signed; else mode=renew; fi
fi
if [[ -n $cert || -n $key ]]; then
  [[ $mode == ensure && -n $cert && -n $key && $have_names == false ]] || usage
  mode=provided
fi
if $have_names; then
  [[ $mode == ensure ]] || usage
  mode=names
fi
needs_root=true
case "$mode" in show|primary|fingerprint) needs_root=false;; esac
if $needs_root; then
  [[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
fi
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
python_args=(--route "$route" "$mode")
case "$mode" in
  provided) python_args+=("$cert" "$key");;
  names) python_args+=("${names[@]}");;
esac
if ! $needs_root || [[ $mode == prepare ]]; then
  # Read-only modes, and the prepare step that runs inside recreate-manager.sh: no recreate decision here.
  exec /usr/bin/python3 "$script_dir/setup_tls.py" "${python_args[@]}"
fi
before=$(/usr/bin/python3 "$script_dir/setup_tls.py" fingerprint 2>/dev/null || true)
/usr/bin/python3 "$script_dir/setup_tls.py" "${python_args[@]}"
after=$(/usr/bin/python3 "$script_dir/setup_tls.py" fingerprint 2>/dev/null || true)
if [[ "$after" == "$before" ]]; then
  echo 'The certificate is unchanged; the manager keeps running.'
elif $recreate; then
  # uvicorn reads /tls/cert.pem and /tls/key.pem at start, so the manager must be recreated to serve the new ones.
  bash "$script_dir/recreate-manager.sh"
else
  echo 'The manager serves the new certificate when start-manager.sh or recreate-manager.sh next creates it.'
fi
