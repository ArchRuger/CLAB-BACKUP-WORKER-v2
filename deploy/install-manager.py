#!/usr/bin/env python3
"""Interactive Ubuntu installer; privileged work stays in the existing helpers."""
import argparse
import hashlib
import importlib.util
import io
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shlex
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.request import ProxyHandler, build_opener

SOURCE = Path(__file__).resolve().parents[1]
APT_LOCK_SCRIPT = SOURCE / 'deploy/apt_lock.py'
LOCK_SIGNATURE = re.compile(r'could not get lock|unable to acquire the dpkg frontend lock|held by process', re.I)


class Cancelled(Exception):
    pass


def ask(prompt, default=''):
    value = input(prompt + (f' [{default}]' if default else '') + ': ').strip()
    return value or default


def menu(title, choices, default='1'):
    print('\n' + title)
    for key, label in choices:
        print(f'  {key}. {label}')
    while True:
        selected = ask('Choose', default)
        if selected in dict(choices):
            return selected
        print('Choose one of the displayed numbers.')


def confirm(prompt):
    return ask(prompt + ' (y/N)').lower() in ('y', 'yes')


def environment(account):
    return {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
            'HOME': account.pw_dir, 'USER': account.pw_name, 'LOGNAME': account.pw_name,
            'LANG': 'C.UTF-8', 'TERM': os.environ.get('TERM', 'dumb')}


def run(args, env, capture=False, tee=False):
    # Password and GitHub device login prompts must keep the real terminal in
    # every mode: stdin is never redirected except the bounded `capture` checks.
    if tee:
        # A long package/build step: stream it live and also return its combined
        # output, so a caller can look for a specific error signature (never a
        # persisted log; the text is used in memory only, for this one decision).
        lines = []
        with subprocess.Popen(args, cwd=SOURCE, env=env, text=True, stdin=None,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as process:
            for line in process.stdout:
                print(line, end='', flush=True)
                lines.append(line)
            code = process.wait()
        return subprocess.CompletedProcess(args, code, stdout=''.join(lines))
    return subprocess.run(args, cwd=SOURCE, env=env, text=True,
                          stdin=subprocess.DEVNULL if capture else None,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.DEVNULL if capture else None,
                          timeout=30 if capture else None)


def output(args, env):
    result = run(args, env, capture=True)
    if result.returncode:
        raise ValueError('Check failed: ' + shlex.join(args) + '. Check Docker/sudo access and rerun checks.')
    return result.stdout.strip()


def source_version():
    spec = importlib.util.spec_from_file_location('release_check', SOURCE / 'deploy/verify-release.py')
    release = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release)
    return release.verify(SOURCE)


def compose(*args):
    return ['sudo', 'docker', '--host', 'unix:///var/run/docker.sock', 'compose',
            '-f', str(SOURCE / 'clab-backup-ui/compose.yml'), *args]


def health_url(command):
    if not isinstance(command, list) or not all(isinstance(item, str) for item in command):
        raise ValueError('Unexpected manager startup command. Check Compose configuration.')
    try:
        host = command[command.index('--host') + 1]
        port = int(command[command.index('--port') + 1])
        if host == 'localhost':
            host = '127.0.0.1'
        address = ipaddress.ip_address(host)
    except (ValueError, IndexError) as error:
        raise ValueError('Cannot determine the manager bind address/port from its running container.') from error
    if not 1 <= port <= 65535:
        raise ValueError('The configured manager port is outside 1-65535.')
    if address.is_unspecified:
        address = ipaddress.ip_address('::1' if address.version == 6 else '127.0.0.1')
    hostname = f'[{address}]' if address.version == 6 else str(address)
    return f'http://{hostname}:{port}/api/state'


