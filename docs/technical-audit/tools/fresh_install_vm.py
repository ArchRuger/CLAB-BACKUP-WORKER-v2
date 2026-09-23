#!/usr/bin/env python3
"""Fresh-install evidence driver for the technical audit (release 1.30.42+).

Boots a scratch QEMU/KVM virtual machine from an unmodified Ubuntu 24.04 cloud
image, stages a `git archive` source tarball into it, drives the guided
installer (`deploy/install.sh`) through an interactive pseudo-terminal
session over SSH, then runs read-only proofs
(`deploy/check-install.sh`, `/api/state`, `docker`, `ss`) entirely inside the
nested VM. Nothing here touches the host's own manager, `/srv` or `/etc`;
every privileged command is `sudo`'d inside the guest, where the seeded
`student` account has passwordless sudo.

Run with the project virtualenv's Python (it carries paramiko):
  clab-backup-ui/.venv/bin/python docs/technical-audit/tools/fresh_install_vm.py <subcommand> ...

Subcommands are independent and resumable against the same --scratch
directory, so a run can be inspected or retried stage by stage:
  keygen            generate an SSH key pair in the scratch directory
  seed              write cloud-init user-data/meta-data and build seed.iso
  disk              create the copy-on-write disk backed by the base image
  boot              start qemu-system-x86_64 (daemonized, serial to a log file)
  wait-ssh          poll until the guest accepts an SSH connection
  cloud-init-wait   run `cloud-init status --wait` inside the guest
  facts             collect and print the pre-install environment facts (JSON)
  stage             scp the source archive in, extract it, run verify-release.py
  installer         drive deploy/install.sh interactively; stop at the Git wizard
  health            run deploy/check-install.sh and save the raw report
  state             curl /api/state and save it
  inventory         docker ps/volumes/images, ss, grep/ls absence proofs
  again             rerun start-manager.sh (idempotent upgrade path) + health
  reboot            sudo reboot; wait for SSH; re-check manager/capture/state
  vmconn            call the VM-connection API the "Save and test connection"
                    button uses, without ever writing the password anywhere
  shutdown          sudo poweroff; wait for the QEMU process to exit
  all               run every stage above in order

Every stage writes its raw output under --scratch (never under the
evidence directory); the caller trims/curates evidence separately.
"""
import argparse
import json
import os
import secrets
import shlex
import socket
import string
import subprocess
import sys
import time
from pathlib import Path

try:
    import paramiko
except ImportError:
    paramiko = None

DEFAULT_SSH_PORT = 2222
DEFAULT_VCPUS = 6
DEFAULT_MEM_MB = 8192
DEFAULT_DISK_SIZE = '30G'
GUEST_USER = 'student'
REPO_SOURCE_ON_GUEST = '$HOME/projects/clab-manager'


def sh(args, **kwargs):
    print('+ ' + shlex.join(str(a) for a in args), file=sys.stderr)
    return subprocess.run(args, check=True, **kwargs)


def via_kvm_group(command_line):
    """Run a shell command line with the kvm group active, without sudo."""
    return sh(['sg', 'kvm', '-c', command_line])


# ---------------------------------------------------------------- keygen ----
def cmd_keygen(args):
    scratch = Path(args.scratch)
    key = scratch / 'id_ed25519'
    if key.exists():
        print(f'Key pair already present: {key}')
        return
    sh(['ssh-keygen', '-t', 'ed25519', '-N', '', '-f', str(key), '-C', 'fresh-install-audit'])
    print(f'Generated {key} / {key}.pub')


# -------------------------------------------------------------------- seed --
CLOUD_CONFIG_TEMPLATE = """#cloud-config
hostname: fresh-clab
manage_etc_hosts: true
users:
  - name: {user}
    groups: [sudo]
    shell: /bin/bash
    sudo: ['ALL=(ALL) NOPASSWD:ALL']
    lock_passwd: false
    ssh_authorized_keys:
      - {pubkey}
chpasswd:
  list: |
    {user}:{console_password}
  expire: false
ssh_pwauth: true
package_update: true
"""

