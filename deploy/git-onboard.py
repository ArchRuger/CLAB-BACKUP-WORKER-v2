#!/usr/bin/env python3
"""Interactive Git onboarding. All Git and authentication run as the VM user."""
import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

SOURCE = Path(__file__).resolve().parent.parent


class SetupCancelled(Exception):
    """A deliberate stop; callers can retain a successfully installed manager."""


class PackageSourceError(ValueError):
    """APT did not reach package installation."""


def ask(prompt, default=''):
    answer = input(prompt + (f' [{default}]' if default else '') + ': ').strip()
    return answer or default


def confirm(prompt):
    return ask(prompt + ' (y/N)').lower() in ('y', 'yes')


def menu(prompt, options, default=None):
    """Numbered input works over SSH, serial consoles and terminals without curses."""
    print('\n' + prompt)
    for number, (key, label) in enumerate(options, 1):
        print(f'  {number}. {label}')
    print('  q. Cancel and keep completed work')
    default_number = next((str(i) for i, (key, _) in enumerate(options, 1) if key == default), '')
    while True:
        answer = ask('Choose a number', default_number).lower()
        if answer in ('q', 'quit', 'cancel'):
            raise SetupCancelled()
        for number, (key, _) in enumerate(options, 1):
            if answer in (str(number), key):
                return key
        print('Choose one of the listed numbers, or q to cancel.')


def step(number, title, action, env=None, url=''):
    print(f'\n[{number}/6] {title}')
    while True:
        try:
            result = action()
            print('  OK: ' + title)
            return result
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            print('\n' + str(error))
            print('Completed files and login are retained. Fix the issue in another terminal, then retry here.')
            options = [('retry', 'Retry this step')]
            if env is not None and urlsplit(url).hostname == 'github.com':
                options.append(('login', 'Sign in to GitHub again, then retry'))
            if isinstance(error, PackageSourceError) and env is not None:
                options.append(('repair', 'Review and repair obsolete installation-media APT sources'))
            choice = menu('How would you like to continue?', options, 'retry')
            if choice == 'login':
                # Login failure remains recoverable from the same phase menu.
                try:
                    github_login(env, force=True)
                except (ValueError, OSError, subprocess.SubprocessError) as login_error:
                    print(str(login_error))
            elif choice == 'repair':
                print('This repairs only obsolete CD-ROM installation sources and backs up edited files.')
                print('Network mirrors and repository signature checks remain enabled.')
                if confirm('Run installation-media source repair with sudo?'):
                    try:
                        run(['sudo', 'python3', str(SOURCE / 'deploy/apt_sources.py'), '--repair'], env, interactive=True)
                    except (ValueError, OSError, subprocess.SubprocessError) as repair_error:
                        print(str(repair_error))


def service_env(owner, home):
    # Match the host helper: no shell-only GH_TOKEN, alternate config or agent.
    return {'PATH': '/usr/local/bin:/usr/bin:/bin', 'HOME': str(home), 'USER': owner,
            'LOGNAME': owner, 'LANG': 'C.UTF-8', 'GIT_TERMINAL_PROMPT': '0',
            'GCM_INTERACTIVE': 'never', 'GIT_PAGER': 'cat', 'GIT_LITERAL_PATHSPECS': '1'}


def run(args, env, cwd=None, interactive=False, check=True):
    result = subprocess.run(args, cwd=cwd, env=env,
                            stdin=None if interactive else subprocess.DEVNULL,
                            stdout=None if interactive else subprocess.PIPE,
                            stderr=None if interactive else subprocess.DEVNULL,
                            text=True, timeout=None if interactive else 120)
    if check and result.returncode:
        raise ValueError(f'{args[0]} {args[1]} failed. Check connectivity and the selected account; rerun setup to continue.')
    return result


def https_url(value):
    url = urlsplit(value)
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or url.query or url.fragment or any(ord(c) <= 32 or ord(c) == 127 for c in value)
            or '%' in value or '\\' in value or not url.path.strip('/')):
        raise ValueError('Use an HTTPS clone URL without a username, token, query or fragment.')
    if url.hostname == 'github.com':
        parts = url.path.strip('/').split('/')
        if (len(parts) != 2 or not all(re.fullmatch(r'[A-Za-z0-9_.-]+', part) for part in parts)
                or any(part in ('.', '..') for part in parts)
                or not parts[1].removesuffix('.git')):
            raise ValueError('Use the GitHub repository clone URL: https://github.com/OWNER/REPOSITORY.git. '
                             'Copy Code > HTTPS; do not include /tree/main, /blob/ or other page paths.')
    return value


