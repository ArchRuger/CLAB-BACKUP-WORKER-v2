#!/usr/bin/env bash
# Engineer access for VS Code Remote - SSH and the Containerlab extension.
#
# The manager never needs any of this: it runs containerlab through sudo behind
# its restricted clab-discovery gateway. The engineer's own VS Code session does:
# the Containerlab extension refuses to activate unless the account is in the
# docker and clab_admins groups, its file explorer cannot create lab folders in
# a root-owned lab root, and "containerlab deploy" from its terminal needs the
# upstream sudo-less SUID mode. This script grants exactly that to one ordinary
# account, records it, and is safe to rerun (start-manager.sh reapplies it).
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
config=/etc/clab-manager/engineer.json
operations=/etc/clab-manager/operations.json
owner=''; refresh=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --owner) [[ $# -ge 2 ]] || exit 64; owner=$2; shift 2;;
    --refresh) refresh=true; shift;;
    *) echo 'Usage: sudo bash deploy/setup-engineer-access.sh --owner LINUX_USER, or --refresh to reapply the saved account.' >&2; exit 64;;
  esac
done
[[ ! -L "$config" && ! -L "$operations" && ! -L /etc/clab-manager ]] || { echo 'Refusing a symlink at a manager configuration path.' >&2; exit 1; }
if $refresh; then
  [[ -n "$owner" ]] && { echo '--refresh reapplies the saved account; do not combine it with --owner.' >&2; exit 64; }
  [[ -f "$config" ]] || { echo 'Engineer access is not configured; nothing to refresh.'; exit 0; }
  owner=$(/usr/bin/python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["owner"])' "$config")
fi
owner=${owner:-${SUDO_USER:-}}
[[ -n "$owner" ]] || { echo 'Supply --owner LINUX_USER: your ordinary VM account, not clab-discovery.' >&2; exit 64; }
id "$owner" >/dev/null 2>&1 || { echo "Linux account '$owner' does not exist. Use the account VS Code logs in with (run whoami there)." >&2; exit 1; }
[[ $(id -u "$owner") -ne 0 && "$owner" != clab-discovery ]] || { echo 'Choose the ordinary engineer account, never root or clab-discovery.' >&2; exit 1; }
if [[ ! -f "$operations" ]]; then
  if $refresh; then echo 'Lab operations are not enabled; engineer access refresh skipped.'; exit 0; fi
  echo 'Enable lab operations first: sudo bash deploy/start-manager.sh --enable-operations' >&2; exit 1
fi
getent group docker >/dev/null || { echo 'Install Docker first with bash deploy/install.sh.' >&2; exit 1; }
clab_path=$(command -v containerlab) || { echo 'containerlab is not installed or not on PATH.' >&2; exit 1; }
clab_bin=$(readlink -f "$clab_path")
[[ "$clab_bin" =~ ^/usr/(local/)?bin/[A-Za-z0-9._-]+$ && $(stat -c %u "$clab_bin") == 0 ]] || { echo 'containerlab must be a root-owned binary in /usr/bin or /usr/local/bin.' >&2; exit 1; }
(( (8#$(stat -c %a "$clab_bin") & 8#022) == 0 )) || { echo 'The containerlab binary must not be group/other writable.' >&2; exit 1; }

# 1. Groups the Containerlab extension checks with id -nG. Both are root-equivalent,
#    which is why only the one named engineer account gets them.
groupadd -r -f clab_admins
usermod -aG docker,clab_admins "$owner"

# 2. Trusted lab roots, read from the operations configuration so custom --lab-root
#    folders are covered too. Group clab_admins, setgid so files the engineer or the
#    manager create inherit the group, group write so VS Code can create and edit.
mapfile -t roots < <(/usr/bin/python3 -c 'import json, sys; [print(r) for r in json.load(open(sys.argv[1]))["roots"]]' "$operations")
applied=()
for root in "${roots[@]}"; do
  [[ "$root" == /* && -d "$root" && ! -L "$root" ]] || continue
  chgrp -R clab_admins -- "$root"
  find "$root" -type d -exec chmod 2775 -- {} +
  find "$root" -type f -exec chmod g+rw -- {} +
  applied+=("$root")
done

# 3. Upstream sudo-less mode: clab_admins members run the SUID binary. The
#    installer strips this bit on a fresh containerlab install, so it is restored
#    here and again by start-manager.sh --refresh after any package upgrade.
chmod 4755 "$clab_bin"

install -d -o root -g root -m 0700 /etc/clab-manager
/usr/bin/python3 -c 'import json, os, sys
tmp = sys.argv[2] + ".tmp"
with open(tmp, "w") as stream: json.dump({"owner": sys.argv[1]}, stream)
os.chmod(tmp, 0o600); os.replace(tmp, sys.argv[2])' "$owner" "$config"

echo "Engineer access ready for $owner: docker and clab_admins groups, containerlab SUID restored,"
echo "group-writable lab folders: ${applied[*]:-none}."
echo 'New groups apply to new logins only: reconnect your SSH session, and in VS Code run'
echo '"Remote-SSH: Kill VS Code Server on Host..." and reconnect before using the Containerlab extension.'
