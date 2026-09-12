#!/usr/bin/env bash
# Run on the Linux VM: sudo bash deploy/setup-discovery.sh
set -euo pipefail
[[ $EUID -eq 0 && $# -le 1 ]] || { echo 'Usage: sudo bash deploy/setup-discovery.sh [--reset-password|--update-helper]' >&2; exit 1; }
password_args=()
case "${1:-}" in
  --reset-password) password_args+=(--reset-password);;
  ''|--update-helper) ;;
  *) echo 'Public key setup has been replaced. Run without arguments to create or retain the VM password.' >&2; exit 64;;
esac
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
[[ -x /usr/bin/python3 ]] || { echo 'Install python3 first.' >&2; exit 1; }
command -v visudo >/dev/null || { echo 'Install sudo first.' >&2; exit 1; }
command -v sshd >/dev/null || [[ -x /usr/sbin/sshd ]] || { echo 'Install and enable the SSH server first.' >&2; exit 1; }
clab_path=$(command -v containerlab) || { echo 'containerlab is not installed or not on PATH. Run bash deploy/install.sh or install it in /usr/bin or /usr/local/bin first.' >&2; exit 1; }
clab_bin=$(readlink -f "$clab_path")
[[ "$clab_bin" =~ ^/usr/(local/)?bin/[A-Za-z0-9._-]+$ ]] || { echo 'Install containerlab in /usr/bin or /usr/local/bin.' >&2; exit 1; }
[[ $(stat -c %u "$clab_bin") == 0 ]] || { echo 'The containerlab binary must be owned by root.' >&2; exit 1; }
mode=$(stat -c %a "$clab_bin")
(( (8#$mode & 8#022) == 0 )) || { echo 'The containerlab binary must not be writable by group/others.' >&2; exit 1; }
docker_path=$(command -v docker) || { echo 'Docker is not installed or not on PATH. Run bash deploy/install.sh first.' >&2; exit 1; }
docker_bin=$(readlink -f "$docker_path")
[[ "$docker_bin" =~ ^/usr/(local/)?bin/[A-Za-z0-9._-]+$ && $(stat -c %u "$docker_bin") == 0 ]] || { echo 'Install a root-owned Docker binary in /usr/bin or /usr/local/bin.' >&2; exit 1; }
docker_mode=$(stat -c %a "$docker_bin")
(( (8#$docker_mode & 8#022) == 0 )) || { echo 'Docker must not be writable by group/others.' >&2; exit 1; }
account=clab-discovery
if ! id "$account" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/sh "$account"
  usermod --password '*' "$account"
fi
home_dir=$(getent passwd "$account" | cut -d: -f6)
[[ "$home_dir" == /home/clab-discovery ]] || { echo 'Expected /home/clab-discovery for the discovery account.' >&2; exit 1; }
[[ ! -L "$home_dir/.ssh" && ! -L "$home_dir/.ssh/authorized_keys" ]] || { echo 'Refusing a symlink in the dedicated SSH key path.' >&2; exit 1; }
tmp=$(mktemp -d)
trap 'rm -f -- "$tmp/helper" "$tmp/sudoers"; rmdir -- "$tmp"' EXIT
cat > "$tmp/helper" <<EOF
#!/bin/sh
set -eu
[ "\$#" -eq 0 ] || exit 64
cd /
exec /usr/bin/env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin HOME=/root /usr/bin/python3 -I /usr/local/lib/clab-manager/clab_manager_files.py "$clab_bin" "$docker_bin"
EOF
[[ ! -L /usr/local/lib/clab-manager && ! -L /usr/local/lib/clab-manager/clab_manager_files.py && ! -L /usr/local/sbin/clab-manager-inspect ]] || { echo 'Refusing symlink at helper install location.' >&2; exit 1; }
install -d -o root -g root -m 0755 /usr/local/lib/clab-manager
install -o root -g root -m 0644 "$script_dir/../clab-backup-ui/app/host_files.py" /usr/local/lib/clab-manager/clab_manager_files.py
install -o root -g root -m 0755 "$tmp/helper" /usr/local/sbin/clab-manager-inspect
# Preserve operations permissions on helper upgrades and password resets.
if [[ ! -f /etc/sudoers.d/clab-manager-discovery ]]; then
  printf '%s\n' 'clab-discovery ALL=(root) NOPASSWD: /usr/local/sbin/clab-manager-inspect ""' > "$tmp/sudoers"
  visudo -cf "$tmp/sudoers"
  install -o root -g root -m 0440 "$tmp/sudoers" /etc/sudoers.d/clab-manager-discovery
fi
[[ ! -L /usr/local/sbin/clab-manager-gateway ]] || exit 1
install -o root -g root -m 0755 "$script_dir/clab-manager-gateway" /usr/local/sbin/clab-manager-gateway
bash "$script_dir/setup-password.sh" "${password_args[@]}"
echo 'Discovery and file import ready. Enter the clab-discovery password in VM connection.'