META_DATA_TEMPLATE = """instance-id: fresh-clab
local-hostname: fresh-clab
"""


def cmd_seed(args):
    scratch = Path(args.scratch)
    pubkey = (scratch / 'id_ed25519.pub').read_text().strip()
    console_password = secrets.token_urlsafe(18)
    (scratch / 'console-password.txt').write_text(console_password + '\n')
    os.chmod(scratch / 'console-password.txt', 0o600)
    user_data = CLOUD_CONFIG_TEMPLATE.format(user=GUEST_USER, pubkey=pubkey, console_password=console_password)
    (scratch / 'user-data').write_text(user_data)
    (scratch / 'meta-data').write_text(META_DATA_TEMPLATE)
    seed = scratch / 'seed.iso'
    if seed.exists():
        seed.unlink()
    sh(['cloud-localds', str(seed), str(scratch / 'user-data'), str(scratch / 'meta-data')])
    print(f'Wrote {seed} (console recovery password kept only in {scratch}/console-password.txt, out of evidence).')


# -------------------------------------------------------------------- disk --
def cmd_disk(args):
    scratch = Path(args.scratch)
    disk = scratch / 'disk.qcow2'
    base = Path(args.image)
    if disk.exists():
        print(f'{disk} already exists; not recreated (remove it first to redo).')
        return
    sh(['qemu-img', 'create', '-f', 'qcow2', '-F', 'qcow2', '-b', str(base), str(disk), args.size])
    print(f'Created {disk} ({args.size}, backed by {base}).')


# -------------------------------------------------------------------- boot --
def cmd_boot(args):
    scratch = Path(args.scratch)
    disk = scratch / 'disk.qcow2'
    seed = scratch / 'seed.iso'
    console_log = scratch / 'console.log'
    pidfile = scratch / 'qemu.pid'
    if pidfile.exists():
        pid = pidfile.read_text().strip()
        if pid and Path(f'/proc/{pid}').exists():
            print(f'QEMU already running as pid {pid}.')
            return
        pidfile.unlink()
    if console_log.exists():
        console_log.unlink()
    command = (
        'qemu-system-x86_64 -enable-kvm -cpu host -smp {vcpus} -m {mem} '
        '-drive file={disk},if=virtio,format=qcow2 '
        '-drive file={seed},if=virtio,format=raw '
        '-nic user,model=virtio,hostfwd=tcp:127.0.0.1:{port}-:22 '
        '-display none -daemonize -serial file:{console} -pidfile {pidfile}'
    ).format(vcpus=args.vcpus, mem=args.mem, disk=shlex.quote(str(disk)), seed=shlex.quote(str(seed)),
              port=args.ssh_port, console=shlex.quote(str(console_log)), pidfile=shlex.quote(str(pidfile)))
    via_kvm_group(command)
    time.sleep(2)
    pid = pidfile.read_text().strip() if pidfile.exists() else '?'
    print(f'QEMU daemonized, pid {pid}; SSH forwarded to 127.0.0.1:{args.ssh_port}; console log {console_log}.')


# ---------------------------------------------------------------- wait-ssh --
def cmd_wait_ssh(args):
    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(('127.0.0.1', args.ssh_port), timeout=3) as sock:
                banner = sock.recv(64)
                if banner.startswith(b'SSH-'):
                    print(f'SSH is up on 127.0.0.1:{args.ssh_port}: {banner!r}')
                    return
        except OSError:
            pass
        time.sleep(3)
    raise SystemExit(f'Timed out waiting for SSH on 127.0.0.1:{args.ssh_port} after {args.timeout}s.')


# ------------------------------------------------------------- ssh helpers --
def connect(args):
    if paramiko is None:
        raise SystemExit('paramiko is not importable; run with clab-backup-ui/.venv/bin/python.')
    scratch = Path(args.scratch)
    key = paramiko.Ed25519Key.from_private_key_file(str(scratch / 'id_ed25519'))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect('127.0.0.1', port=args.ssh_port, username=GUEST_USER, pkey=key, timeout=15,
                    allow_agent=False, look_for_keys=False)
    return client


