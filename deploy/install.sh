#!/usr/bin/env bash
# Run from the source checkout as the ordinary Ubuntu VM account, without sudo.
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ $EUID -eq 0 ]]; then
  printf 'Run as your ordinary VM account, without sudo:\n  bash %q\n' "$script_dir/install.sh" >&2
  exit 1
fi
[[ -x /usr/bin/python3 ]] || { echo 'Python 3 is required. Ask the VM administrator to install python3, then rerun.' >&2; exit 1; }
# Python 3.12 switches to UTF-8 under the C locale, so the full-screen installer cannot tell a
# non-UTF-8 terminal from inside; decide here and let it draw ASCII only.
if [[ -z ${CLAB_INSTALLER_ASCII:-} && $(locale charmap 2>/dev/null) != UTF-8 ]]; then
  export CLAB_INSTALLER_ASCII=1
fi
exec /usr/bin/python3 "$script_dir/install-manager.py" "$@"