def ask_clone_url():
    while True:
        try:
            value = ask('HTTPS clone URL (Code > HTTPS on GitHub)')
            suggestion = github_clone_suggestion(value)
            if suggestion:
                print('This is a GitHub branch/file page. Its repository clone URL is:\n  ' + suggestion)
                if confirm('Use this repository clone URL?'):
                    return suggestion
                continue
            return https_url(value)
        except ValueError as error:
            print(str(error))


def github_clone_suggestion(value):
    """Only propose a safe GitHub page conversion; never silently change a remote."""
    try:
        url = urlsplit(value)
        if (url.scheme != 'https' or url.netloc != 'github.com' or url.query or url.fragment
                or any(ord(c) <= 32 or ord(c) == 127 for c in value) or '%' in value or '\\' in value):
            return None
        parts = url.path.strip('/').split('/')
        if len(parts) < 4 or parts[2] not in ('tree', 'blob'):
            return None
        return https_url('https://github.com/' + '/'.join(parts[:2]).removesuffix('.git') + '.git')
    except ValueError:
        return None


def install_package(package, env):
    if run(['sudo', '/usr/bin/python3', str(SOURCE / 'deploy/apt_update.py')], env, interactive=True, check=False).returncode:
        raise PackageSourceError('APT package-list update failed; the package was not installed. '
                         'If the output mentions file:/cdrom or cdrom: and a missing Release file, '
                         'disable only the obsolete installation-media entry in /etc/apt/sources.list '
                         'or /etc/apt/sources.list.d/ (see GIT-SETUP.md, Package installation recovery). '
                         'Keep Ubuntu/Docker network sources and signature checks enabled. '
                         'For Release file is not valid yet or expired, follow the VM clock/mirror recovery above; '
                         'CD-ROM repair does not fix clock errors. Otherwise resolve the APT or sudo error shown above. '
                         'Run sudo apt-get update --error-on=any successfully, then choose Retry this step.')
    if run(['sudo', 'apt-get', 'install', '-y', package], env, interactive=True, check=False).returncode:
        raise ValueError(f'APT could not install {package}. Resolve the package or sudo error above, '
                         f'then run sudo apt-get install -y {package} and rerun bash deploy/setup-git.sh.')


def checkout_path(value):
    path = Path(value).expanduser()
    if not path.is_absolute() or '..' in path.parts or path == Path(path.anchor):
        raise ValueError('Choose an absolute checkout path, for example ~/labs/my-lab.')
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('Choose a checkout path without symbolic links.')
    return path


def validate_checkout_directory(path):
    control = path / '.git'
    if control.is_symlink() or not control.is_dir():
        raise ValueError('Choose a normal checkout with a .git directory; linked worktrees and symbolic links are unsupported.')
    getuid = getattr(os, 'geteuid', None)
    if getuid and (path.stat().st_uid != getuid() or control.stat().st_uid != getuid()):
        raise ValueError('This checkout or .git belongs to a different Linux account. Use its owner or clone into a new folder as this user. Setup does not change ownership.')


