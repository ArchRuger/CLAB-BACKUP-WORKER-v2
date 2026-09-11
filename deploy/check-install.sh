#!/usr/bin/env bash
# Diagnose an existing VM installation without installing or repairing it.
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[[ -x /usr/bin/python3 ]] || { echo 'Python 3 is required. Run this check inside the Ubuntu VM.' >&2; exit 1; }
exec /usr/bin/python3 "$script_dir/check_install.py" "$@"
