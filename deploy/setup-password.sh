#!/usr/bin/env bash
# Called by setup-discovery after the restricted helpers have been installed.
set -euo pipefail
# Never trace this script: the password lives in a shell variable for a moment.
{ set +x; } 2>/dev/null
[[ $EUID -eq 0 ]] || exit 64
reset=false; data_dir=/srv/containerlab-node-manager/data
while [[ $# -gt 0 ]]; do
  case "$1" in
    --reset-password) $reset && exit 64; reset=true; shift;;
    --data-dir) [[ $# -ge 2 && $2 == /* ]] || exit 64; data_dir=$2; shift 2;;
    *) exit 64;;
  esac
done
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
if [[ "$password_state" != P ]] || $reset; then
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
# Never expose the password through argv, environment or shell tracing. It is read
# twice without echo, handed to chpasswd and the seed writer on stdin only (printf is
# a shell builtin), and only its hash is stored in the VM's /etc/shadow.
password=''; confirm=''; seeded=false
if [[ "$password_state" != P ]] || $reset; then
  echo 'Create the clab-discovery password. Setup hands it to the manager once, so VM connection opens prefilled.'
  attempts=0
  while :; do
    IFS= read -rs -p 'New password: ' password; echo
    IFS= read -rs -p 'Retype new password: ' confirm; echo
    if [[ -n $password && $password == "$confirm" ]]; then break; fi
    attempts=$((attempts + 1))
    if [[ -z $password ]]; then echo 'The password must not be empty.' >&2; else echo 'The passwords do not match.' >&2; fi
    (( attempts < 3 )) || { password=''; confirm=''; echo 'No password set.' >&2; exit 1; }
  done
  confirm=''
  printf '%s:%s\n' "$account" "$password" | chpasswd
  seeded=true
fi
committed=true
[[ $(passwd -S "$account" | awk '{print $2}') == P ]] || { password=''; echo 'A usable account password is required.' >&2; exit 1; }
if $seeded; then
  # One-time seed for the manager: its VM connection dialog opens prefilled and it
  # connects only after the student confirms (the seed never pins a host key).
  effective=$("$sshd" -T -C "user=$account,host=localhost,addr=127.0.0.1" 2>/dev/null) || effective=''
  port=$(awk '$1 == "port" {print $2; exit}' <<< "$effective")
  [[ $port =~ ^[0-9]+$ ]] || port=22
  key_args=()
  while read -r key; do
    [[ -n $key ]] && key_args+=(--host-key "$key.pub")
  done < <(awk '$1 == "hostkey" {print $2}' <<< "$effective")
  seed_status=0
  printf '%s\n' "$password" | /usr/bin/python3 -I "$script_dir/host_bootstrap_seed.py" --data-dir "$data_dir" --port "$port" "${key_args[@]}" || seed_status=$?
  password=''
  case $seed_status in
    0) echo 'VM connection prefilled for the manager: open VM connection and choose Save and test connection once.';;
    2) ;;
    *) echo 'The VM connection could not be prefilled; enter the clab-discovery password in VM connection.' >&2;;
  esac
fi
password=''
home_dir=$(getent passwd "$account" | cut -d: -f6)
[[ "$home_dir" == /home/clab-discovery && ! -L "$home_dir/.ssh" && ! -L "$home_dir/.ssh/authorized_keys" ]] || exit 1
# Revoke the dedicated account's previous client keys; host identity keys remain.
if [[ -f "$home_dir/.ssh/authorized_keys" ]]; then
  install -o root -g root -m 0644 /dev/null "$home_dir/.ssh/authorized_keys"
fi
echo 'VM password authentication ready. Saved passwords are retained on subsequent launches.'
