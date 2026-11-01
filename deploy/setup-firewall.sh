#!/usr/bin/env bash
# Host firewall for an exposed manager VM (docs/sign-on/EXPOSURE.md 5.2). With ufw it allows every
# port sshd listens on, the manager's TLS port (UI_PORT, default 8443) and its plain-HTTP redirect
# port (UI_HTTP_PORT, default 8081; 0 means none), then denies other incoming traffic and enables ufw.
# Works from any directory.
#
#   sudo bash deploy/setup-firewall.sh            add the rules, deny other incoming, enable ufw
#   sudo bash deploy/setup-firewall.sh --remove   delete the rules this script added
#
# The SSH ports are every port sshd -T names (its Port lines and the port of each ListenAddress) and,
# when ssh.socket is enabled or active, the ports of its ListenStream lines.
#
# It never locks out an SSH session: before any change it refuses when a session (SSH_CONNECTION, or
# under sudo, which drops that variable, the established sshd connections `ss` lists) is connected on
# a port that is not one of those, when a session is connected over IPv6 while /etc/default/ufw does
# not set IPV6=yes (ufw then drops all incoming IPv6), or when an operator's rule denies an SSH port to
# every address. Each rule it adds carries the comment clab-manager. An operator's rule for a port, in
# any form ufw writes (`22`, `22/tcp`, `20:30/tcp`, `to any port 22`, an application profile), keeps
# that port untouched: nothing is added for it, and an operator's allow narrowed to some addresses or
# an interface is never widened. It never resets ufw's rules and never disables it. --remove deletes
# only the clab-manager rules, and keeps the SSH one while ufw is active and denies other incoming
# traffic (deleting it would block new SSH logins).
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
ufw_defaults=/etc/default/ufw
refuse() { printf '%s\n' "$1" >&2; exit 1; }
nothing='Nothing was changed.'
$remove && nothing='Nothing was removed.'

command -v ufw >/dev/null || refuse "ufw is not installed. Install it with: sudo apt-get install -y ufw, then rerun. $nothing"