def run_ssh(client, command, timeout=600):
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode('utf-8', 'replace')
    err = stderr.read().decode('utf-8', 'replace')
    code = stdout.channel.recv_exit_status()
    return code, out, err


# --------------------------------------------------------- cloud-init-wait --
def cmd_cloud_init_wait(args):
    client = connect(args)
    try:
        code, out, err = run_ssh(client, 'cloud-init status --wait', timeout=args.timeout)
        print(out, end='')
        print(err, end='', file=sys.stderr)
        if code != 0:
            raise SystemExit(f'cloud-init status --wait exited {code}.')
    finally:
        client.close()


# ------------------------------------------------------------------ facts --
FACT_COMMANDS = {
    'lsb_release': 'lsb_release -a',
    'uname': 'uname -r',
    'nproc': 'nproc',
    'free': 'free -g',
    'df': 'df -h /',
    'docker_absent': 'command -v docker || echo ABSENT',
    'containerlab_absent': 'command -v containerlab || echo ABSENT',
    'manager_dir_absent': 'ls /srv/containerlab-node-manager 2>&1 || true',
    'etc_clab_manager_absent': 'ls /etc/clab-manager 2>&1 || true',
}


def cmd_facts(args):
    client = connect(args)
    try:
        facts = {}
        for name, command in FACT_COMMANDS.items():
            code, out, err = run_ssh(client, command)
            facts[name] = {'code': code, 'stdout': out.strip(), 'stderr': err.strip()}
    finally:
        client.close()
    scratch = Path(args.scratch)
    (scratch / 'facts.json').write_text(json.dumps(facts, indent=2))
    print(json.dumps(facts, indent=2))


# ------------------------------------------------------------------ stage --
def cmd_stage(args):
    client = connect(args)
    try:
        sftp = client.open_sftp()
        archive = Path(args.archive)
        remote_archive = f'/home/{GUEST_USER}/{archive.name}'
        print(f'Uploading {archive} -> {remote_archive} ...')
        sftp.put(str(archive), remote_archive)
        sftp.close()
        commands = [
            f'mkdir -p $HOME/projects',
            f'tar -xzf {shlex.quote(remote_archive)} -C $HOME/projects',
            # git archive of a commit produces a tree without a name; the caller must
            # have written it so extraction lands directly at projects/clab-manager.
            f'ls $HOME/projects',
        ]
        for command in commands:
            code, out, err = run_ssh(client, command)
            print(f'$ {command}\n{out}{err}')
            if code != 0 and 'ls $HOME/projects' not in command:
                raise SystemExit(f'Stage command failed ({code}): {command}')
        code, out, err = run_ssh(client, f'python3 {REPO_SOURCE_ON_GUEST}/deploy/verify-release.py')
        print(out, err)
        if code != 0:
            raise SystemExit(f'verify-release.py failed (exit {code}) inside the guest.')
    finally:
        client.close()


# --------------------------------------------------------------- installer --
def _pump(shell, buffer, stop_markers, timeout, log, auto_responses=None):
    """Read from an invoke_shell channel until one of `stop_markers` appears, or
    `timeout` elapses, meanwhile auto-answering any prompt in `auto_responses`
    (marker -> text to send, including its own newline) the moment a new
    occurrence of that marker appears. Returns (buffer, matched_marker_or_None)."""
    auto_responses = auto_responses or {}
    seen_counts = {marker: buffer.count(marker) for marker in auto_responses}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if shell.recv_ready():
            chunk = shell.recv(65536).decode('utf-8', 'replace')
            buffer += chunk
            log.write(chunk)
            log.flush()
            for marker in stop_markers:
                if marker in buffer:
                    return buffer, marker
            for marker, response in auto_responses.items():
                count = buffer.count(marker)
                if count > seen_counts[marker]:
                    seen_counts[marker] = count
                    shell.send(response)
        else:
            time.sleep(0.3)
    return buffer, None


