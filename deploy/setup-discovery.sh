#!/usr/bin/env bash
# Run on the Linux VM: sudo bash deploy/setup-discovery.sh /path/to/discovery-key.pub
set -euo pipefail
[[ $EUID -eq 0 && $# -eq 1 ]] || { echo 'Usage: sudo bash deploy/setup-discovery.sh /path/to/key.pub' >&2; exit 1; }
public_key=$(cat -- "$1")
[[ "$public_key" != *$'\n'* && "$public_key" =~ ^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521))[[:space:]][A-Za-z0-9+/=]+([[:space:]].*)?$ ]] || { echo 'Supply one OpenSSH public key, without authorized_keys options.' >&2; exit 1; }
command -v visudo >/dev/null || { echo 'Install sudo first.' >&2; exit 1; }
command -v sshd >/dev/null || [[ -x /usr/sbin/sshd ]] || { echo 'Install and enable the SSH server first.' >&2; exit 1; }
clab_bin=$(readlink -f "$(command -v containerlab)")
[[ "$clab_bin" =~ ^/usr/(local/)?bin/[A-Za-z0-9._-]+$ ]] || { echo 'Install containerlab in /usr/bin or /usr/local/bin.' >&2; exit 1; }
[[ $(stat -c %u "$clab_bin") == 0 ]] || { echo 'The containerlab binary must be owned by root.' >&2; exit 1; }
mode=$(stat -c %a "$clab_bin")
(( (8#$mode & 8#022) == 0 )) || { echo 'The containerlab binary must not be writable by group/others.' >&2; exit 1; }
account=clab-discovery
if ! id "$account" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/sh "$account"
  usermod --password '*' "$account"
fi
home_dir=$(getent passwd "$account" | cut -d: -f6)
[[ "$home_dir" == /home/clab-discovery ]] || { echo 'Expected /home/clab-discovery for the discovery account.' >&2; exit 1; }
[[ ! -L "$home_dir/.ssh" && ! -L "$home_dir/.ssh/authorized_keys" ]] || { echo 'Refusing a symlink in the dedicated SSH key path.' >&2; exit 1; }
tmp=$(mktemp -d)
trap 'rm -f -- "$tmp/helper" "$tmp/sudoers" "$tmp/authorized_keys"; rmdir -- "$tmp"' EXIT
cat > "$tmp/helper" <<EOF
#!/bin/sh
set -eu
[ "\$#" -eq 0 ] || exit 64
cd /
exec /usr/bin/env -i PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin HOME=/root "$clab_bin" inspect --all --format json
EOF
install -o root -g root -m 0755 "$tmp/helper" /usr/local/sbin/clab-manager-inspect
printf '%s\n' 'clab-discovery ALL=(root) NOPASSWD: /usr/local/sbin/clab-manager-inspect ""' > "$tmp/sudoers"
visudo -cf "$tmp/sudoers"
install -o root -g root -m 0440 "$tmp/sudoers" /etc/sudoers.d/clab-manager-discovery
install -d -o root -g root -m 0755 "$home_dir/.ssh"
# The dedicated account is intentionally restricted to one supplied key/command.
printf 'restrict,command="sudo -n /usr/local/sbin/clab-manager-inspect" %s\n' "$public_key" > "$tmp/authorized_keys"
install -o root -g root -m 0644 "$tmp/authorized_keys" "$home_dir/.ssh/authorized_keys"
echo 'Discovery account ready: clab-discovery. Select the installed helper in VM connection.'
echo 'Upload the matching PRIVATE key in the manager UI; the VM setup uses only its PUBLIC key.'
echo 'Rerunning this script replaces this dedicated account’s authorized key.'
