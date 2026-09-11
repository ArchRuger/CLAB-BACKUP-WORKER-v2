#!/usr/bin/env python3
"""Interactive Git onboarding. All Git and authentication run as the VM user."""
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

SOURCE = Path(__file__).resolve().parent.parent


def ask(prompt, default=''):
    answer = input(prompt + (f' [{default}]' if default else '') + ': ').strip()
    return answer or default


def confirm(prompt):
    return ask(prompt + ' (y/N)').lower() in ('y', 'yes')


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
            or url.query or url.fragment or any(ord(c) <= 32 for c in value)
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
            return https_url(ask('HTTPS clone URL (Code > HTTPS on GitHub)'))
        except ValueError as error:
            print(str(error))


def install_package(package, env):
    if run(['sudo', 'apt-get', 'update'], env, interactive=True, check=False).returncode:
        raise ValueError('APT package-list update failed; the package was not installed. '
                         'If the output mentions file:/cdrom or cdrom: and a missing Release file, '
                         'disable only the obsolete installation-media entry in /etc/apt/sources.list '
                         'or /etc/apt/sources.list.d/ (see GIT-SETUP.md, Package installation recovery). '
                         'Keep Ubuntu/Docker network sources and signature checks enabled. '
                         'Otherwise resolve the APT or sudo error shown above. '
                         'Run sudo apt-get update successfully, then rerun bash deploy/setup-git.sh.')
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