def check_manager(env, version, wait_seconds=45):
    ident = output(compose('ps', '--status', 'running', '--quiet', 'backup-ui'), env)
    if not re.fullmatch(r'[0-9a-f]{12,64}', ident):
        raise ValueError('The Compose manager is not running. Choose Install/update, or inspect the launcher error.')
    running_version = output(compose('exec', '-T', 'backup-ui', 'python', '-c',
                                    'from app import __version__; print(__version__)'), env)
    if running_version != version:
        raise ValueError(f'Running manager version does not match source {version}. Choose Install/update to rebuild it.')
    command = json.loads(output(['sudo', 'docker', '--host', 'unix:///var/run/docker.sock',
                                 'inspect', '--format', '{{json .Config.Cmd}}', ident], env))
    url = health_url(command)
    # Ignore workstation/terminal proxy settings for this VM-local readiness test.
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            with opener.open(url, timeout=3) as response:
                data = response.read(8 * 1024 * 1024 + 1)
                if response.status == 200 and len(data) <= 8 * 1024 * 1024:
                    body = json.loads(data)
                    if isinstance(body, dict) and body.get('version') == version:
                        print(f'Manager {version}: running; HTTP and version checks passed.')
                        print('VM-local address: ' + url.removesuffix('/api/state') + '/')
                        print('From your workstation use the VM address and this port, not workstation 127.0.0.1.')
                        return
        except (OSError, ValueError):
            pass
        if time.monotonic() >= deadline:
            raise ValueError('Manager HTTP/version check did not pass. Inspect Compose logs and bind/port settings; '
                             'use Check installation to retry without rebuilding.')
        time.sleep(2)


def phase(title, action, env=None):
    while True:
        print('\n' + title)
        try:
            action()
            print('Completed: ' + title)
            return
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            print('Needs attention: ' + str(error))
            if env is not None and getattr(error, 'lock_signature', False):
                if lock_recovery(env):
                    continue
                raise Cancelled()
            if menu('Recovery', [('1', 'Retry this step after fixing the error'),
                                 ('2', 'Return to menu; keep completed work')], default='2') == '2':
                raise Cancelled()


def command_step(args, env, tee=False):
    # Only the package step streams through a pipe (to spot the dpkg lock signature);
    # every other step keeps the real terminal: setup-password.sh reads the new
    # clab-discovery password from it and refuses to run without one.
    result = run(args, env, tee=tee)
    if result.returncode:
        error = ValueError('The command above failed. Completed setup and existing data are retained.')
        error.lock_signature = bool(LOCK_SIGNATURE.search(getattr(result, 'stdout', '') or ''))
        raise error


def lock_free(env):
    # timeout 0: an immediate check, never an actual wait.
    try:
        result = run(['sudo', '-n', 'python3', str(APT_LOCK_SCRIPT), '--wait', '--timeout', '0'], env, capture=True)
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0


def lock_holder_text(env):
    try:
        result = run(['sudo', '-n', 'python3', str(APT_LOCK_SCRIPT), '--show'], env, capture=True)
    except subprocess.TimeoutExpired:
        return ''
    return (result.stdout or '') if result.returncode == 0 else ''


def lock_recovery(env):
    """A package step failed with the dpkg/apt lock signature. Show the live holder and let the
    operator wait here, retry immediately, or return to the menu. True retries the failed step."""
    manual_command = ['sudo', 'python3', str(APT_LOCK_SCRIPT), '--wait', '--pause-timers']
    while True:
        if lock_free(env):
            print('The package lock is now released.')
            return True
        report = lock_holder_text(env)
        if report:
            print(report)
        print('Copyable command, in another terminal: ' + shlex.join(manual_command))
        choice = menu('Package lock recovery', [
            ('1', 'Wait for the package lock here, then retry this step (recommended)'),
            ('2', 'Retry this step now'),
            ('3', 'Return to menu; keep completed work')], default='1')
        if choice == '3':
            return False
        if choice == '2':
            return True
        result = run(['sudo', 'python3', str(APT_LOCK_SCRIPT), '--wait', '--pause-timers'], env)
        if result.returncode == 0:
            print('The package lock is released.')
            return True
        print('The wait ended without releasing the package lock; checking again.')


def default_env_choice():
    """Standard path: no bind/port menu. An existing .env is retained unchanged; a missing one
    gets the documented defaults (all VM interfaces, port 8081) with no file written here."""
    target = SOURCE / 'clab-backup-ui/.env'
    if target.is_symlink():
        raise ValueError('The source .env is a symlink. Use a regular settings file before setup.')
    if target.exists():
        print('Existing clab-backup-ui/.env will be retained unchanged.')
    else:
        print('No existing clab-backup-ui/.env: using the defaults (all VM interfaces, port 8081).')
    return None