# A port number as compose reads it: digits only, 1-65535; printed without leading zeros.
port_number() { [[ $1 =~ ^[0-9]{1,5}$ ]] && (( 10#$1 >= 1 && 10#$1 <= 65535 )) && printf '%d' "$((10#$1))"; }
contains() { local item=$1; shift; local each; for each in "$@"; do [[ $each == "$item" ]] && return 0; done; return 1; }

# The ports SSH listens on: the Port lines of sshd -T (the awk of setup-password.sh), the port of each
# of its ListenAddress lines (an explicit host:port there is the port sshd binds, while the Port line
# keeps its default), and the ListenStream ports of ssh.socket when socket activation is in use (an
# upgrade from Ubuntu 22.10 or 23.x can keep an override there).
sshd=$(command -v sshd || printf /usr/sbin/sshd)
effective=$("$sshd" -T 2>/dev/null) || refuse "Could not read the SSH port with sshd -T. $nothing"
socket_ports() {
  command -v systemctl >/dev/null || return 0
  systemctl is-active --quiet ssh.socket || systemctl is-enabled --quiet ssh.socket || return 0
  systemctl show ssh.socket --property=Listen --value | grep -oE '[0-9]+ \(Stream\)' | cut -d' ' -f1 || true
}
ssh_ports=()
while read -r port; do
  port=$(port_number "$port") || continue
  contains "$port" "${ssh_ports[@]}" || ssh_ports+=("$port")
done < <({ awk '$1 == "port" {print $2}' <<< "$effective"
           awk '$1 == "listenaddress" {n = split($2, part, ":"); print part[n]}' <<< "$effective"
           socket_ports; } | sort -n)
(( ${#ssh_ports[@]} )) || refuse "sshd -T names no SSH port. $nothing"
port_sources="sshd -T Port and ListenAddress, ssh.socket ListenStream: ${ssh_ports[*]}"

# An address of IPv6, not IPv4 written as an IPv4-mapped IPv6 address (that traffic is IPv4 on the wire).
is_ipv6() {
  local address=${1#[}; address=${address%]}; address=${address%%\%*}
  [[ $address == *:* ]] || return 1
  [[ ! ${address,,} =~ ^::ffff:[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]
}

# The ports SSH sessions are connected on right now, and the first one connected over IPv6.
session_ports=(); ipv6_session=''
if [[ -n ${SSH_CONNECTION-} ]]; then
  read -r _ _ server_address server_port _ <<< "$SSH_CONNECTION"
  server_port=$(port_number "${server_port-}") || refuse "SSH_CONNECTION names no server port, so this session's SSH port is unknown. $nothing"
  session_ports+=("$server_port")
  if is_ipv6 "$server_address"; then ipv6_session=$server_port; fi
fi
command -v ss >/dev/null || refuse "ss (iproute2) is needed to see the SSH sessions that are connected. $nothing"
# The local port and address of a socket line: the first field that ends in :<digits>.
# shellcheck disable=SC2016 # an awk program, not a shell expansion
local_ends='{ for (i = 1; i <= NF; i++) if ($i ~ /:[0-9]+$/) { n = split($i, part, ":"); print part[n], substr($i, 1, length($i) - length(part[n]) - 1); next } }'
listening=$(ss -Htn state listening | awk "$local_ends" | cut -d' ' -f1) || refuse "ss could not list the listening TCP ports. $nothing"
established=$(ss -Htnp state established | awk '/\("sshd[-a-z]*",pid=/' | awk "$local_ends") || refuse "ss could not list the SSH sessions. $nothing"
# An sshd socket counts as a session only on a listening port: a forwarding socket sshd opened has an
# ephemeral local port.
while read -r port address; do
  [[ -n $port ]] || continue
  grep -qxF -- "$port" <<< "$listening" || continue
  port=$(port_number "$port") || continue
  contains "$port" "${session_ports[@]}" || session_ports+=("$port")
  if [[ -z $ipv6_session ]] && is_ipv6 "$address"; then ipv6_session=$port; fi
done <<< "$established"

# ufw filters IPv6 only with IPV6=yes in /etc/default/ufw (ufw-init accepts yes or YES); otherwise
# enabling it loads an IPv6 table that drops every incoming packet and keeps no established connection.
ipv6_value=''
if [[ -f $ufw_defaults ]]; then
  ipv6_value=$(grep -E '^[[:space:]]*IPV6=' "$ufw_defaults" | tail -n 1 | cut -d= -f2- | tr -d "\"' \r\t" || true)
fi
ipv6_filtered=false
[[ $ipv6_value == yes || $ipv6_value == YES ]] && ipv6_filtered=true
ipv6_setting="$ufw_defaults does not set IPV6"
[[ -z $ipv6_value ]] || ipv6_setting="$ufw_defaults sets IPV6=$ipv6_value"

if ! $remove; then
  for port in "${session_ports[@]}"; do
    contains "$port" "${ssh_ports[@]}" || refuse "An SSH session is connected on port $port, which is not among the ports SSH listens on ($port_sources). $nothing The firewall would block port $port."
  done
  if [[ -n $ipv6_session ]] && ! $ipv6_filtered; then
    refuse "An SSH session is connected over IPv6 (port $ipv6_session), and $ipv6_setting, not IPV6=yes: enabling ufw would drop all incoming IPv6, this session included. Set IPV6=yes there, or connect over IPv4, then rerun. $nothing"
  fi
fi

added=$(ufw show added) || refuse "ufw show added failed. $nothing"
rules=()
while IFS= read -r line; do [[ $line == 'ufw '* ]] && rules+=("$line"); done <<< "$added"

# Whether port $2 is in a ufw port list $1 (22, 21,22 or 20:30, mixed).
in_ports() {
  local item low high
  local -a items
  IFS=, read -ra items <<< "$1"
  for item in "${items[@]}"; do
    low=${item%%:*}; high=${item##*:}
    [[ $low =~ ^[0-9]+$ && $high =~ ^[0-9]+$ ]] || continue
    (( 10#$low <= $2 && $2 <= 10#$high )) && return 0
  done
  return 1
}
# Whether ufw's application profile $1 opens TCP port $2 (ufw app info lists its ports).
app_opens() {
  local info spec
  info=$(ufw app info "$1" 2>/dev/null) || return 1
  while read -r spec; do
    [[ $spec =~ ^([0-9][0-9,:]*)(/([a-z]+))?$ ]] || continue
    [[ -z ${BASH_REMATCH[3]} || ${BASH_REMATCH[3]} == tcp ]] || continue
    in_ports "${BASH_REMATCH[1]}" "$2" && return 0
  done < <(awk '/^Ports?:$/ {take = 1; next} take && NF {gsub(/\|/, "\n"); print $1}' <<< "$info")
  return 1
}
# What one line of `ufw show added` does to new incoming TCP connections on port $2. Prints
# "<action> every" when it applies to every address, "<action> some" when it names the port (or a
# profile that opens it) but only for some sources, an interface or a destination address, and nothing
# when it does not apply: another port, protocol or direction, a route rule, or a narrowed rule that
# names no port (a trusted network, not a rule about this port). The forms are those ufw's
# get_command() writes: `action [in on IF] [log] PORTS[/PROTO]|APP` and the full syntax with
# `from`, `to`, `port`, `app` and `proto`.
rule_effect() {
  local line=$1 port=$2 action rest quoted='' narrow=false dport=any proto=any app='' i=0 count place
  local -a word
  [[ $line =~ ^(.*)\ comment\ \'.*\'$ ]] && line=${BASH_REMATCH[1]}
  [[ $line =~ ^ufw\ (allow|deny|reject|limit)\ (.+)$ ]] || return 0
  action=${BASH_REMATCH[1]}; rest=${BASH_REMATCH[2]}
  if [[ $rest =~ ^(.*)\'([^\']*)\'(.*)$ ]]; then
    quoted=${BASH_REMATCH[2]}; rest="${BASH_REMATCH[1]}@quoted${BASH_REMATCH[3]}"
  fi
  read -ra word <<< "$rest"
  count=${#word[@]}
  if [[ ${word[0]-} == in && ${word[1]-} == on ]]; then narrow=true; i=3; fi
  [[ ${word[i]-} != out ]] || return 0
  if [[ ${word[i]-} == log || ${word[i]-} == log-all ]]; then i=$((i + 1)); fi
  case ${word[i]-} in
    from|to|proto)
      while (( i < count )); do
        case ${word[i]} in
          from|to)
            place=${word[i]}
            [[ ${word[i + 1]-} == any || ${word[i + 1]-} == 0.0.0.0/0 || ${word[i + 1]-} == ::/0 ]] || narrow=true
            i=$((i + 2))
            if [[ ${word[i]-} == port || ${word[i]-} == app ]]; then
              if [[ $place == from ]]; then narrow=true
              elif [[ ${word[i]} == port ]]; then dport=${word[i + 1]-}
              else app=${word[i + 1]-}
              fi
              i=$((i + 2))
            fi;;
          proto) proto=${word[i + 1]-}; i=$((i + 2));;
          *) return 0;;
        esac
      done;;
    '') return 0;;
    *)
      (( i + 1 == count )) || return 0
      if [[ ${word[i]} =~ ^([0-9][0-9,:]*)(/([a-z]+))?$ ]]; then
        dport=${BASH_REMATCH[1]}; proto=${BASH_REMATCH[3]:-any}
      else
        app=${word[i]}
      fi;;
  esac
  [[ $app != @quoted ]] || app=$quoted
  [[ $proto == any || $proto == tcp ]] || return 0
  if [[ -n $app ]]; then
    app_opens "$app" "$port" || return 0
  elif [[ $dport == any ]]; then
    ! $narrow || return 0
  else
    in_ports "$dport" "$port" || return 0
  fi
  if $narrow; then echo "$action some"; else echo "$action every"; fi
}
ours() { [[ $1 == "ufw allow $2/tcp comment '$comment'" ]]; }
# How the rules already treat port $1, in ufw's order (the first rule that matches decides): sets
# decision to ours, kept (an operator's rule for every address), blocked (a deny or reject for every
# address that no narrowed allow comes before), narrowed (the operator's allow for some addresses
# only) or add, and decision_line to the rule it rests on.
decide() {
  local line effect narrowed=''
  decision=add; decision_line=''
  for line in "${rules[@]}"; do
    effect=$(rule_effect "$line" "$1")
    case $effect in
      'allow every'|'limit every')
        if ours "$line" "$1"; then decision=ours; else decision=kept; fi
        decision_line=$line; break;;
      'deny every'|'reject every') decision=blocked; decision_line=$line; break;;
      'allow some'|'limit some') [[ -n $narrowed ]] || narrowed=$line;;
    esac
  done
  if [[ -n $narrowed && ( $decision == add || $decision == blocked ) ]]; then decision=narrowed; decision_line=$narrowed; fi
}

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
      # ufw takes a plain allow or limit of the same port and protocol over in place of this rule (and
      # drops its comment), so the hint names only forms that ufw keeps as rules of their own.
      example="sudo ufw allow from <your network> to any port $port proto tcp"
      [[ $port != 22 ]] || example="$example or sudo ufw allow OpenSSH"
      echo "Kept the SSH allow on $port/tcp (clab-manager): ufw is active and denies other incoming traffic, so deleting it would block new SSH logins."
      echo "To replace it, add an SSH rule that ufw keeps apart from this one, for example $example (a plain allow or limit of $port/tcp would take this rule over instead), check with sudo ufw show added that your rule is listed, then: sudo ufw delete allow $port/tcp"
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

ports=()
for port in "${ssh_ports[@]}" "${tls_ports[@]}" "${redirect_ports[@]}"; do
  contains "$port" "${ports[@]}" || ports+=("$port")
done
decisions=(); lines=()
for port in "${ports[@]}"; do
  decide "$port"
  if [[ $decision == blocked ]] && contains "$port" "${ssh_ports[@]}"; then
    refuse "Your ufw rule '${decision_line#ufw }' blocks the SSH port $port. $nothing"
  fi
  decisions+=("$decision"); lines+=("$decision_line")
done
$ipv6_filtered || echo "Note: $ipv6_setting, so once ufw is enabled it drops all incoming IPv6, SSH and the manager included. Set IPV6=yes there to filter IPv6 with the same rules."

for index in "${!ports[@]}"; do
  port=${ports[index]}; line=${lines[index]}
  case ${decisions[index]} in
    add)
      ufw allow "$port/tcp" comment "$comment" >/dev/null
      echo "Allowed $port/tcp (comment $comment).";;
    ours) echo "Already allowed $port/tcp ($comment).";;
    kept) echo "Kept your own rule for $port/tcp: ${line#ufw }.";;
    narrowed) echo "Kept your own rule for $port/tcp: ${line#ufw }. It limits who reaches port $port, so no rule open to every address was added.";;
    blocked)
      echo "Kept your own rule for $port/tcp: ${line#ufw }."
      echo "The manager is not reachable on port $port while that rule stays.";;
  esac
done
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw --force enable >/dev/null
echo 'ufw is enabled: other incoming traffic is denied, outgoing traffic is allowed.'
ufw status numbered
echo 'Docker-published ports bypass this firewall; the health check lists them.'
