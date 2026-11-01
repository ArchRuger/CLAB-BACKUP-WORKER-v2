#!/usr/bin/env bash
# Host firewall for an exposed manager VM (docs/sign-on/EXPOSURE.md 5.2). With ufw it allows every
# port sshd listens on, the manager's TLS port (UI_PORT, default 8443) and its plain-HTTP redirect
# port (UI_HTTP_PORT, default 8081; 0 means none), then denies other incoming traffic and enables ufw.
# Works from any directory.
#
#   sudo bash deploy/setup-firewall.sh            add the rules, deny other incoming, enable ufw
#   sudo bash deploy/setup-firewall.sh --remove   delete the rules this script added
#
# It never locks out an SSH session: before any change it refuses when a session (SSH_CONNECTION, or
# under sudo, which drops that variable, the established sshd connections `ss` lists) is connected on
# a port sshd -T does not list. Each rule it adds carries the comment clab-manager; a port the operator
# already has a rule for keeps that rule untouched. It never resets ufw's rules and never disables it.
# --remove deletes only the clab-manager rules, and keeps the SSH one while ufw is active and denies
# other incoming traffic (deleting it would block new SSH logins).
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
usage() { echo 'Usage: sudo bash deploy/setup-firewall.sh [--remove]' >&2; exit 64; }
remove=false
[[ $# -le 1 ]] || usage
case "${1-}" in
  '') ;;
  --remove) remove=true;;
  *) usage;;
esac
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(dirname -- "$script_dir")
comment=clab-manager
refuse() { printf '%s\n' "$1" >&2; exit 1; }
nothing='Nothing was changed.'
$remove && nothing='Nothing was removed.'

command -v ufw >/dev/null || refuse "ufw is not installed. Install it with: sudo apt-get install -y ufw, then rerun. $nothing"