def choose_env_copy():
    target = SOURCE / 'clab-backup-ui/.env'
    if target.is_symlink():
        raise ValueError('The source .env is a symlink. Use a regular settings file before setup.')
    if target.exists():
        print('Existing clab-backup-ui/.env will be retained unchanged.')
        return None
    choice = menu('Manager bind/port settings', [('1', 'Use defaults: all VM interfaces, port 8081'),
                  ('2', 'Copy .env from a previous source folder'), ('3', 'Back')])
    if choice == '3':
        raise Cancelled()
    if choice == '1':
        return None
    while True:
        value = ask('Previous .env absolute path (blank to go back)')
        if not value:
            raise Cancelled()
        path = Path(value).expanduser()
        if (path.is_absolute() and path.is_file() and not path.is_symlink()
                and stat.S_ISREG(path.stat().st_mode) and path.stat().st_size <= 65536):
            return path
        print('Choose a regular .env file no larger than 64 KiB. Its contents will not be displayed.')


def copy_env(path):
    if path is None:
        return
    data = path.read_bytes()
    if len(data) > 65536:
        raise ValueError('Previous .env exceeds 64 KiB.')
    # Exclusive creation never replaces settings written after the plan was shown.
    target = SOURCE / 'clab-backup-ui/.env'
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
    print('Previous .env copied with private permissions; its contents were retained.')


def git_setup(env):
    print('\nGit setup runs as ' + env['USER'] + ', with home ' + env['HOME'] + '.')
    result = run(['bash', str(SOURCE / 'deploy/setup-git.sh')], env)
    if result.returncode == 0:
        print('Git setup completed. In the manager, connect the registered checkout to your lab.')
    else:
        print('Git setup is incomplete. The manager and existing checkout remain available.')
        print('Choose Git setup from this menu to resume without rebuilding the manager.')
    return result.returncode


LAZYDOCKER_ARCH = {'x86_64': 'x86_64', 'aarch64': 'arm64', 'arm64': 'arm64',
                   'armv7l': 'armv7', 'armv6l': 'armv6'}
LAZYDOCKER_PATH_BLOCK = ('# Added by Containerlab Node Manager setup: user tools such as lazydocker\n'
                        'case ":$PATH:" in *":$HOME/.local/bin:"*) ;; '
                        '*) export PATH="$PATH:$HOME/.local/bin";; esac\n')


def lazydocker_arch(machine=None):
    return LAZYDOCKER_ARCH.get(platform.machine() if machine is None else machine)


def lazydocker_latest_tag(timeout=20):
    opener = build_opener(ProxyHandler({}))
    with opener.open('https://api.github.com/repos/jesseduffield/lazydocker/releases/latest', timeout=timeout) as response:
        data = json.loads(response.read(1024 * 1024))
    tag = data.get('tag_name') if isinstance(data, dict) else None
    if not isinstance(tag, str) or not re.fullmatch(r'v?\d+\.\d+\.\d+', tag):
        raise ValueError('Unexpected lazydocker release tag.')
    return tag


def download_lazydocker_tarball(tag, arch, timeout=20):
    version = tag[1:] if tag.startswith('v') else tag
    url = (f'https://github.com/jesseduffield/lazydocker/releases/download/{tag}/'
          f'lazydocker_{version}_Linux_{arch}.tar.gz')
    opener = build_opener(ProxyHandler({}))
    with opener.open(url, timeout=timeout) as response:
        return response.read(64 * 1024 * 1024)


def lazydocker_tarball_filename(tag, arch):
    version = tag[1:] if tag.startswith('v') else tag
    return f'lazydocker_{version}_Linux_{arch}.tar.gz'


def download_lazydocker_checksums(tag, timeout=20):
    # Same release, same asset lazydocker itself publishes; mirrors the official
    # containerlab .deb verification in install-prerequisites.sh.
    url = f'https://github.com/jesseduffield/lazydocker/releases/download/{tag}/checksums.txt'
    opener = build_opener(ProxyHandler({}))
    with opener.open(url, timeout=timeout) as response:
        return response.read(1024 * 1024).decode('utf-8', 'replace')


