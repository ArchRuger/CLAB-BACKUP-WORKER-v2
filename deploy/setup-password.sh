#!/usr/bin/env bash
# Called by setup-discovery after the restricted helpers have been installed.
set -euo pipefail
[[ $EUID -eq 0 && $# -le 1 ]] || exit 64
[[ $# -eq 0 || $1 == --reset-password ]] || exit 64
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
account=clab-discovery
config=/etc/ssh/sshd_config
policy=/etc/ssh/clab-manager-password.conf
[[ ! -L "$config" && ! -L "$policy" ]] || { echo 'Refusing symlink at SSH configuration path.' >&2; exit 1; }
sshd=$(command -v sshd || printf /usr/sbin/sshd)
"$sshd" -t
unit=ssh
systemctl is-active --quiet ssh || unit=sshd
systemctl is-active --quiet "$unit" || { echo 'Start the SSH service first.' >&2; exit 1; }
password_state=$(passwd -S "$account" | awk '{print $2}')
if [[ "$password_state" != P || $# -ne 0 ]]; then
  [[ -t 0 && -t 1 ]] || { echo 'Run setup in an interactive VM terminal to create the clab-discovery password.' >&2; exit 1; }
fi
temp_dir=$(mktemp -d)
changed=false; committed=false; had_policy=false
cp -p -- "$config" "$temp_dir/original"
if [[ -e "$policy" ]]; then cp -p -- "$policy" "$temp_dir/policy"; had_policy=true; fi
cleanup() {
  if $changed && ! $committed; then
    cp -p -- "$temp_dir/original" "$config"
    if $had_policy; then cp -p -- "$temp_dir/policy" "$policy"; else rm -f -- "$policy"; fi
    "$sshd" -t && systemctl reload "$unit" || echo 'Check SSH configuration and reload the service.' >&2
  fi
  rm -f -- "$temp_dir/original" "$temp_dir/policy" "$temp_dir/candidate" "$temp_dir/effective"
  rmdir -- "$temp_dir"
}
trap cleanup EXIT
cp -p -- "$config" "$temp_dir/candidate"
# Append a dedicated include, leaving global and administrator settings intact.
# Match all prevents an earlier Match clause from making the Include conditional.
if ! grep -qxF "Include $policy" "$temp_dir/candidate"; then
  printf '\nMatch all\nInclude %s\n' "$policy" >> "$temp_dir/candidate"
fi
changed=true
install -o root -g root -m 0644 "$script_dir/clab-manager-password.conf" "$policy"
"$sshd" -t -f "$temp_dir/candidate"
for address in 127.0.0.1 192.0.2.1; do
  "$sshd" -T -f "$temp_dir/candidate" -C "user=$account,host=localhost,addr=$address" > "$temp_dir/effective"
  /usr/bin/python3 "$script_dir/verify-ssh-password.py" < "$temp_dir/effective"
done
install -o root -g root -m 0600 "$temp_dir/candidate" "$config"
"$sshd" -t
systemctl reload "$unit"
# Never expose the password through argv, environment, files, or shell tracing.
# passwd prompts twice without echo and stores the hash in the VM's /etc/shadow.
if [[ "$password_state" != P || $# -ne 0 ]]; then
  echo 'Create the clab-discovery password. Enter this same password in VM connection after launch.'
  passwd "$account"
fi
committed=true
[[ $(passwd -S "$account" | awk '{print $2}') == P ]] || { echo 'A usable account password is required.' >&2; exit 1; }
home_dir=$(getent passwd "$account" | cut -d: -f6)
[[ "$home_dir" == /home/clab-discovery && ! -L "$home_dir/.ssh" && ! -L "$home_dir/.ssh/authorized_keys" ]] || exit 1
# Revoke the dedicated account's previous client keys; host identity keys remain.
if [[ -f "$home_dir/.ssh/authorized_keys" ]]; then
  install -o root -g root -m 0644 /dev/null "$home_dir/.ssh/authorized_keys"
fi
echo 'VM password authentication ready. Saved passwords are retained on subsequent launches.'
