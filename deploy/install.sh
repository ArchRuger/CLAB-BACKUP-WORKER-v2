#!/usr/bin/env bash
# Run from the source checkout as the ordinary Ubuntu VM account, without sudo.
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ $EUID -eq 0 ]]; then
  printf 'Run as your ordinary VM account, without sudo:\n  bash %q\n' "$script_dir/install.sh" >&2
  exit 1
fi
[[ -x /usr/bin/python3 ]] || { echo 'Python 3 is required. Ask the VM administrator to install python3, then rerun.' >&2; exit 1; }
exec /usr/bin/python3 "$script_dir/install-manager.py" "$@"