def verify_lazydocker_checksum(data, checksums_text, filename):
    """Exactly one checksums.txt line for `filename`, whose SHA-256 matches `data`.
    False for a mismatched digest, an absent or duplicated entry, or an empty checksums
    file — every one of those is treated as a verification failure by the caller."""
    matches = []
    for line in checksums_text.splitlines():
        match = re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?(.+)', line.strip())
        if match and match[2] == filename:
            matches.append(match[1].lower())
    if len(matches) != 1:
        return False
    return hashlib.sha256(data).hexdigest() == matches[0]


def _lazydocker_member(archive):
    # Only the exact top-level file, never a nested or traversal path such as
    # 'sub/lazydocker' or '../lazydocker' (those never equal 'lazydocker' below).
    for candidate in archive.getmembers():
        name = candidate.name[2:] if candidate.name.startswith('./') else candidate.name
        if name == 'lazydocker' and candidate.isfile():
            return candidate
    return None


def install_lazydocker_binary(tarball_bytes, destination):
    with tarfile.open(fileobj=io.BytesIO(tarball_bytes), mode='r:gz') as archive:
        member = _lazydocker_member(archive)
        if member is None:
            raise ValueError("The lazydocker archive did not contain a 'lazydocker' file.")
        extracted = archive.extractfile(member)
        if extracted is None:
            raise ValueError('Could not read the lazydocker archive member.')
        data = extracted.read()
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.lazydocker-', dir=str(destination.parent))
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(data)
        os.chmod(temporary, 0o755)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def lazydocker_up_to_date(path, version, env):
    if not path.is_file():
        return False
    try:
        result = subprocess.run([str(path), '--version'], env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and version in result.stdout


def _local_bin_path_line(text):
    return any('.local/bin' in line and 'PATH' in line for line in text.splitlines())


def ensure_local_bin_on_path(home):
    # Never another user's file: home is always the invoking account's own $HOME.
    bashrc = Path(home) / '.bashrc'
    text = bashrc.read_text() if bashrc.exists() else ''
    if _local_bin_path_line(text):
        return False
    if text and not text.endswith('\n'):
        text += '\n'
    text += '\n' + LAZYDOCKER_PATH_BLOCK
    bashrc.write_text(text)
    return True


def setup_lazydocker(env):
    # Ordinary-user convenience tool; never installed as root, and a failure here
    # never fails the installation, only prints a warning.
    print('\nlazydocker (optional; browse/manage Docker from the terminal)')
    machine = platform.machine()
    arch = lazydocker_arch(machine)
    if arch is None:
        print(f'lazydocker: unsupported architecture ({machine}); skipping.')
        return
    home = Path(env['HOME'])
    destination = home / '.local' / 'bin' / 'lazydocker'
    try:
        tag = lazydocker_latest_tag()
        version = tag[1:] if tag.startswith('v') else tag
        if lazydocker_up_to_date(destination, version, env):
            print(f'lazydocker {version} is already current.')
        else:
            tarball = download_lazydocker_tarball(tag, arch)
            filename = lazydocker_tarball_filename(tag, arch)
            checksums_text = download_lazydocker_checksums(tag)
            if not verify_lazydocker_checksum(tarball, checksums_text, filename):
                raise ValueError(f'lazydocker checksum verification failed for {filename}; '
                                 'the release asset may be incomplete or compromised.')
            install_lazydocker_binary(tarball, destination)
            print(f'lazydocker {version} installed to {destination}.')
        if ensure_local_bin_on_path(home):
            print('Added ~/.local/bin to PATH in ~/.bashrc (new shells only).')
        if str(destination.parent) not in os.environ.get('PATH', '').split(os.pathsep):
            print('This shell does not have that directory on PATH yet; to use it now, run:')
            print('  export PATH="$PATH:$HOME/.local/bin"')
    except Exception as error:  # optional tool: any failure is a warning, never the installation's
        print(f'lazydocker setup skipped: {error}')


def engineer_access(env):
    # Groups, group-writable trusted lab folders and containerlab SUID for the
    # installing account. Privileged work stays in the dedicated helper script.
    command_step(['sudo', 'bash', str(SOURCE / 'deploy/setup-engineer-access.sh'), '--owner', env['USER']], env)
    print('New groups apply to new logins: reconnect SSH, and in VS Code run '
          '"Remote-SSH: Kill VS Code Server on Host..." then reconnect before using the Containerlab extension.')


def stack_command(name):
    # Same privileged environment as the launcher: the local rootful daemon, never a remote context.
    return ['sudo', 'env', 'DOCKER_HOST=unix:///var/run/docker.sock', 'bash', str(SOURCE / 'deploy' / name)]


def capture_stack(env):
    # Browser Wireshark: Edgeshark discovery, the session service built from this source and the
    # pinned Wireshark image. Part of every installation; the script recreates the manager itself.
    command_step(stack_command('setup-capture.sh'), env)


def stacks(env):
    phase('Browser Wireshark capture stack', lambda: capture_stack(env), env)
    print('Wireshark opens from the map (Capture packets).')


def verify_manager(env, version):
    # A source build can outlast sudo's timestamp; renew on the real terminal
    # before checks that deliberately capture output and have no stdin.
    command_step(['sudo', '-v'], env)
    check_manager(env, version)


def health_report(env):
    result = run(['bash', str(SOURCE / 'deploy/check-install.sh')], env)
    if result.returncode:
        print('Review the health report above, complete the indicated steps, then run the check again.')
    return result.returncode


def install(env, version, advanced=False):
    # Standard path: the routine choices are automatic (A2). --advanced restores every
    # question, including copying .env from a previous source folder.
    if advanced:
        env_source = choose_env_copy()
        operations = menu('Lab operation access', [('1', 'Enable reviewed lab operations (standard standalone setup)'),
                         ('2', 'Discovery/import only; retain any previously enabled operations'), ('3', 'Back')])
        if operations == '3':
            raise Cancelled()
        engineer = '2'
        if operations == '1':
            # The manager works without this; VS Code Remote - SSH with the Containerlab
            # extension does not (groups, writable lab folders, containerlab SUID).
            engineer = menu('VS Code / Containerlab extension access for ' + env['USER'],
                            [('1', 'Set up now: docker and clab_admins groups, group-writable lab folders, containerlab SUID (standard)'),
                             ('2', 'Skip; the manager does not need it')])
        repair = confirm('Back up and disable obsolete installation-media APT entries if present?')
    else:
        env_source = default_env_choice()
        operations, engineer, repair = '1', '1', True
    print('\nInstallation plan')
    print('  Source: ' + str(SOURCE) + ' (' + version + ')')
    print('  Install missing prerequisites: Git, SSH, Docker/Compose and containerlab.')
    print('  Check UTC/NTP before APT; wait briefly for active time sync without changing time settings.')
    print('  Retain compatible installed tools; start Docker and SSH services.')
    print('  Prepare persistent storage and restricted clab-discovery password/helpers.')
    print('  Existing password/data retained; first setup asks you to create the password.')
    print('  Rebuild/recreate only the manager; existing lab containers remain in place.')
    print('  Lab operations: ' + ('enabled with default trusted roots' if operations == '1' else 'existing permissions retained'))
    print('  Browser Wireshark: pull the pinned Wireshark image, build the session service, start Edgeshark (localhost 5001/5801).')
    print('  Engineer access: ' + ('set up for ' + env['USER'] + ' (VS Code, Containerlab extension)' if engineer == '1' else 'not selected'))
    print('  Settings: ' + ('copy ' + str(env_source) if env_source else 'retain current .env or use defaults'))
    print('  Installation-media APT repair: ' + ('enabled with backup' if repair else 'not selected'))
    print('  lazydocker: install or update for ' + env['USER'] + ' (never fails the installation).')
    print('  Check running version/HTTP, then set up Git under ' + env['USER'] + '.')
    if advanced:
        if not confirm('Proceed with this plan?'):
            raise Cancelled()
    else:
        print('Starting now; the standard path runs these steps without further confirmation.')
    total = '6' if engineer == '1' else '5'
    phase('1/' + total + ' Administrator access and settings', lambda: command_step(['sudo', '-v'], env), env)
    copy_env(env_source)
    prereqs = ['sudo', 'bash', str(SOURCE / 'deploy/install-prerequisites.sh'), '--docker', '--containerlab']
    if repair:
        prereqs.append('--repair-install-media')
    phase('2/' + total + ' VM prerequisites', lambda: command_step(prereqs, env, tee=True), env)
    # A separate phase so a failed image pull is retried on its own instead of repeating the
    # password, helper and image-build step.
    launch = ['sudo', 'env', 'DOCKER_HOST=unix:///var/run/docker.sock',
              'bash', str(SOURCE / 'deploy/start-manager.sh'), '--manager-only']
    if operations == '1':
        launch.append('--enable-operations')
    phase('3/' + total + ' Password, helpers, image and manager', lambda: command_step(launch, env), env)
    phase('4/' + total + ' Browser Wireshark capture stack', lambda: capture_stack(env), env)
    phase('5/' + total + ' Running manager verification', lambda: verify_manager(env, version), env)
    if engineer == '1':
        phase('6/6 Engineer access for VS Code', lambda: engineer_access(env), env)
    setup_lazydocker(env)
    print('\nManager installation is ready. Git is a separate setup step under your ordinary account.')
    print('Wireshark opens from the map (Capture packets).')
    if advanced:
        # Item 1 says "then set up Git"; the standard path always runs it, the advanced
        # path keeps the choice of doing it now or later.
        if menu('Next step', [('1', 'Set up or repair Git now'), ('2', 'Finish; set up Git later')]) == '1':
            git_setup(env)
    else:
        git_setup(env)
    print('In VM connection use clab-discovery and the password you created. Verify the host fingerprint.')
    print('After browser setup, run the full installation health report (without sudo):\n  '
          + shlex.join(['bash', str(SOURCE / 'deploy/check-install.sh')]))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Guided manager install/update and Git setup for Ubuntu 24.04.')
    parser.add_argument('--git', action='store_true', help='Open Git setup directly (manager already installed)')
    parser.add_argument('--advanced', action='store_true',
                        help='Ask every setup question again (bind/port, lab operations, VS Code access, '
                             'APT installation-media repair, plan confirmation, Git now/later) instead of '
                             'the standard defaults.')
    args = parser.parse_args(argv)
    if sys.platform != 'linux' or os.geteuid() == 0:
        raise ValueError('Run on the Ubuntu VM as its ordinary account, without sudo.')
    import pwd
    account = pwd.getpwuid(os.geteuid())
    if account.pw_name == 'clab-discovery':
        raise ValueError('Use your ordinary VM account, not clab-discovery.')
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError('Open an interactive SSH/VM terminal; do not pipe the installer.')
    version = source_version()
    env = environment(account)
    print(f'\nContainerlab Node Manager {version} — guided setup')
    print(f'Linux account: {account.pw_name}\nPersistent home: {account.pw_dir}\nSource: {SOURCE}')
    if args.git:
        return git_setup(env)
    while True:
        choice = menu('Setup menu', [('1', 'Install or update manager, then set up Git'),
                      ('2', 'Git setup / repair only (no rebuild)'),
                      ('3', 'VS Code / Containerlab extension access for ' + account.pw_name + ' (no rebuild)'),
                      ('4', 'Browser Wireshark stack only (reinstall or upgrade, no rebuild)'),
                      ('5', 'Check running installation'), ('6', 'Exit')])
        if choice == '6':
            return 0
        try:
            # A5: a successful path prints its completion information (already done by
            # each step above) and exits to the shell rather than looping back here. A
            # failure or cancellation keeps today's behaviour: retained work, the
            # Recovery menu inside phase(), and this Setup menu.
            if choice == '1':
                install(env, version, advanced=args.advanced)
                return 0
            elif choice == '2':
                if git_setup(env) == 0:
                    return 0
            elif choice == '3':
                phase('Engineer access for VS Code', lambda: engineer_access(env), env)
                return 0
            elif choice == '4':
                stacks(env)
                return 0
            else:
                if health_report(env) == 0:
                    return 0
        except Cancelled:
            print('Returned to menu. Existing data and completed steps are retained.')


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        sys.exit('\nSetup stopped. Existing data is retained; rerun this installer to continue.')
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        sys.exit('\nSetup stopped: ' + str(error))