def prepare_checkout(path, url, env):
    path = checkout_path(str(path))
    if (path / '.git').is_dir():
        return False  # Registration validates ownership, root, branch and remotes.
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError('This path contains files but is not a normal Git checkout. Choose another path; nothing was overwritten.')
    if not url:
        raise ValueError('This directory has no Git checkout. Choose Clone in the setup wizard.')
    https_url(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    result = run(['git', 'clone', '--', url, str(path)], env, check=False)
    if result.returncode:
        raise ValueError('Clone failed. Check the HTTPS URL, repository access and directory ownership. Setup left existing files in place.')
    return True


def identity(path, env):
    for key, prompt in (('user.name', 'Commit author name'), ('user.email', 'Commit author email (GitHub noreply email is also valid)')):
        current = run(['git', 'config', '--get', key], env, path, check=False).stdout.strip()
        if not current:
            value = ask(prompt)
            if not value or any(ord(c) < 32 for c in value):
                raise ValueError('Enter a nonempty commit identity. Rerun setup to continue.')
            run(['git', 'config', '--local', key, value], env, path)
    for role in ('GIT_AUTHOR_IDENT', 'GIT_COMMITTER_IDENT'):
        if run(['git', 'var', role], env, path, check=False).returncode:
            raise ValueError('Git author/committer identity is invalid. Set repository-local user.name and user.email, then rerun.')


def github_login(env):
    if not Path('/usr/bin/gh').exists():
        if not confirm('Install GitHub CLI with sudo apt-get?'):
            raise ValueError('Install gh as a VM administrator, then rerun setup as the repository owner.')
        install_package('gh', env)
    if run(['gh', 'auth', 'status', '--hostname', 'github.com'], env, check=False).returncode:
        print('\nGitHub login belongs to this Linux account. Use your GitHub account with write access.')
        print('Copy the device code below, press Enter, then open the displayed URL in your workstation browser.')
        print('A missing VM browser is normal. Keep this terminal running; do not press Ctrl+C.')
        run(['gh', 'auth', 'login', '--hostname', 'github.com', '--git-protocol', 'https', '--web'], env, interactive=True)
    run(['gh', 'auth', 'setup-git', '--hostname', 'github.com'], env)
    # Show account selection, not auth status (which can include token details).
    login = run(['gh', 'api', 'user', '--jq', '.login'], env).stdout.strip()
    print('GitHub account: ' + login)


def main():
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
    print('No additional Linux user is required. Sudo is used only for packages and helper registration.\n')
    if not shutil.which('git', path=env['PATH']):
        if not confirm('Install Git with sudo apt-get?'):
            raise ValueError('Install git as a VM administrator, then rerun.')
        install_package('git', env)
    mode = ask('Clone a repository or use an existing checkout? Enter clone/existing', 'clone').lower()
    if mode not in ('clone', 'existing'):
        raise ValueError('Choose clone or existing.')
    url = ''
    if mode == 'clone':
        print('First create your repository on GitHub with a README (an initial commit). A private repository is suitable for lab configs.')
        url = ask_clone_url()
        name = urlsplit(url).path.rstrip('/').split('/')[-1].removesuffix('.git')
        print('Checkout directory is the local repository on this VM, where lab configurations will be saved.')
        path = checkout_path(ask('Checkout directory', str(Path(account.pw_dir) / 'labs' / name)))
    else:
        path = checkout_path(ask('Existing checkout directory'))
        prepare_checkout(path, '', env)
        url = https_url(run(['git', 'remote', 'get-url', '--push', 'origin'], env, path).stdout.strip())
    if urlsplit(url).hostname == 'github.com':
        github_login(env)
    else:
        print('For this HTTPS host, configure a persistent credential helper as this Linux account before continuing.')
        if not confirm('Is HTTPS Git authentication already configured?'):
            raise ValueError('Complete your provider login, then rerun setup.')
    prepare_checkout(path, url, env)
    # Never silently reuse a different repository in the suggested directory.
    actual = run(['git', 'remote', 'get-url', '--push', 'origin'], env, path).stdout.strip()
    if actual != url:
        raise ValueError('This checkout has a different origin URL. Rerun with Existing, or choose another clone directory.')
    if run(['git', 'rev-parse', '--verify', 'HEAD'], env, path, check=False).returncode:
        raise ValueError('This repository has no initial commit. Add a README and publish it on GitHub, then clone into a new directory or update this checkout yourself. Setup does not create or push commits.')
    identity(path, env)
    print('\nChecking the checkout with the same environment used by unattended manager saves...')
    print('Registration checks the branch, clean managed files, commit identity, remote sync and a push dry run.')
    if urlsplit(url).hostname == 'github.com':
        slug = urlsplit(url).path.strip('/').removesuffix('.git')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', slug):
            raise ValueError('Use a normal GitHub OWNER/REPOSITORY clone URL.')
        permission = run(['gh', 'api', 'repos/' + slug, '--jq', '.permissions.push'], env).stdout.strip()
        if permission != 'true':
            raise ValueError('The active GitHub account does not have repository write permission. Fix access or use gh auth switch --hostname github.com, then rerun.')
    print(f'\nRegister Linux owner {account.pw_name}\nCheckout: {path}\nRemote: {url}')
    if not confirm('Register this checkout with the manager?'):
        print('Checkout and login retained. No registration was changed.')
        return
    # Only this installation step becomes root; setup-git drops back to the owner
    # before inspecting Git config, hooks, credentials or repository contents.
    registration = ['sudo', 'bash', str(SOURCE / 'deploy/setup-git.sh'), '--owner', account.pw_name,
                    '--repo', str(path)]
    result = run(registration, env, interactive=True, check=False)
    if result.returncode:
        print('If this owner is not an administrator, have the VM administrator run:\n' + shlex.join(registration))
        raise ValueError('Registration did not complete. Resolve the error above; checkout and login are retained.')
    print('\nReady. In the manager: open your lab > More > Git repository.')
    print('Select this checkout and devices, review the destination, then Save progress.')
    print('Save progress commits and pushes automatically. No separate Commit button is needed.')
    print('If a push fails, reopen that save and Retry; do not create a new capture or manually commit its staged files.')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        sys.exit('\nSetup stopped: ' + str(error))
    except (KeyboardInterrupt, EOFError):
        sys.exit('\nSetup cancelled. Existing files and login are retained; rerun to continue.')