def cmd_installer(args):
    client = connect(args)
    scratch = Path(args.scratch)
    log_path = scratch / 'installer.log'
    manager_password = secrets.token_urlsafe(20)
    console_password_path = scratch / 'console-password.txt'
    console_password = console_password_path.read_text().strip() if console_password_path.exists() else None
    if console_password is None:
        raise SystemExit('No console-password.txt in scratch; run the seed subcommand first.')
    # `sudo -v` (bare validate, no command) is called twice by the installer (phase 1
    # "Administrator access and settings" and again inside phase 5's verify_manager if the
    # cached credential expired during the long build/pull phases). On a normal Ubuntu
    # account in the `sudo` group, sudo's validate-only check requires a password even
    # though the seeded cloud-init NOPASSWD entry lets every *specific* command run
    # password-free (that is last-match-wins for a given command, which is why phases 2-6's
    # `sudo bash ...` invocations need nothing). This matches the quick-install guide's own
    # "[sudo] password for <account>:" row; we answer it with the seeded account login
    # password (never the manager/VM password created below) every time it recurs.
    auto = {'password for ' + GUEST_USER + ':': console_password + '\n'}
    try:
        shell = client.invoke_shell(term='xterm', width=220, height=50)
        shell.settimeout(0.0)
        with open(log_path, 'a') as log:
            buf = ''
            # Drain the login banner/prompt, then start the installer.
            time.sleep(1)
            if shell.recv_ready():
                buf += shell.recv(65536).decode('utf-8', 'replace')
                log.write(buf)
            shell.send(f'bash {REPO_SOURCE_ON_GUEST}/deploy/install.sh\n')
            buf, marker = _pump(shell, '', ['Setup menu'], 60, log)
            if marker is None:
                raise SystemExit('Never saw the Setup menu; see installer.log.')
            shell.send('1\n')
            buf, marker = _pump(shell, buf, ['New password:'], 60, log, auto_responses=auto)
            if marker is None:
                raise SystemExit('Never saw the New password prompt (phase 1-3 may have failed); see installer.log.')
            shell.send(manager_password + '\n')
            buf, marker = _pump(shell, buf, ['Retype new password:'], 30, log, auto_responses=auto)
            if marker is None:
                raise SystemExit('Never saw the Retype new password prompt; see installer.log.')
            shell.send(manager_password + '\n')
            manager_password = None  # never referenced again; not written anywhere
            buf, marker = _pump(shell, buf, ['Where are your lab configurations going?'], args.install_timeout, log,
                                 auto_responses=auto)
            if marker is None:
                raise SystemExit('Never reached the Git wizard; installer may have failed. See installer.log '
                                  'and look for "Needs attention:" / "Recovery".')
            # Record a little more so the wizard's first menu (with its numbered
            # choices) is fully captured, then stop here: GitHub login is out of scope.
            buf, _ = _pump(shell, buf, ['Choose [1]'], 15, log)
            shell.send('\x03')
            time.sleep(2)
            if shell.recv_ready():
                tail = shell.recv(65536).decode('utf-8', 'replace')
                log.write(tail)
            shell.send('echo INSTALLER_SESSION_DONE_$?\n')
            time.sleep(2)
            if shell.recv_ready():
                tail = shell.recv(65536).decode('utf-8', 'replace')
                log.write(tail)
        print(f'Installer session ended; raw transcript in {log_path} (kept out of evidence).')
    finally:
        client.close()


# ------------------------------------------------------------------ health --
def cmd_health(args):
    client = connect(args)
    try:
        code, out, err = run_ssh(client, f'bash {REPO_SOURCE_ON_GUEST}/deploy/check-install.sh', timeout=300)
    finally:
        client.close()
    scratch = Path(args.scratch)
    raw = scratch / args.out
    raw.write_text(out + ('\n--- stderr ---\n' + err if err.strip() else ''))
    print(f'check-install.sh exit {code}; raw report saved to {raw}')
    print(out)


# ------------------------------------------------------------------- state --
def cmd_state(args):
    client = connect(args)
    try:
        code, out, err = run_ssh(client, "curl -s http://127.0.0.1:8081/api/state")
    finally:
        client.close()
    scratch = Path(args.scratch)
    raw = scratch / args.out
    raw.write_text(out)
    print(f'/api/state saved to {raw} (exit {code})')
    print(out[:2000])


