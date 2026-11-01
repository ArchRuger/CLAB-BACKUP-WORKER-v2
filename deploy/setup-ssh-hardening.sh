#!/usr/bin/env bash
# A conservative sshd drop-in for an exposed manager VM (docs/sign-on/EXPOSURE.md 5.4). Works from
# any directory.
#
#   sudo bash deploy/setup-ssh-hardening.sh            write /etc/ssh/sshd_config.d/40-clab-manager.conf
#   sudo bash deploy/setup-ssh-hardening.sh --remove   delete it and reload sshd
#
# Ubuntu includes sshd_config.d/*.conf at the top of sshd_config and the first value wins, so the
# drop-in would override the operator's own settings. It therefore carries only the directives whose
# effective value (sshd -T, read without this script's own earlier drop-in) is still OpenSSH's
# default. It never writes PasswordAuthentication (WinSCP, VS Code and the clab-discovery account use
# passwords), AllowTcpForwarding (VS Code Remote-SSH) or AllowUsers, and it never touches the
# clab-discovery policy of setup-password.sh. The candidate is checked with sshd -t -f, the applied
# configuration with sshd -t, then sshd is reloaded; any failure restores the previous drop-in (or its
# absence) and reloads that.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
usage() { echo 'Usage: sudo bash deploy/setup-ssh-hardening.sh [--remove]' >&2; exit 64; }
remove=false
[[ $# -le 1 ]] || usage
case "${1-}" in
  '') ;;
  --remove) remove=true;;
  *) usage;;
esac
refuse() { printf '%s\n' "$1" >&2; exit 1; }
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ssh_dir=/etc/ssh
config="$ssh_dir/sshd_config"
dropin_dir="$ssh_dir/sshd_config.d"
dropin="$dropin_dir/40-clab-manager.conf"
for path in "$config" "$dropin_dir" "$dropin"; do
  [[ ! -L $path ]] || refuse "Refusing symlink at SSH configuration path $path. Nothing was changed."
done
[[ -f $config && -d $dropin_dir ]] || refuse "$config or $dropin_dir is missing. Nothing was changed."
[[ ! -e $dropin || -f $dropin ]] || refuse "$dropin is not a regular file. Nothing was changed."
grep -Eiq '^[[:space:]]*Include[[:space:]].*sshd_config\.d/\*\.conf' "$config" \
  || refuse "$config does not include sshd_config.d/*.conf, so a drop-in there would have no effect. Nothing was changed."
sshd=$(command -v sshd || printf /usr/sbin/sshd)
"$sshd" -t || refuse 'The current SSH configuration does not pass sshd -t; fix it first. Nothing was changed.'
unit=''
if systemctl is-active --quiet ssh; then unit=ssh; elif systemctl is-active --quiet sshd; then unit=sshd; fi
reload() { [[ -z $unit ]] || systemctl reload "$unit"; }

temp_dir=$(mktemp -d)
placing=''; had_dropin=false; changed=false; committed=false
if [[ -e $dropin ]]; then cp -p -- "$dropin" "$temp_dir/previous"; had_dropin=true; fi
cleanup() {
  [[ -z $placing ]] || rm -f -- "$placing"
  if $changed && ! $committed; then
    if $had_dropin; then cp -p -- "$temp_dir/previous" "$dropin"; else rm -f -- "$dropin"; fi
    if "$sshd" -t && reload; then
      echo 'The previous SSH configuration was restored and reloaded.' >&2
    else
      echo 'The previous SSH configuration was restored; check it with sudo sshd -t and reload the SSH service.' >&2
    fi
  fi
  rm -f -- "$temp_dir/previous" "$temp_dir/candidate"
  rmdir -- "$temp_dir"
}
trap cleanup EXIT
reloaded() { if [[ -n $unit ]]; then echo "sshd reloaded ($unit)."; else echo 'The SSH service is not running; the change applies when it starts.'; fi; }

if $remove; then
  $had_dropin || { echo "No clab-manager SSH drop-in to remove ($dropin)."; exit 0; }
  changed=true
  rm -f -- "$dropin"
  "$sshd" -t
  reload
  committed=true
  echo "Removed $dropin."
  reloaded
  exit 0
fi

# Read the effective values without this script's own earlier drop-in, so that its values are not
# mistaken for the operator's and an operator's change since the last run is released.
if $had_dropin; then changed=true; rm -f -- "$dropin"; fi
effective=$("$sshd" -T) || { echo 'Could not read the effective SSH configuration with sshd -T.' >&2; exit 1; }
value_of() { awk -v key="$1" '$1 == key {print $2; exit}' <<< "$effective"; }
written=()
# Directive, the value written, the sshd -T key, then OpenSSH's default as sshd -T prints it.
consider() {
  local directive=$1 value=$2 key=$3 current default; shift 3
  current=$(value_of "$key")
  if [[ -z $current ]]; then
    echo "Not written: $directive (this sshd does not know it)."
    return 0
  fi
  for default in "$@"; do
    if [[ $current == "$default" ]]; then written+=("$directive $value"); return 0; fi
  done
  echo "Kept your own $directive $current."
}
consider PermitRootLogin no permitrootlogin prohibit-password without-password
consider MaxAuthTries 4 maxauthtries 6
consider LoginGraceTime 30 logingracetime 120
consider PerSourceMaxStartups 8 persourcemaxstartups none
consider X11Forwarding no x11forwarding no

if (( ${#written[@]} == 0 )); then
  if $had_dropin; then
    "$sshd" -t
    reload
    committed=true
    echo "Every directive now has a value of your own; removed $dropin."
    reloaded
  else
    echo 'Every directive already has a value of your own; no drop-in was written.'
  fi
  exit 0
fi

{
  echo '# Written by clab-manager deploy/setup-ssh-hardening.sh: only directives that were still at'
  echo "# OpenSSH's default when it ran. Remove with: sudo bash $script_dir/setup-ssh-hardening.sh --remove"
  printf '%s\n' "${written[@]}"
} > "$temp_dir/candidate"
"$sshd" -t -f "$temp_dir/candidate"
changed=true
# A hidden name outside the *.conf glob until the rename puts it in place.
placing=$(mktemp "$dropin_dir/.40-clab-manager.conf.XXXXXX")
cat -- "$temp_dir/candidate" > "$placing"
chmod 0644 -- "$placing"
mv -f -- "$placing" "$dropin"
placing=''
"$sshd" -t
reload
committed=true
echo "Wrote $dropin."
reloaded
after=$("$sshd" -T 2>/dev/null) || after=''
for line in "${written[@]}"; do
  directive=${line%% *}; value=${line#* }
  key=$(tr '[:upper:]' '[:lower:]' <<< "$directive")
  current=$(awk -v key="$key" '$1 == key {print $2; exit}' <<< "$after")
  if [[ $current == "$value" ]]; then
    echo "In effect: $directive $value"
  else
    echo "Not in effect: $directive is ${current:-unknown} (an earlier file in $dropin_dir sets it)."
  fi
done
