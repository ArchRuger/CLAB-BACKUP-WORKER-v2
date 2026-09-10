#!/usr/bin/env bash
# Enable approved lab-level host operations while retaining the discovery key.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
roots=(); network=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --lab-root) [[ $# -ge 2 ]] || exit 64; roots+=("$2"); shift 2;;
    --allow-downloads) network=true; shift;;
    *) echo 'Options: --lab-root /trusted/directory --allow-downloads' >&2; exit 64;;
  esac
done
[[ -f /home/clab-discovery/.ssh/authorized_keys && -f /etc/sudoers.d/clab-manager-discovery ]] || { echo 'Set up the discovery account first.' >&2; exit 1; }
clab_bin=$(readlink -f "$(command -v containerlab)")
docker_bin=$(readlink -f "$(command -v docker)")
git_bin=$(command -v git || true)
for binary in "$clab_bin" "$docker_bin" ${git_bin:+"$git_bin"}; do
  [[ "$binary" =~ ^/usr/(local/)?bin/[A-Za-z0-9._-]+$ && $(stat -c %u "$binary") == 0 ]] || { echo 'Use root-owned binaries in /usr/bin or /usr/local/bin.' >&2; exit 1; }
  binary_mode=$(stat -c %a "$binary")
  (( (8#$binary_mode & 8#022) == 0 )) || exit 1
done
[[ ! -L /srv/containerlab-node-manager && ! -L /srv/containerlab-node-manager/projects && ! -L /usr/local/lib/clab-manager && ! -L /home/clab-discovery/.ssh && ! -L /home/clab-discovery/.ssh/authorized_keys ]] || exit 1
[[ ! -L /etc/clab-manager && ! -L /etc/clab-manager/operations.json && ! -L /usr/local/sbin/clab-manager-operate && ! -L /usr/local/sbin/clab-manager-gateway && ! -L /usr/local/lib/clab-manager/host_operations.py ]] || exit 1
install -d -o root -g root -m 0700 /etc/clab-manager
install -d -o root -g root -m 0755 /srv/containerlab-node-manager/projects
/usr/bin/python3 - "$clab_bin" "$docker_bin" "$git_bin" "$network" "${roots[@]}" <<'PY'
import json, os, pathlib, sys
path=pathlib.Path('/etc/clab-manager/operations.json')
old=json.loads(path.read_text()) if path.exists() else {}
roots=set(old.get('roots', ['/etc/containerlab','/srv/containerlab-node-manager/projects']))
for value in sys.argv[5:]:
    p=pathlib.Path(value)
    if not p.is_absolute() or '..' in p.parts or str(p)=='/' or any(q.is_symlink() for q in (p,*p.parents)):
        sys.exit('Use absolute trusted project roots without symlinks; filesystem root is not allowed.')
    roots.add(str(p))
value=dict(clab=sys.argv[1],docker=sys.argv[2],git=sys.argv[3] or '/usr/bin/git',roots=sorted(roots),
           projects='/srv/containerlab-node-manager/projects',network=old.get('network',False) or sys.argv[4]=='true',
           )
tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value));os.chmod(tmp,0o600);os.replace(tmp,path)
PY
install -o root -g root -m 0644 "$script_dir/../clab-backup-ui/app/host_operations.py" /usr/local/lib/clab-manager/host_operations.py
temp_dir=$(mktemp -d)
trap 'rm -f -- "$temp_dir/operate" "$temp_dir/gateway" "$temp_dir/sudoers"; rmdir -- "$temp_dir"' EXIT
cat > "$temp_dir/operate" <<'SH'
#!/bin/sh
set -eu
[ "$#" -eq 0 ] || exit 64
cd /
exec /usr/bin/env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin HOME=/root /usr/bin/python3 -I /usr/local/lib/clab-manager/host_operations.py
SH
cat > "$temp_dir/gateway" <<'SH'
#!/bin/sh
set -eu
[ "$#" -eq 0 ] || exit 64
case "${SSH_ORIGINAL_COMMAND:-}" in
  clab-manager-operations) exec sudo -n /usr/local/sbin/clab-manager-operate ;;
  'sudo -n /usr/local/sbin/clab-manager-inspect'|'containerlab inspect --all --format json'|'') exec sudo -n /usr/local/sbin/clab-manager-inspect ;;
  *) echo 'Only manager discovery and structured lab operations are supported.' >&2; exit 64 ;;
esac
SH
printf '%s\n' 'clab-discovery ALL=(root) NOPASSWD: /usr/local/sbin/clab-manager-inspect "", /usr/local/sbin/clab-manager-operate ""' > "$temp_dir/sudoers"
visudo -cf "$temp_dir/sudoers"
install -o root -g root -m 0755 "$temp_dir/operate" /usr/local/sbin/clab-manager-operate
install -o root -g root -m 0755 "$temp_dir/gateway" /usr/local/sbin/clab-manager-gateway
install -o root -g root -m 0440 "$temp_dir/sudoers" /etc/sudoers.d/clab-manager-discovery
/usr/bin/python3 - <<'PY'
from pathlib import Path
import os
path=Path('/home/clab-discovery/.ssh/authorized_keys')
if path.is_symlink(): raise SystemExit('Refusing symlink at authorized_keys.')
raw=path.read_text()
old='restrict,command="sudo -n /usr/local/sbin/clab-manager-inspect" '
new='restrict,command="/usr/local/sbin/clab-manager-gateway" '
lines=raw.splitlines()
if not lines or any(not line.startswith((old,new)) for line in lines): raise SystemExit('Unknown authorized_keys options; retain existing file and review account setup.')
updated='\n'.join(new+line.split('" ',1)[1] for line in lines)+'\n'
tmp=path.with_suffix('.tmp');tmp.write_text(updated);os.chmod(tmp,0o644);os.replace(tmp,path)
PY
echo 'Lab operations enabled. Existing SSH public keys retained. Trusted project roots and optional permissions are in /etc/clab-manager/operations.json.'
