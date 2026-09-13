"""Read-only host checks for check-install.py; never requests an SSH password."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import stat


GATEWAY = '/usr/local/sbin/clab-manager-gateway'
SFTP_SERVER = '/usr/lib/openssh/sftp-server'
ENGINEER_CONFIG = '/etc/clab-manager/engineer.json'
OPERATIONS_CONFIG = '/etc/clab-manager/operations.json'
ENGINEER_FIX = 'Run sudo bash deploy/setup-engineer-access.sh --refresh (or choose VS Code access in bash deploy/install.sh), then reconnect SSH and kill the VS Code server on the host.'
POLICY = {
    'authenticationmethods': 'password', 'passwordauthentication': 'yes',
    'kbdinteractiveauthentication': 'no', 'pubkeyauthentication': 'no',
    'permitemptypasswords': 'no', 'forcecommand': GATEWAY,
    'disableforwarding': 'yes', 'permittty': 'no', 'permittunnel': 'no',
    'permituserrc': 'no', 'permituserenvironment': 'no',
}
SSH_FIX = 'Run bash deploy/install.sh to install prerequisites and the VM connection helpers.'


def _read(path):
    try:
        with open(path, encoding='utf-8') as handle:
            data = handle.read(65537)
        return data if len(data) <= 65536 else ''
    except (OSError, UnicodeError):
        return ''


def _values(text, separator=None):
    values = {}
    for line in text.splitlines():
        pair = line.strip().split(separator, 1)
        if len(pair) == 2:
            values[pair[0]] = pair[1].strip().strip('"')
    return values


def _executable(path):
    return os.path.isfile(path) and os.access(path, os.X_OK)


def _disk(ctx, check_id, title, path):
    target = Path(path)
    try:
        while not target.exists() and target != target.parent:
            target = target.parent
        usage = shutil.disk_usage(target)
        gib = usage.free / (1024 ** 3)
        fraction = usage.free / max(usage.total, 1)
        status = 'FAIL' if gib < 1 else 'WARN' if gib < 5 or fraction < .1 else 'PASS'
        ctx.add(check_id, status, title, f'{gib:.1f} GiB free ({fraction:.0%}) on its current backing filesystem; lab image needs vary.',
                'Free space or extend the VM filesystem before installing images or saving backups.' if status != 'PASS' else '')
    except OSError:
        ctx.add(check_id, 'WARN', title, 'Free space could not be read.', 'Inspect df -h on the VM.')


def _clock(ctx):
    result = ctx.run(['timedatectl', 'show', '--property=NTPSynchronized', '--property=NTP'], timeout=5)
    values = _values(result.stdout, '=') if result.ok else {}
    synced = values.get('NTPSynchronized') == 'yes'
    stamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    ctx.add('host.clock', 'PASS' if synced else 'WARN', 'VM clock synchronization',
            f'VM reports {stamp}. ' + ('NTP reports synchronized; no external time comparison was made.' if synced else
            'NTP synchronization is not confirmed; APT can reject future-dated release files.'),
            '' if synced else 'Check date -u and timedatectl status; correct VM/Proxmox time and enable working time synchronization before retrying APT.')


def _listener(ctx, config):
    ports = []
    for line in config.splitlines():
        fields = line.split()
        if len(fields) == 2 and fields[0] == 'port' and fields[1].isdigit() and 0 < int(fields[1]) < 65536:
            ports.append(int(fields[1]))
    ports = list(dict.fromkeys(ports or [22]))[:4]
    for port in ports:
        for address in ('127.0.0.1', '::1'):
            try:
                with socket.create_connection((address, port), timeout=1):
                    ctx.add('ssh.listener', 'PASS', 'SSH TCP listener', f'Loopback TCP port {port} accepts connections. SSH socket activation is supported; remote firewall access is not tested.')
                    return
            except OSError:
                pass
    bound_elsewhere = any(line.startswith('listenaddress ') and not any(value in line for value in ('0.0.0.0:', '[::]:', '127.0.0.1:', '[::1]:'))
                         for line in config.splitlines())
    ctx.add('ssh.listener', 'WARN' if bound_elsewhere else 'FAIL', 'SSH TCP listener',
            'No checked loopback SSH port accepted a connection.' + (' A configured address may only accept remote clients.' if bound_elsewhere else ''),
            'Check sudo systemctl status ssh.service ssh.socket and sudo ss -ltnp; test the VM address from your workstation.')


def _effective(ctx, user, address='127.0.0.1'):
    return ctx.run(['/usr/sbin/sshd', '-T', '-C', f'user={user},host=localhost,addr={address}'], privileged=True, timeout=5)


def _admin_sftp(ctx):
    severity = 'FAIL' if ctx.require_admin_sftp else 'INFO'
    if not ctx.owner:
        ctx.add('sftp.admin', 'WARN' if ctx.require_admin_sftp else 'INFO', 'Optional WinSCP root file access',
                'No ordinary Linux owner was selected; permission cannot be checked.', 'Rerun with --owner followed by your Ubuntu account name.')
        return
    if not ctx.privileged:
        ctx.add('sftp.admin', 'WARN', 'Optional WinSCP root file access', 'Administrator access is needed to inspect the effective sudoers permission.')
        return
    result = ctx.run(['sudo', '-n', '-ll', '-U', ctx.owner, '--', SFTP_SERVER], privileged=True, timeout=5)
    # Verbose listing with a command returns the matching rule. Listing permission
    # alone does not mean its command is NOPASSWD (especially for sudo-group users).
    option_lines = re.findall(r'^\s*Options:\s*(.*)$', result.stdout, re.MULTILINE) if result.ok else []
    options = [value.strip() for line in option_lines for value in line.split(',')]
    no_password = bool(options) and '!authenticate' in options and 'authenticate' not in options
    if result.ok and no_password and _executable(SFTP_SERVER):
        ctx.add('sftp.admin', 'PASS', 'Optional WinSCP root file access',
                'Effective sudoers rule permits passwordless root SFTP. WinSCP must use sudo -n /usr/lib/openssh/sftp-server; this grants root file access.')
    else:
        ctx.add('sftp.admin', severity, 'Optional WinSCP root file access',
                'Passwordless root SFTP is not confirmed. Ordinary SFTP to folders owned by your account does not need this permission.',
                'If needed, follow docs/INSTALL.md: edit the owner-specific sudoers file with visudo, validate it, and set the WinSCP SFTP server command.')


def _ssh(ctx):
    if not _executable('/usr/sbin/sshd'):
        ctx.add('ssh.config', 'FAIL', 'OpenSSH server', 'The SSH server executable is missing.', SSH_FIX)
        ctx.add('ssh.listener', 'SKIP', 'SSH TCP listener', 'OpenSSH must be installed first.')
        ctx.add('ssh.discovery', 'SKIP', 'Manager SSH account', 'OpenSSH must be installed first.')
        ctx.add('sftp.normal', 'SKIP', 'Ordinary account SFTP', 'OpenSSH must be installed first.')
        _admin_sftp(ctx)
        return
    if not ctx.privileged:
        ctx.add('ssh.config', 'WARN', 'SSH effective configuration', 'Administrator access is needed to validate server configuration and account policy.')
        _listener(ctx, '')
        _admin_sftp(ctx)
        return
    syntax = ctx.run(['/usr/sbin/sshd', '-t'], privileged=True, timeout=5)
    ctx.add('ssh.config', 'PASS' if syntax.ok else 'FAIL', 'SSH configuration syntax',
            'sshd validates its configuration.' if syntax.ok else 'sshd rejected or could not validate its configuration.',
            '' if syntax.ok else 'Run sudo /usr/sbin/sshd -t on the VM and correct the reported configuration error before reload.')
    discovery = ctx.run(['getent', 'passwd', 'clab-discovery'], timeout=5)
    password = ctx.run(['passwd', '-S', 'clab-discovery'], privileged=True, timeout=5) if discovery.ok else None
    password_set = bool(password and password.ok and len(password.stdout.split()) >= 2 and password.stdout.split()[1] == 'P')
    effective = _effective(ctx, 'clab-discovery')
    remote = _effective(ctx, 'clab-discovery', '192.0.2.1')
    restricted = all(result.ok and all(_values(result.stdout).get(key) == value for key, value in POLICY.items()) for result in (effective, remote))
    good = discovery.ok and password_set and restricted and _executable(GATEWAY)
    ctx.add('ssh.discovery', 'PASS' if good else 'FAIL', 'Manager SSH account and restrictions',
            'clab-discovery has a set password and the restricted gateway policy for local and sample remote addresses; no password login was attempted.' if good else
            'Account, set-password status, executable gateway or required effective SSH restrictions are missing or could not be verified.', SSH_FIX if not good else '')
    owner = _effective(ctx, ctx.owner) if ctx.owner else effective
    _listener(ctx, owner.stdout if owner.ok else effective.stdout if effective.ok else '')
    if not ctx.owner:
        ctx.add('sftp.normal', 'WARN', 'Ordinary account SFTP', 'The ordinary Linux owner is unknown; clab-discovery deliberately blocks SFTP.', 'Rerun with --owner followed by your Ubuntu account name.')
    else:
        policy = _values(owner.stdout) if owner.ok else {}
        subsystem = next((line.split()[2:] for line in owner.stdout.splitlines() if line.startswith('subsystem sftp ')), []) if owner.ok else []
        server = bool(subsystem and (subsystem[0] == 'internal-sftp' or _executable(subsystem[0])))
        usable = server and policy.get('forcecommand') in ('none', 'internal-sftp')
        password_auth = policy.get('passwordauthentication') == 'yes' and policy.get('authenticationmethods') in ('any', 'password')
        status = 'FAIL' if not usable else 'PASS' if password_auth else 'WARN'
        ctx.add('sftp.normal', status, 'Ordinary account SFTP configuration',
                'SFTP subsystem and ordinary password policy are present; verify a real WinSCP login and upload as your Ubuntu account.' if status == 'PASS' else
                'SFTP subsystem, forced command or password policy needs review. Key-only or client-specific policies may be intentional.',
                '' if status == 'PASS' else 'Use your ordinary Ubuntu account, not clab-discovery. Follow the SSH/SFTP recovery section in docs/FRESH-VM-GUIDE-V2.md.')
    _admin_sftp(ctx)


def _json_file(ctx, path):
    # Root-only manager configuration; both files hold only account names and paths.
    result = ctx.run(['cat', path], privileged=True, timeout=5)
    if not result.ok:
        return None
    try:
        value = json.loads(result.stdout)
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _engineer(ctx):
    """VS Code Remote - SSH with the Containerlab extension needs what the manager does not.

    The two errors this explains: "Extension activation failed. Insufficient permissions.
    Ensure USER is in the clab_admins and docker group(s)" and "EACCES: permission denied,
    mkdir '/etc/containerlab/...'" from the VS Code file explorer.
    """
    title = 'Engineer access for VS Code / Containerlab extension'
    if not ctx.privileged:
        ctx.add('host.engineer', 'INFO', title, 'Administrator access is needed to inspect groups, lab folders and the containerlab mode.')
        return
    config = _json_file(ctx, ENGINEER_CONFIG)
    owner = config.get('owner') if config else None
    if not isinstance(owner, str) or not owner:
        ctx.add('host.engineer', 'INFO', title,
                'Not configured. The manager does not need it; VS Code Remote - SSH with the Containerlab extension does '
                '(docker and clab_admins groups, group-writable lab folders, containerlab SUID).',
                'Run sudo bash deploy/setup-engineer-access.sh --owner YOUR_VM_USER, or choose VS Code access in bash deploy/install.sh.')
        return
    problems = []
    groups = ctx.run(['id', '-nG', owner], timeout=5)
    missing = sorted({'docker', 'clab_admins'} - set(groups.stdout.split())) if groups.ok else ['docker', 'clab_admins']
    if missing:
        problems.append(owner + ' lacks the ' + ' and '.join(missing) + ' group(s)')
    operations = _json_file(ctx, OPERATIONS_CONFIG) or {}
    roots = [r for r in operations.get('roots', []) if isinstance(r, str) and r.startswith('/')]
    for root in roots:
        result = ctx.run(['stat', '-c', '%G %a', root], privileged=True, timeout=5)
        fields = result.stdout.split() if result.ok else []
        try:
            mode = int(fields[1], 8) if len(fields) == 2 else -1
        except ValueError:
            mode = -1
        # setgid (02000) plus group write (00020): new files inherit clab_admins and
        # the engineer's editor can create and change lab files.
        if len(fields) != 2 or fields[0] != 'clab_admins' or mode < 0 or mode & 0o2020 != 0o2020:
            problems.append(root + ' is not a group-writable clab_admins lab folder')
    binary = next((path for path in ('/usr/bin/containerlab', '/usr/local/bin/containerlab') if _executable(path)), '')
    result = ctx.run(['stat', '-c', '%u %a', binary], privileged=True, timeout=5) if binary else None
    fields = result.stdout.split() if result and result.ok else []
    try:
        suid = len(fields) == 2 and fields[0] == '0' and int(fields[1], 8) & 0o4000 == 0o4000
    except ValueError:
        suid = False
    if not suid:
        problems.append('containerlab is not the root-owned SUID binary the extension runs without sudo')
    ctx.add('host.engineer', 'FAIL' if problems else 'PASS', title,
            ('Configured for ' + owner + ' but incomplete: ' + '; '.join(problems) + '. Existing SSH and VS Code server sessions keep their old groups until restarted.') if problems
            else 'Configured for ' + owner + ': docker and clab_admins groups, group-writable clab_admins lab folders (' + ', '.join(roots) + ') and the SUID containerlab binary. Group changes need a fresh login.',
            ENGINEER_FIX if problems else '')


def check_host(ctx):
    release = _values(_read('/etc/os-release'), '=')
    supported = release.get('ID') == 'ubuntu' and release.get('VERSION_ID') == '24.04' and platform.machine() in ('x86_64', 'aarch64', 'arm64')
    ctx.add('host.os', 'PASS' if supported else 'WARN', 'Supported installer platform',
            'Ubuntu 24.04 on a supported architecture.' if supported else 'Ubuntu 24.04 amd64/arm64 was not confirmed; this is the automatic installer target.')
    _clock(ctx)
    _disk(ctx, 'host.disk_source', 'Source filesystem free space', ctx.source)
    _disk(ctx, 'host.disk_data', 'Default manager data filesystem free space', '/srv/containerlab-node-manager/data')
    _ssh(ctx)
    guest = ctx.run(['dpkg-query', '-W', '-f=${db:Status-Status}', 'qemu-guest-agent'], timeout=5)
    if guest.ok and guest.stdout.strip() == 'installed':
        active = ctx.run(['systemctl', 'is-active', 'qemu-guest-agent.service'], timeout=5)
        ctx.add('host.guest_agent', 'PASS' if active.ok else 'WARN', 'Optional Proxmox guest agent',
                'QEMU guest agent is active.' if active.ok else 'Installed guest agent is not active; check the Proxmox guest-agent device and service.')
    else:
        ctx.add('host.guest_agent', 'INFO', 'Optional Proxmox guest agent', 'QEMU guest agent is not confirmed installed; the manager does not require it.')
    try:
        kvm = stat.S_ISCHR(os.stat('/dev/kvm').st_mode)
    except OSError:
        kvm = False
    ctx.add('host.kvm', 'PASS' if kvm else 'FAIL' if ctx.require_kvm else 'INFO', 'KVM device for VM-based network images',
            '/dev/kvm is present. Image-specific permissions and successful guest boot remain to be tested.' if kvm else
            '/dev/kvm is absent. VM-based NOS images need nested virtualization; ordinary container images may not.',
            '' if kvm else 'If using VM-based images, check the Proxmox host nested-virtualization setting and VM CPU type in docs/FRESH-VM-GUIDE-V2.md.')
    _engineer(ctx)