def prepare_checkout(path, url, env):
    path = checkout_path(str(path))
    if (path / '.git').is_dir():
        validate_checkout_directory(path)
        return False  # Registration validates ownership, root, branch and remotes.
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError('This path contains files but is not a normal Git checkout. Choose another path; nothing was overwritten.')
    if not url:
        raise ValueError('This directory has no Git checkout. Choose Clone in the setup wizard.')
    https_url(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Cloning keeps the terminal: a large lab-config repository or a slow link
    # must not hit the 120 s non-interactive limit, and Git's own progress and
    # error text stay visible. GIT_TERMINAL_PROMPT=0 still blocks credential prompts.
    result = run(['git', 'clone', '--', url, str(path)], env, interactive=True, check=False)
    if result.returncode:
        raise ValueError('Clone failed. Check the HTTPS URL, repository access and directory ownership. Setup left existing files in place.')
    return True


def identity(path, env):
    print('Commit name/email label your commits; GitHub login does not set them. Settings apply only to this checkout.')
    for key, prompt in (('user.name', 'Commit author name'), ('user.email', 'Commit author email (GitHub noreply email is also valid)')):
        current = run(['git', 'config', '--get', key], env, path, check=False).stdout.strip()
        if not current:
            value = ask_identity(prompt)
            run(['git', 'config', '--local', key, value], env, path)
    while any(run(['git', 'var', role], env, path, check=False).returncode
              for role in ('GIT_AUTHOR_IDENT', 'GIT_COMMITTER_IDENT')):
        print('Git rejected the commit identity. Enter a replacement name and email for this checkout.')
        for key, prompt in (('user.name', 'Commit author name'), ('user.email', 'Commit author email')):
            run(['git', 'config', '--local', key, ask_identity(prompt)], env, path)
    print('Commit identity verified for this checkout.')


def ask_identity(prompt):
    while True:
        value = ask(prompt)
        if value and not any(ord(c) < 32 or ord(c) == 127 for c in value):
            return value
        print('Enter a nonempty value without control characters, or press Ctrl+C to cancel.')


def github_login(env, force=False):
    if not Path('/usr/bin/gh').exists():
        if not confirm('Install GitHub CLI with sudo apt-get?'):
            raise ValueError('Install gh as a VM administrator, then rerun setup as the repository owner.')
        install_package('gh', env)
    if force or run(['gh', 'auth', 'status', '--hostname', 'github.com'], env, check=False).returncode:
        print('\nGitHub login belongs to this Linux account. Use your GitHub account with write access.')
        print('Copy the device code below, press Enter, then open the displayed URL in your workstation browser.')
        print('A missing VM browser is normal. Keep this terminal running; do not press Ctrl+C.')
        run(['gh', 'auth', 'login', '--hostname', 'github.com', '--git-protocol', 'https', '--web'], env, interactive=True)
    run(['gh', 'auth', 'setup-git', '--hostname', 'github.com'], env)
    # Show account selection, not auth status (which can include token details).
    login = run(['gh', 'api', 'user', '--jq', '.login'], env).stdout.strip()
    print('GitHub account: ' + login)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Guided Git setup as the existing VM account.')
    parser.add_argument('--repo', help='Resume guided setup for an existing checkout; no cloning.')
    return parser.parse_args(argv)


def read_registrations(env):
    print('Checking existing manager registrations with sudo so their settings can be preserved.')
    run(['sudo', '-v'], env, interactive=True)
    result = run(['sudo', '-n', 'bash', str(SOURCE / 'deploy/setup-git.sh'), '--list'], env, check=False)
    if result.returncode:
        raise ValueError('Could not read manager registrations. Use a VM administrator account or repair the registry error with your administrator. Setup will not guess or replace existing settings.')
    try:
        if len(result.stdout) > 1024 * 1024:
            raise ValueError()
        payload = json.loads(result.stdout)['result']
        entries = payload['repositories']
        if payload['protocol'] != 'clab-manager-git-v1' or not isinstance(entries, list):
            raise ValueError()
        fields = ('id', 'label', 'owner', 'path', 'remote', 'push_url', 'branch', 'prefix', 'revision')
        if any(not isinstance(entry, dict) or any(not isinstance(entry.get(key), str) for key in fields) for entry in entries):
            raise ValueError()
        return entries
    except (ValueError, KeyError, TypeError):
        raise ValueError('The registration list is invalid. Repair it with your VM administrator; setup will not replace existing settings.') from None


def selected_registration(account, path, registrations):
    matches = [entry for entry in registrations if entry['path'] == str(path)]
    if any(entry['owner'] != account.pw_name for entry in matches):
        raise ValueError('This checkout is registered to another Linux owner. Continue as its registered owner; setup will not reassign it.')
    if not matches:
        return {'remote': 'origin', 'prefix': '', 'label': path.name, 'branch': '', 'push_url': ''}
    if not (path / '.git').is_dir():
        raise ValueError('This path has an existing registration but its checkout is missing. Restore the original checkout including .git, or select a new directory.')
    if len(matches) > 1:
        selected = menu('Select the existing registration to check:', [
            (str(i), entry['label'] + ' — ' + (entry['prefix'] or 'repository root'))
            for i, entry in enumerate(matches, 1)])
        binding = matches[int(selected) - 1]
    else:
        binding = matches[0]
    print('Keeping existing registration: ' + binding['label'])
    print('Remote: ' + binding['remote'] + '; destination: ' + (binding['prefix'] or 'repository root') + '; branch: ' + binding['branch'])
    return binding


def choose_checkout(account, existing, env, registrations=()):
    choices = [('clone', 'Clone a repository from GitHub or another HTTPS host'),
               ('existing', 'Use an existing checkout on this VM')]
    saved_paths = list(dict.fromkeys(entry['path'] for entry in registrations if entry['owner'] == account.pw_name))
    if saved_paths:
        choices.insert(0, ('registered', 'Check or repair an already registered checkout'))
    mode = 'existing' if existing else menu('Where are your lab configurations going?', choices,
                                          'registered' if saved_paths else 'clone')
    if mode == 'registered':
        if len(saved_paths) == 1:
            existing = saved_paths[0]
        else:
            index = menu('Choose your registered checkout:', [(str(i), path) for i, path in enumerate(saved_paths, 1)])
            existing = saved_paths[int(index) - 1]
        mode = 'existing'
    print('Checkout directory = your local lab-config repository, usually under ~/labs/.')
    print('It is separate from the manager source folder: ' + str(SOURCE))
    url = ''
    if mode == 'clone':
        print('First create the repository on GitHub with a README (initial commit). A private repository is suitable for lab configs.')
        url = ask_clone_url()
        name = urlsplit(url).path.rstrip('/').split('/')[-1].removesuffix('.git')
        default = str(Path(account.pw_dir) / 'labs' / name)
    else:
        default = existing or ''
    while True:
        try:
            path = checkout_path(existing or ask('Checkout directory', default))
            if path == SOURCE:
                raise ValueError('This is the manager source directory. Choose the separate lab-config checkout under your home/labs directory.')
            binding = selected_registration(account, path, registrations)
            remote = binding['remote']
            if mode == 'existing':
                prepare_checkout(path, '', env)
                url = https_url(run(['git', 'remote', 'get-url', '--push', remote], env, path).stdout.strip())
            elif path.exists():
                if (path / '.git').is_dir():
                    validate_checkout_directory(path)
                    actual = https_url(run(['git', 'remote', 'get-url', '--push', remote], env, path).stdout.strip())
                    if not same_repository_url(actual, url):
                        raise ValueError('This directory is a different repository. Choose another directory, or cancel and select Existing.')
                    print('Existing checkout found; it will be reused. No clone, reset or overwrite is needed.')
                    url = actual
                elif not path.is_dir() or any(path.iterdir()):
                    raise ValueError('This directory contains files but has no normal Git checkout. Choose another directory; nothing was overwritten.')
            if binding['push_url'] and binding['push_url'] != url:
                raise ValueError('The registered push URL changed. Resolve pending saves and review the existing connection before changing its registration. Setup will not rebind it automatically.')
            return path, url, binding
        except (ValueError, OSError) as error:
            if existing:
                raise
            print(str(error))
            if menu('Choose another checkout directory?', [('path', 'Enter a different directory')], 'path') == 'path':
                default = ''


def same_repository_url(left, right):
    def normalized(value):
        if urlsplit(value).hostname == 'github.com':
            return value.rstrip('/').removesuffix('.git').lower()
        return value
    return normalized(left) == normalized(right)


def check_checkout(path, url, env, binding):
    prepare_checkout(path, url, env)
    actual = https_url(run(['git', 'remote', 'get-url', '--push', binding['remote']], env, path).stdout.strip())
    if not same_repository_url(actual, url):
        raise ValueError('This checkout has a different origin URL. Cancel and select Existing, or choose another clone directory.')
    if run(['git', 'rev-parse', '--verify', 'HEAD'], env, path, check=False).returncode:
        raise ValueError('This repository has no initial commit. Add a README and publish it on GitHub, then update this checkout yourself. Setup does not create or push commits.')
    if binding['branch']:
        branch = run(['git', 'symbolic-ref', '--quiet', '--short', 'HEAD'], env, path).stdout.strip()
        if branch != binding['branch']:
            raise ValueError('The checkout moved from its registered branch. Resolve pending saves and review the connection before changing branches. Setup will not rebind it automatically.')


def check_permission(url, env):
    if urlsplit(url).hostname == 'github.com':
        slug = urlsplit(url).path.strip('/').removesuffix('.git')
        permission = run(['gh', 'api', 'repos/' + slug, '--jq', '.permissions.push'], env).stdout.strip()
        if permission != 'true':
            raise ValueError('The active GitHub account does not have repository write permission. Grant access on GitHub, or choose Sign in again below to use another account.')


def register_checkout(account, path, env, binding):
    if binding.get('id'):
        current = next((entry for entry in read_registrations(env) if entry['id'] == binding['id']), None)
        fields = ('id', 'label', 'owner', 'path', 'remote', 'push_url', 'branch', 'prefix', 'revision')
        if current is None or any(current.get(key) != binding.get(key) for key in fields):
            raise ValueError('The existing registration changed while setup was open. Cancel and resume to review its current settings; setup will not overwrite it.')
        actual = run(['git', 'remote', 'get-url', '--push', binding['remote']], env, path).stdout.strip()
        if actual != binding['push_url']:
            raise ValueError('The checkout push URL changed after review. Restore its registered URL before retrying; setup will not rebind it automatically.')
    if binding['branch']:
        branch = run(['git', 'symbolic-ref', '--quiet', '--short', 'HEAD'], env, path).stdout.strip()
        if branch != binding['branch']:
            raise ValueError('The checkout changed branches after review. Restore its registered branch before retrying; setup will not rebind it automatically.')
    registration = ['sudo', 'bash', str(SOURCE / 'deploy/setup-git.sh'), '--owner', account.pw_name,
                    '--repo', str(path), '--remote', binding['remote'], '--prefix', binding['prefix'], '--label', binding['label']]
    result = run(registration, env, interactive=True, check=False)
    if result.returncode:
        print('If this owner is not an administrator, have the VM administrator run:\n' + shlex.join(registration))
        raise ValueError('Registration did not complete. Resolve the error above; checkout and login are retained.')


def resume_message(path=None):
    command = ['bash', str(SOURCE / 'deploy/setup-git.sh')]
    if path is not None and (path / '.git').is_dir():
        command += ['--guided', '--repo', str(path)]
    print('Resume as the same Linux account, without sudo:\n  ' + shlex.join(command))


def main(argv=None):
    options = parse_args(argv)
    import pwd
    if os.geteuid() == 0:
        raise ValueError('Run bash deploy/setup-git.sh as the ordinary VM account, without sudo.')
    if not sys.stdin.isatty():
        raise ValueError('Guided setup needs an interactive VM terminal. See --help for scripted registration.')
    account = pwd.getpwuid(os.geteuid())
    if account.pw_name == 'clab-discovery':
        raise ValueError('Use your ordinary VM account, not the restricted clab-discovery account.')
    if not Path('/etc/ssh/clab-manager-password.conf').is_file():
        raise ValueError('Start the manager with sudo bash deploy/start-manager.sh first, then rerun Git setup.')
    env = service_env(account.pw_name, account.pw_dir)
    print(f'\nGit setup for Linux account: {account.pw_name}\nPersistent home: {account.pw_dir}')
    print('This is the repository owner. It does not need to match your GitHub username.')
    print('No additional Linux user is required. Sudo is used for packages and reading/updating manager registrations.\n')
    print('Manager source: ' + str(SOURCE))
    print('The lab-config checkout is a separate folder. A clean git status does not verify commit identity or push access.')
    print('Use numbered menus and Enter. Press Ctrl+C at any prompt, or q in a menu, to stop safely.')
    path = None
    try:
        def ensure_git():
            if not shutil.which('git', path=env['PATH']):
                if not confirm('Install Git with sudo apt-get?'):
                    raise SetupCancelled()
                install_package('git', env)
            return read_registrations(env)
        registrations = step(1, 'Check Git, Linux account and existing registrations', ensure_git, env)
        path, url, binding = step(2, 'Choose the local lab-config repository',
                                  lambda: choose_checkout(account, options.repo, env, registrations))
        def authenticate():
            if urlsplit(url).hostname == 'github.com':
                github_login(env)
            else:
                print('Configure a persistent HTTPS credential helper as this Linux account before continuing.')
                if not confirm('Is HTTPS Git authentication already configured?'):
                    raise SetupCancelled()
        step(3, 'Connect your GitHub / HTTPS account', authenticate, env, url)
        step(4, 'Clone or validate the existing checkout', lambda: check_checkout(path, url, env, binding), env, url)
        step(5, 'Verify commit identity and write permission',
             lambda: (identity(path, env), check_permission(url, env)), env, url)
        print(f'\nReview registration\nLinux owner: {account.pw_name}\nCheckout: {path}\nRemote: {url}')
        print('Remote name: ' + binding['remote'] + '; configs: ' + (binding['prefix'] or 'repository root'))
        print('Existing registration settings are retained. New checkouts use the current branch.')
        print('Registration checks clean managed files, identity, remote sync and a push dry run.')
        print('Setup does not create or push commits. Server branch rules may still reject future saves.')
        if not confirm('Register this checkout with the manager?'):
            raise SetupCancelled()
        step(6, 'Register the checkout with the manager', lambda: register_checkout(account, path, env, binding), env, url)
    except (SetupCancelled, KeyboardInterrupt, EOFError):
        print('\nGit setup cancelled. Completed files and login are retained; readiness has not been confirmed.')
        resume_message(path)
        return 2
    print('\nReady. In the manager: open your lab > More > Git repository.')
    print('Select this checkout and devices, review the destination, then Save progress.')
    print('Save progress commits and pushes automatically. No separate Commit button is needed.')
    print('If a push fails, reopen that save and Retry; do not create a new capture or manually commit its staged files.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        sys.exit('\nSetup stopped: ' + str(error))
    except (KeyboardInterrupt, EOFError):
        sys.exit('\nSetup cancelled. Existing files and login are retained; rerun to continue.')
