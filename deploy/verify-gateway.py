#!/usr/bin/env python3
"""Verify installed helpers through the restricted account before recreation.

These local requests exercise the gateway and effective sudo rules. They do not
test the SSH password or deploy a lab, and no helper response content is printed.
"""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading


GATEWAY = '/usr/local/sbin/clab-manager-gateway'
ACCOUNT = 'clab-discovery'
REQUESTS = {
    'discovery': ('sudo -n /usr/local/sbin/clab-manager-inspect', b'', 16 * 1024 * 1024),
    'operations': ('clab-manager-operations', b'{"mode":"capabilities"}\n', 1024 * 1024),
    'git': ('clab-manager-git', b'{"mode":"list"}\n', 24 * 1024 * 1024),
}
REPAIR = {
    'discovery': 'setup-discovery.sh',
    'operations': 'setup-operations.sh',
    'git': 'setup-git.sh --refresh',
}


def gateway_command(kind):
    command = REQUESTS[kind][0]
    return ['/usr/sbin/runuser', '--user', ACCOUNT, '--', '/usr/bin/env', '-i',
            'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
            'HOME=/home/clab-discovery', 'USER=' + ACCOUNT, 'LOGNAME=' + ACCOUNT,
            'LANG=C.UTF-8', 'SSH_ORIGINAL_COMMAND=' + command, GATEWAY]


def stop_request(process):
    try:
        os.killpg(process.pid, getattr(signal, 'SIGKILL', 9))
    except ProcessLookupError:
        pass


def run_request(kind):
    _, request, limit = REQUESTS[kind]
    output, errors = bytearray(), bytearray()
    oversized = threading.Event()
    read_failed = threading.Event()
    # Bound both pipes while reading. No inventory/config data is written to
    # disk, and an oversized response terminates the whole request immediately.
    with subprocess.Popen(gateway_command(kind), stdin=subprocess.PIPE, cwd='/',
                          env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LANG': 'C.UTF-8'},
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
                          start_new_session=True) as process:
        def read(stream, target, maximum):
            try:
                while True:
                    chunk = stream.read(min(65536, maximum + 1 - len(target)))
                    if not chunk:
                        return
                    target.extend(chunk)
                    if len(target) > maximum:
                        oversized.set()
                        stop_request(process)
                        return
            except (OSError, ValueError):
                read_failed.set()
                stop_request(process)
                return
        readers = [threading.Thread(target=read, args=(process.stdout, output, limit), daemon=True),
                   threading.Thread(target=read, args=(process.stderr, errors, 65536), daemon=True)]
        for reader in readers:
            reader.start()
        try:
            try:
                process.stdin.write(request)
            except BrokenPipeError:
                pass
            finally:
                try:
                    process.stdin.close()
                except BrokenPipeError:
                    pass
            process.wait(timeout=180)
        except subprocess.TimeoutExpired as error:
            raise ValueError(f'{kind.capitalize()} gateway request timed out. Inspect its helper and Docker service.') from error
        finally:
            # Also end descendants left behind when runuser exits early.
            stop_request(process)
            process.wait(timeout=5)
            for reader in readers:
                reader.join(timeout=5)
        # Never accept a valid-looking prefix if a pipe failed or never reached
        # EOF. Unbuffered pipes also keep context cleanup from waiting on a
        # BufferedReader lock held by an unfinished reader.
        if any(reader.is_alive() for reader in readers):
            raise ValueError(f'{kind.capitalize()} gateway response did not close after the request ended.')
        if oversized.is_set():
            raise ValueError(f'{kind.capitalize()} helper response exceeded its size limit.')
        if read_failed.is_set():
            raise ValueError(f'{kind.capitalize()} gateway response could not be read completely.')
        if process.returncode:
            detail = bytes(errors[:8192]).lower()
            if any(marker in detail for marker in (b'a password is required', b'not allowed', b'not in the sudoers')):
                raise ValueError(f'{kind.capitalize()} gateway cannot use its passwordless sudo permission.')
            raise ValueError(f'{kind.capitalize()} gateway/helper failed while running as {ACCOUNT}.')
        return bytes(output)


def verify_response(kind, raw, version):
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise ValueError(f'{kind.capitalize()} gateway returned invalid JSON.') from error
    if not isinstance(data, dict) or 'error' in data:
        raise ValueError(f'{kind.capitalize()} gateway returned an unsuccessful response.')
    if kind == 'discovery':
        if (data.get('protocol') != 'clab-manager-files-v1' or data.get('helper_version') != version
                or not isinstance(data.get('inspect'), (dict, list)) or not isinstance(data.get('sources'), dict)):
            raise ValueError('Discovery gateway protocol/version/inventory verification failed.')
        return
    result = data.get('result')
    protocol = 'clab-manager-operations-v1' if kind == 'operations' else 'clab-manager-git-v1'
    if not isinstance(result, dict) or result.get('protocol') != protocol or result.get('version') != version:
        raise ValueError(f'{kind.capitalize()} gateway protocol/version verification failed.')
    if kind == 'git':
        if not isinstance(result.get('repositories'), list):
            raise ValueError('Git gateway returned an invalid repository list.')
    else:
        actions = result.get('actions')
        for name in ('deploy', 'destroy', 'inspect'):
            capability = actions.get(name) if isinstance(actions, dict) else None
            if not isinstance(capability, dict) or capability.get('available') is not True:
                raise ValueError(f'Operations gateway cannot expose containerlab {name}; check the installed binary and helper configuration.')


def verify_gateways(version, kinds, runner=run_request):
    for kind in kinds:
        try:
            verify_response(kind, runner(kind), version)
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            # Errors here are controlled metadata; never print raw JSON/stderr.
            detail = str(error) if isinstance(error, ValueError) else 'The gateway command could not run.'
            raise ValueError(detail + f' Run sudo bash deploy/{REPAIR[kind]} from this source folder, '
                             'then retry. Manager has not been recreated.') from error
        print(f'Verified {kind} through {ACCOUNT}, the gateway and passwordless sudo ({version}).')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('version')
    parser.add_argument('--operations', action='store_true')
    parser.add_argument('--git', action='store_true')
    args = parser.parse_args(argv)
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise ValueError('Run this local gateway preflight on the VM with sudo.')
    if not re.fullmatch(r'\d+\.\d+\.\d+', args.version):
        raise ValueError('Supply the numeric source release version.')
    if not Path('/usr/sbin/runuser').is_file():
        raise ValueError('Install Ubuntu util-linux (runuser) before verifying the restricted gateway.')
    kinds = ['discovery']
    if args.operations:
        kinds.append('operations')
    if args.git:
        kinds.append('git')
    verify_gateways(args.version, kinds)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as error:
        sys.exit(str(error))