# --------------------------------------------------------------- inventory --
INVENTORY_COMMANDS = {
    'docker_ps': "sudo docker ps -a --format '{{.Names}} {{.Image}} {{.Status}}'",
    'docker_volumes': 'sudo docker volume ls',
    'docker_images': 'sudo docker images',
    'ss_ltnp': 'sudo ss -ltnp',
    'env_telemetry_count': f'grep -c TELEMETRY {REPO_SOURCE_ON_GUEST}/clab-backup-ui/.env || true',
    'srv_manager_ls': 'ls /srv/containerlab-node-manager',
    'retire_dry_run': f'sudo bash {REPO_SOURCE_ON_GUEST}/deploy/retire-telemetry.sh --dry-run --no-recreate',
    'host_operations_grafana_grep': 'sudo grep -c grafana /usr/local/lib/clab-manager/host_operations.py || true',
    'helper_versions': (
        "sudo grep -h \"helper_version\\|^VERSION\" /usr/local/lib/clab-manager/clab_manager_files.py "
        "/usr/local/lib/clab-manager/host_operations.py /usr/local/lib/clab-manager/host_git.py 2>&1"
    ),
}


def cmd_inventory(args):
    client = connect(args)
    try:
        results = {}
        for name, command in INVENTORY_COMMANDS.items():
            code, out, err = run_ssh(client, command, timeout=120)
            results[name] = {'code': code, 'stdout': out.strip(), 'stderr': err.strip()}
    finally:
        client.close()
    scratch = Path(args.scratch)
    (scratch / 'inventory.json').write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


# ------------------------------------------------------------------- again --
def cmd_again(args):
    client = connect(args)
    try:
        code, out, err = run_ssh(
            client, f'sudo bash {REPO_SOURCE_ON_GUEST}/deploy/start-manager.sh', timeout=600)
    finally:
        client.close()
    scratch = Path(args.scratch)
    (scratch / 'again-start-manager.log').write_text(out + err)
    print(f'start-manager.sh (repeat) exit {code}')
    print(out[-4000:])


# ------------------------------------------------------------------ reboot --
def cmd_reboot(args):
    client = connect(args)
    try:
        try:
            run_ssh(client, 'sudo reboot', timeout=5)
        except Exception:
            pass
    finally:
        client.close()
    print('Reboot issued; waiting for the guest to go down and come back...')
    time.sleep(10)
    cmd_wait_ssh(args)
    time.sleep(10)
    cmd_cloud_init_wait(args)


def cmd_reboot_check(args):
    client = connect(args)
    try:
        checks = {
            'manager_container': "sudo docker ps --format '{{.Names}} {{.Status}}' --filter name=backup-ui",
            'capture_containers': "sudo docker ps --format '{{.Names}} {{.Status}}' | grep -i capture || true",
            'state': 'curl -s http://127.0.0.1:8081/api/state',
            'no_telemetry': "sudo docker ps -a --format '{{.Names}}' | grep -i telemetry || echo NONE",
        }
        results = {}
        for name, command in checks.items():
            code, out, err = run_ssh(client, command, timeout=60)
            results[name] = {'code': code, 'stdout': out.strip(), 'stderr': err.strip()}
    finally:
        client.close()
    scratch = Path(args.scratch)
    (scratch / 'reboot-check.json').write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))


# ------------------------------------------------------------------ vmconn --
def cmd_vmconn(args):
    client = connect(args)
    try:
        put_body = '{"address":"127.0.0.1","port":22,"username":"clab-discovery","auth":"password",' \
                    '"password":"","command_mode":"helper","enabled":true,"reset_fingerprint":false}'
        put_cmd = (
            "curl -s -X PUT http://127.0.0.1:8081/api/host "
            f"-H 'Content-Type: application/json' --data-raw {shlex.quote(put_body)}"
        )
        code, out, err = run_ssh(client, put_cmd, timeout=60)
        refresh_cmd = "curl -s -X POST http://127.0.0.1:8081/api/discovery/refresh -H 'Content-Type: application/json' --data-raw '{}'"
        code2, out2, err2 = run_ssh(client, refresh_cmd, timeout=60)
    finally:
        client.close()
    scratch = Path(args.scratch)
    (scratch / 'vmconn.json').write_text(json.dumps({'put': out, 'refresh': out2}, indent=2))
    print('PUT /api/host ->', out)
    print('POST /api/discovery/refresh ->', out2)


