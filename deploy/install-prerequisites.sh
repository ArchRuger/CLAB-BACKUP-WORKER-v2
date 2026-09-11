#!/usr/bin/env bash
# Called by the ordinary-user installer after its installation plan is accepted.
# Official references: https://docs.docker.com/engine/install/ubuntu/
# https://containerlab.dev/install/ (manual .deb and sudo-less opt-out)
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
unset DOCKER_CONTEXT DOCKER_HOST DOCKER_TLS_VERIFY DOCKER_CERT_PATH
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
docker_requested=false
clab_requested=false
repair_media=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --docker) docker_requested=true;;
    --containerlab) clab_requested=true;;
    --repair-install-media) repair_media=true;;
    --help|-h)
      echo 'Usage: sudo bash deploy/install-prerequisites.sh [--docker] [--containerlab] [--repair-install-media]'
      echo 'Ubuntu 24.04 amd64/arm64 only. Installs missing basic tools and starts SSH.'
      echo 'Optional Docker/Compose and containerlab are installed only when missing.'
      echo 'Media repair backs up APT files and disables only active installation-media entries.'
      exit 0;;
    *) echo "Unknown prerequisite option: $1" >&2; exit 64;;
  esac
  shift
done
fail() { printf '%s\n' "$*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || fail 'Use the guided installer without sudo; it requests sudo for this prerequisite step.'
[[ -r /etc/os-release ]] || fail 'Cannot identify this OS; install prerequisites manually using FRESH-VM-GUIDE.md.'
# shellcheck disable=SC1091
. /etc/os-release
[[ ${ID:-} == ubuntu && ${VERSION_ID:-} == 24.04 ]] || fail 'Automatic prerequisite installation supports Ubuntu Server 24.04 only. Follow FRESH-VM-GUIDE.md for manual setup.'
architecture=$(dpkg --print-architecture)
[[ $architecture == amd64 || $architecture == arm64 ]] || fail 'Automatic installation supports amd64 and arm64 only.'
[[ -x /usr/bin/python3 && -d /run/systemd/system ]] || fail 'This installer requires Ubuntu Server with Python 3 and systemd running.'

installed() { [[ $(dpkg-query -W -f='${db:Status-Status}' "$1" 2>/dev/null || true) == installed ]]; }
trusted_binary() {
  local found mode
  found=$(command -v "$1" || true)
  [[ -n $found ]] || return 1
  found=$(readlink -f -- "$found")
  [[ $found =~ ^/usr/(local/)?bin/[A-Za-z0-9._-]+$ && $(stat -c %u "$found") == 0 ]] || fail "Use a root-owned $1 executable in /usr/bin or /usr/local/bin before continuing."
  mode=$(stat -c %a "$found")
  (( (8#$mode & 8#022) == 0 )) || fail "$1 must not be writable by group or other users."
}
docker_missing=false
compose_missing=false
clab_missing=false
if $docker_requested; then
  if trusted_binary docker; then
    docker --version >/dev/null || fail 'Existing Docker CLI failed. Repair this installation before rerunning setup.'
    docker compose version >/dev/null 2>&1 || compose_missing=true
  else
    docker_missing=true
    compose_missing=true
  fi
  if $docker_missing || $compose_missing; then
    conflicts=()
    for package in docker.io docker-compose docker-compose-v2 docker-doc docker-buildx podman-docker containerd runc; do
      if installed "$package"; then conflicts+=("$package"); fi
    done
    [[ ${#conflicts[@]} -eq 0 ]] || fail "Existing packages conflict with Docker's official packages: ${conflicts[*]}. Review https://docs.docker.com/engine/install/ubuntu/ before rerunning; setup does not remove them."
    if ! $docker_missing && ! installed docker-ce; then
      fail 'Docker is installed outside the official docker-ce package, but Compose is missing. Add compatible Compose to that installation, then rerun setup.'
    fi
  fi
fi
if $clab_requested; then
  if trusted_binary containerlab; then
    containerlab version >/dev/null || fail 'Existing containerlab failed its version check. Repair it before rerunning setup.'
  else
    installed containerlab && fail 'The containerlab package exists but its executable is missing. Repair that package before rerunning setup.'
    clab_missing=true
  fi
fi

temporary=$(mktemp -d /tmp/clab-manager-prerequisites.XXXXXX)
clab_needs_hardening=false
cleanup() {
  local result=$?
  # Also handle package postinstall failure or interrupted installation.
  if $clab_needs_hardening && [[ -f /usr/bin/containerlab && ! -L /usr/bin/containerlab && $(stat -c %u /usr/bin/containerlab) == 0 ]]; then
    chmod 0755 /usr/bin/containerlab || {
      echo 'Remove the SUID bit with sudo chmod 0755 /usr/bin/containerlab before using it.' >&2
      result=1
    }
  fi
  rm -f -- "$temporary/docker.asc" "$temporary/docker.sources" "$temporary/clab.deb" "$temporary/checksums.txt"
  rmdir -- "$temporary"
  return "$result"
}
trap cleanup EXIT
if $repair_media; then
  /usr/bin/python3 "$script_dir/apt_sources.py" --repair
fi

apt_updated=false
apt_update() {
  if ! $apt_updated; then
    /usr/bin/python3 "$script_dir/apt_update.py" || fail 'APT update did not pass. Follow the specific recovery above, then retry this step.'
    apt_updated=true
  fi
}
apt_install() {
  [[ $# -gt 0 ]] || return 0
  apt_update
  DEBIAN_FRONTEND=noninteractive apt-get -y --no-remove --no-upgrade \
    -o Dpkg::Options::=--force-confold install "$@" || fail 'Package installation failed. Resolve the APT error above, then rerun the installer. Existing configuration files are retained.'
}
basics=()
for package in git curl ca-certificates openssh-server; do
  installed "$package" || basics+=("$package")
done
apt_install "${basics[@]}"
if $repair_media; then apt_update; fi
systemctl enable --now ssh || fail 'SSH could not start. Check sudo systemctl status ssh and the SSH configuration before continuing.'

if $docker_missing || $compose_missing; then
  source_file=/etc/apt/sources.list.d/clab-manager-docker.sources
  key_file=/etc/apt/keyrings/clab-manager-docker.asc
  for path in /etc/apt /etc/apt/sources.list.d /etc/apt/keyrings "$source_file" "$key_file"; do
    [[ ! -L $path ]] || fail "Refusing a symlink at $path; review the existing APT configuration."
  done
  # Reuse the operator's Docker repository without adding a duplicate. Its
  # keyring, suite and package pins remain under the operator's control.
  docker_source_state=$(/usr/bin/python3 "$script_dir/apt_sources.py" --docker-source-status)
  if [[ $docker_source_state == enabled ]]; then
    echo 'Reusing the existing enabled Docker APT source.'
  else
  cat > "$temporary/docker.sources" <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: $architecture
Signed-By: $key_file
EOF
  if [[ -e $source_file ]]; then
    cmp -s "$temporary/docker.sources" "$source_file" || fail "Existing $source_file differs from this install plan; review it manually."
  fi
  install -d -o root -g root -m 0755 /etc/apt/keyrings
  if [[ ! -e $key_file ]]; then
    curl --proto '=https' --proto-redir '=https' --connect-timeout 20 --max-time 120 -fsSL \
      https://download.docker.com/linux/ubuntu/gpg -o "$temporary/docker.asc" || fail 'Could not download the official Docker signing key. Check HTTPS connectivity and rerun.'
    grep -q '^-----BEGIN PGP PUBLIC KEY BLOCK-----' "$temporary/docker.asc" || fail 'Docker signing key download is invalid.'
    install -o root -g root -m 0644 "$temporary/docker.asc" "$key_file"
  fi
  if [[ ! -e $source_file ]]; then
    install -o root -g root -m 0644 "$temporary/docker.sources" "$source_file"
  fi
  fi
  apt_updated=false
  docker_packages=()
  if $docker_missing; then
    for package in docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin; do
      installed "$package" || docker_packages+=("$package")
    done
  elif $compose_missing; then
    installed docker-compose-plugin && fail 'Docker Compose plugin is installed but cannot run. Repair the existing package before continuing.'
    docker_packages+=(docker-compose-plugin)
  fi
  apt_install "${docker_packages[@]}"
fi
if $docker_requested; then
  systemctl enable --now docker || fail 'Docker could not start. Check sudo systemctl status docker before continuing.'
  docker --host unix:///var/run/docker.sock info >/dev/null || fail 'The rootful Docker daemon is unavailable at /var/run/docker.sock. Repair the Docker service before continuing.'
  docker compose version || fail 'Docker Compose is still unavailable; check the plugin installation.'
fi

if $clab_missing; then
  # The official containerlab APT example uses trusted=yes. Download the official
  # release package and compare its published SHA256 instead of bypassing APT
  # authentication. No downloaded script is executed.
  release_url=$(curl --proto '=https' --proto-redir '=https' --connect-timeout 20 --max-time 120 \
    -fsSL -o /dev/null -w '%{url_effective}' https://github.com/srl-labs/containerlab/releases/latest) || fail 'Could not resolve the latest official containerlab release. Check HTTPS connectivity and rerun.'
  [[ $release_url =~ ^https://github\.com/srl-labs/containerlab/releases/tag/v([0-9]+\.[0-9]+\.[0-9]+)$ ]] || fail 'Containerlab returned an unexpected release URL; install an official stable package manually.'
  version=${BASH_REMATCH[1]}
  filename="containerlab_${version}_linux_${architecture}.deb"
  base_url="https://github.com/srl-labs/containerlab/releases/download/v${version}"
  curl --proto '=https' --proto-redir '=https' --connect-timeout 20 --max-time 600 -fsSL \
    "$base_url/$filename" -o "$temporary/clab.deb" || fail 'Containerlab package download failed; rerun setup after checking connectivity.'
  curl --proto '=https' --proto-redir '=https' --connect-timeout 20 --max-time 120 -fsSL \
    "$base_url/checksums.txt" -o "$temporary/checksums.txt" || fail 'Containerlab checksums download failed; the package has not been installed.'
  /usr/bin/python3 -I - "$temporary/clab.deb" "$temporary/checksums.txt" "$filename" <<'PY'
import hashlib, pathlib, re, sys
package, checksums, name = sys.argv[1:]
matches = []
for line in pathlib.Path(checksums).read_text(encoding='utf-8').splitlines():
    match = re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?(.+)', line)
    if match and match[2] == name:
        matches.append(match[1].lower())
with open(package, 'rb') as stream:
    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
if len(matches) != 1 or digest != matches[0]:
    sys.exit('Containerlab checksum verification failed; no package was installed. Rerun after checking the official release.')
print('Official containerlab package SHA256 verified.')
PY
  [[ $(dpkg-deb -f "$temporary/clab.deb" Package) == containerlab && $(dpkg-deb -f "$temporary/clab.deb" Architecture) == "$architecture" ]] || fail 'Containerlab package identity does not match the requested platform.'
  for path in /etc/containerlab /etc/containerlab/suid_setup_done /usr/bin/containerlab; do
    [[ ! -L $path ]] || fail "Refusing a symlink at $path; review the existing containerlab installation."
  done
  [[ ! -e /usr/bin/containerlab ]] || fail 'A containerlab file already exists at /usr/bin/containerlab; review it before installation.'
  install -d -o root -g root -m 0755 /etc/containerlab
  if [[ ! -e /etc/containerlab/suid_setup_done ]]; then
    install -o root -g root -m 0644 /dev/null /etc/containerlab/suid_setup_done
  fi
  # Prevent upstream postinstall from granting an operator new group authority.
  # Its SUID bit is removed below on this fresh installation only.
  clab_needs_hardening=true
  # Allow APT's unprivileged downloader to read the already verified local .deb.
  chmod 0755 "$temporary"
  chmod 0644 "$temporary/clab.deb"
  apt_install "$temporary/clab.deb"
  chmod 0755 /usr/bin/containerlab
  containerlab version
fi
echo 'Selected prerequisites are ready. Existing labs and manager data were retained.'