# A port number as compose reads it: digits only, 1-65535; printed without leading zeros.
port_number() { [[ $1 =~ ^[0-9]{1,5}$ ]] && (( 10#$1 >= 1 && 10#$1 <= 65535 )) && printf '%d' "$((10#$1))"; }
contains() { local item=$1; shift; local each; for each in "$@"; do [[ $each == "$item" ]] && return 0; done; return 1; }

# The ports sshd listens on (the awk of setup-password.sh), every one of them.
sshd=$(command -v sshd || printf /usr/sbin/sshd)
effective=$("$sshd" -T 2>/dev/null) || refuse "Could not read the SSH port with sshd -T. $nothing"
ssh_ports=()
while read -r port; do
  port=$(port_number "$port") || continue
  contains "$port" "${ssh_ports[@]}" || ssh_ports+=("$port")
done < <(awk '$1 == "port" {print $2}' <<< "$effective" | sort -n)
(( ${#ssh_ports[@]} )) || refuse "sshd -T names no SSH port. $nothing"

# The ports SSH sessions are connected on right now.
session_ports=()
if [[ -n ${SSH_CONNECTION-} ]]; then
  read -r _ _ _ server_port _ <<< "$SSH_CONNECTION"
  server_port=$(port_number "${server_port-}") || refuse "SSH_CONNECTION names no server port, so this session's SSH port is unknown. $nothing"
  session_ports+=("$server_port")
fi
command -v ss >/dev/null || refuse "ss (iproute2) is needed to see the SSH sessions that are connected. $nothing"
# The local port of a socket line: the first field that ends in :<digits>.
# shellcheck disable=SC2016 # an awk program, not a shell expansion
local_ports='{ for (i = 1; i <= NF; i++) if ($i ~ /:[0-9]+$/) { n = split($i, part, ":"); print part[n]; next } }'
listening=$(ss -Htn state listening | awk "$local_ports") || refuse "ss could not list the listening TCP ports. $nothing"
established=$(ss -Htnp state established | awk '/\("sshd[-a-z]*",pid=/' | awk "$local_ports") || refuse "ss could not list the SSH sessions. $nothing"
# An sshd socket counts as a session only on a listening port: a forwarding socket sshd opened has an
# ephemeral local port.
while read -r port; do
  [[ -n $port ]] || continue
  grep -qxF -- "$port" <<< "$listening" || continue
  port=$(port_number "$port") || continue
  contains "$port" "${session_ports[@]}" || session_ports+=("$port")
done <<< "$established"
if ! $remove; then
  for port in "${session_ports[@]}"; do
    contains "$port" "${ssh_ports[@]}" || refuse "An SSH session is connected on port $port, which sshd -T does not list (${ssh_ports[*]}). $nothing The firewall would block port $port."
  done
fi

added=$(ufw show added) || refuse "ufw show added failed. $nothing"
# The operator's or this script's rule for <port>/tcp, incoming, any action: one line or nothing.
rule_for() { grep -E "^ufw (allow|deny|reject|limit)( in)? $1/tcp( comment '.*')?\$" <<< "$added" | head -n 1 || true; }
ours() { [[ $1 == *" comment '$comment'" ]]; }

if $remove; then
  status=$(ufw status verbose) || refuse "ufw status failed. $nothing"
  denying=false
  if grep -qx 'Status: active' <<< "$status" && ! grep -Eq '^Default: allow \(incoming\)' <<< "$status"; then denying=true; fi
  found=false
  while read -r line; do
    [[ $line =~ ^ufw\ allow\ ([0-9]+)/tcp\ comment\ \'clab-manager\'$ ]] || continue
    found=true
    port=${BASH_REMATCH[1]}
    if $denying && { contains "$port" "${ssh_ports[@]}" || contains "$port" "${session_ports[@]}"; }; then
      echo "Kept the SSH allow on $port/tcp (clab-manager): ufw is active and denies other incoming traffic, so deleting it would block new SSH logins. After adding your own SSH rule: sudo ufw delete allow $port/tcp"
      continue
    fi
    ufw delete allow "$port/tcp" >/dev/null
    echo "Deleted the clab-manager allow for $port/tcp."
  done <<< "$added"
  $found || echo 'No clab-manager rules to remove.'
  echo 'ufw is otherwise unchanged; this script never disables it.'
  exit 0
fi

env_value() { local value=''; if [[ -f $1 ]]; then value=$(grep -E "^$2=" "$1" | tail -n 1 | cut -d= -f2- || true); fi; printf '%s' "$value"; }
env_files=("$repo_dir/clab-backup-ui/.env")
image_env="$repo_dir/deploy/image.env"
[[ -n $(env_value "$image_env" MANAGER_IMAGE) ]] && env_files+=("$image_env")
tls_ports=(); redirect_ports=()
for file in "${env_files[@]}"; do
  value=$(env_value "$file" UI_PORT)
  port=$(port_number "${value:-8443}") || refuse "UI_PORT in $file is not a port number (1-65535). $nothing"
  contains "$port" "${tls_ports[@]}" || tls_ports+=("$port")
  value=$(env_value "$file" UI_HTTP_PORT)
  [[ ${value:-8081} == 0 ]] && continue
  port=$(port_number "${value:-8081}") || refuse "UI_HTTP_PORT in $file is not 0 or a port number (1-65535). $nothing"
  contains "$port" "${redirect_ports[@]}" || redirect_ports+=("$port")
done

for port in "${ssh_ports[@]}"; do
  line=$(rule_for "$port")
  if [[ $line =~ ^ufw\ (deny|reject) ]]; then refuse "Your ufw rule '${line#ufw }' blocks the SSH port $port. $nothing"; fi
done

ports=()
for port in "${ssh_ports[@]}" "${tls_ports[@]}" "${redirect_ports[@]}"; do
  contains "$port" "${ports[@]}" || ports+=("$port")
done
for port in "${ports[@]}"; do
  line=$(rule_for "$port")
  if [[ -z $line ]]; then
    ufw allow "$port/tcp" comment "$comment" >/dev/null
    echo "Allowed $port/tcp (comment $comment)."
  elif ours "$line"; then
    echo "Already allowed $port/tcp ($comment)."
  else
    echo "Kept your own rule for $port/tcp: ${line#ufw }."
    if [[ $line =~ ^ufw\ (deny|reject) ]]; then echo "The manager is not reachable on port $port while that rule stays."; fi
  fi
done
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw --force enable >/dev/null
echo 'ufw is enabled: other incoming traffic is denied, outgoing traffic is allowed.'
ufw status numbered
echo 'Docker-published ports bypass this firewall; the health check lists them.'