# ---------------------------------------------------------------- shutdown --
def cmd_shutdown(args):
    client = connect(args)
    try:
        try:
            run_ssh(client, 'sudo poweroff', timeout=5)
        except Exception:
            pass
    finally:
        client.close()
    scratch = Path(args.scratch)
    pidfile = scratch / 'qemu.pid'
    if not pidfile.exists():
        print('No qemu.pid found; nothing to wait for.')
        return
    pid = pidfile.read_text().strip()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if not Path(f'/proc/{pid}').exists():
            print(f'QEMU pid {pid} exited cleanly.')
            pidfile.unlink(missing_ok=True)
            return
        time.sleep(2)
    print(f'QEMU pid {pid} still present after 60s; sending SIGTERM.')
    subprocess.run(['kill', pid])
    time.sleep(3)
    if not Path(f'/proc/{pid}').exists():
        print(f'QEMU pid {pid} exited after SIGTERM.')
        pidfile.unlink(missing_ok=True)
    else:
        print(f'QEMU pid {pid} still present; manual cleanup needed.')


# -------------------------------------------------------------------- cli --
def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--scratch', required=True, help='Scratch directory holding all VM state and logs.')
    parser.add_argument('--ssh-port', type=int, default=DEFAULT_SSH_PORT)
    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('keygen').set_defaults(func=cmd_keygen)

    sub.add_parser('seed').set_defaults(func=cmd_seed)

    p = sub.add_parser('disk')
    p.add_argument('--image', required=True)
    p.add_argument('--size', default=DEFAULT_DISK_SIZE)
    p.set_defaults(func=cmd_disk)

    p = sub.add_parser('boot')
    p.add_argument('--vcpus', type=int, default=DEFAULT_VCPUS)
    p.add_argument('--mem', type=int, default=DEFAULT_MEM_MB)
    p.set_defaults(func=cmd_boot)

    p = sub.add_parser('wait-ssh')
    p.add_argument('--timeout', type=int, default=180)
    p.set_defaults(func=cmd_wait_ssh)

    p = sub.add_parser('cloud-init-wait')
    p.add_argument('--timeout', type=int, default=300)
    p.set_defaults(func=cmd_cloud_init_wait)

    sub.add_parser('facts').set_defaults(func=cmd_facts)

    p = sub.add_parser('stage')
    p.add_argument('--archive', required=True)
    p.set_defaults(func=cmd_stage)

    p = sub.add_parser('installer')
    p.add_argument('--install-timeout', type=int, default=1800,
                    help='Seconds to wait for phases 1-6 plus lazydocker before the Git wizard.')
    p.set_defaults(func=cmd_installer)

    p = sub.add_parser('health')
    p.add_argument('--out', default='health.txt')
    p.set_defaults(func=cmd_health)

    p = sub.add_parser('state')
    p.add_argument('--out', default='state.json')
    p.set_defaults(func=cmd_state)

    sub.add_parser('inventory').set_defaults(func=cmd_inventory)
    sub.add_parser('again').set_defaults(func=cmd_again)
    p = sub.add_parser('reboot')
    p.add_argument('--timeout', type=int, default=180)
    p.set_defaults(func=cmd_reboot)
    sub.add_parser('reboot-check').set_defaults(func=cmd_reboot_check)
    sub.add_parser('vmconn').set_defaults(func=cmd_vmconn)
    sub.add_parser('shutdown').set_defaults(func=cmd_shutdown)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    Path(args.scratch).mkdir(parents=True, exist_ok=True)
    return args.func(args) or 0


if __name__ == '__main__':
    sys.exit(main())
