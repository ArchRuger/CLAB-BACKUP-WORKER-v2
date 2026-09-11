#!/usr/bin/env python3
"""Interactive Ubuntu installer; privileged work stays in the existing helpers."""
import argparse
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import stat
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener

SOURCE = Path(__file__).resolve().parents[1]


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


def run(args, env, capture=False):
    # Password and GitHub device login prompts must keep the real terminal.
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


def phase(title, action):
    while True:
        print('\n' + title)
        try:
            action()
            print('Completed: ' + title)
            return
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            print('Needs attention: ' + str(error))
            if menu('Recovery', [('1', 'Retry this step after fixing the error'),
                                 ('2', 'Return to menu; keep completed work')], default='2') == '2':
                raise Cancelled()


def command_step(args, env):
    if run(args, env).returncode:
        raise ValueError('The command above failed. Completed setup and existing data are retained.')


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


def install(env, version):
    env_source = choose_env_copy()
    operations = menu('Lab operation access', [('1', 'Enable reviewed lab operations (standard standalone setup)'),
                     ('2', 'Discovery/import only; retain any previously enabled operations'), ('3', 'Back')])
    if operations == '3':
        raise Cancelled()
    repair = confirm('Back up and disable obsolete installation-media APT entries if present?')
    print('\nInstallation plan')
    print('  Source: ' + str(SOURCE) + ' (' + version + ')')
    print('  Install missing prerequisites: Git, SSH, Docker/Compose and containerlab.')
    print('  Check UTC/NTP before APT; wait briefly for active time sync without changing time settings.')
    print('  Retain compatible installed tools; start Docker and SSH services.')
    print('  Prepare persistent storage and restricted clab-discovery password/helpers.')
    print('  Existing password/data retained; first setup asks you to create the password.')
    print('  Rebuild/recreate only the manager; existing lab containers remain in place.')
    print('  Lab operations: ' + ('enabled with default trusted roots' if operations == '1' else 'existing permissions retained'))
    print('  Settings: ' + ('copy ' + str(env_source) if env_source else 'retain current .env or use defaults'))
    print('  Installation-media APT repair: ' + ('enabled with backup' if repair else 'not selected'))
    print('  Check running version/HTTP, then offer Git setup under ' + env['USER'] + '.')
    if not confirm('Proceed with this plan?'):
        raise Cancelled()
    phase('1/4 Administrator access and settings', lambda: command_step(['sudo', '-v'], env))
    copy_env(env_source)
    prereqs = ['sudo', 'bash', str(SOURCE / 'deploy/install-prerequisites.sh'), '--docker', '--containerlab']
    if repair:
        prereqs.append('--repair-install-media')
    phase('2/4 VM prerequisites', lambda: command_step(prereqs, env))
    launch = ['sudo', 'env', 'DOCKER_HOST=unix:///var/run/docker.sock',
              'bash', str(SOURCE / 'deploy/start-manager.sh')]
    if operations == '1':
        launch.append('--enable-operations')
    phase('3/4 Password, helpers, image and manager', lambda: command_step(launch, env))
    phase('4/4 Running manager verification', lambda: verify_manager(env, version))
    print('\nManager installation is ready. Git is a separate setup step under your ordinary account.')
    if menu('Next step', [('1', 'Set up or repair Git now'), ('2', 'Finish; set up Git later')]) == '1':
        git_setup(env)
    print('In VM connection use clab-discovery and the password you created. Verify the host fingerprint.')
    print('After browser setup, run the full installation health report (without sudo):\n  '
          + shlex.join(['bash', str(SOURCE / 'deploy/check-install.sh')]))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Guided manager install/update and Git setup for Ubuntu 24.04.')
    parser.add_argument('--git', action='store_true', help='Open Git setup directly (manager already installed)')
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
                      ('2', 'Git setup / repair only (no rebuild)'), ('3', 'Check running installation'),
                      ('4', 'Exit')])
        if choice == '4':
            return 0
        try:
            if choice == '1':
                install(env, version)
            elif choice == '2':
                git_setup(env)
            else:
                health_report(env)
        except Cancelled:
            print('Returned to menu. Existing data and completed steps are retained.')


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        sys.exit('\nSetup stopped. Existing data is retained; rerun this installer to continue.')
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        sys.exit('\nSetup stopped: ' + str(error))
