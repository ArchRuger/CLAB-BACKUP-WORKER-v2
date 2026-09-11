#!/usr/bin/env python3
"""Read-only clock preflight and streamed APT update with specific recovery hints.

APT remains the authority for repository validity. No clock, NTP configuration,
repository, or authentication policy is changed by this helper.
"""
from datetime import datetime, timezone
import os
import re
import subprocess
import sys
import time


def command_env():
    return dict(os.environ, LC_ALL='C.UTF-8')


def read_clock(timeout=3):
    try:
        result = subprocess.run(
            ['timedatectl', 'show', '--property=CanNTP', '--property=NTP',
             '--property=NTPSynchronized'],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            timeout=timeout, env=command_env(), stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if result.returncode:
        return {}
    return {key: value for line in result.stdout.splitlines()
            for key, sep, value in [line.partition('=')]
            if sep and key in ('CanNTP', 'NTP', 'NTPSynchronized') and value in ('yes', 'no')}


def utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def check_clock(wait_seconds=30):
    print('VM clock: ' + utc_now(), flush=True)
    status = read_clock()
    print('Network time active: ' + status.get('NTP', 'unknown') +
          '; clock synchronized: ' + status.get('NTPSynchronized', 'unknown'), flush=True)
    if status.get('NTP') == 'yes' and status.get('NTPSynchronized') == 'no':
        print(f'Waiting up to {wait_seconds:g}s for the already active time service...', flush=True)
        deadline = time.monotonic() + max(0, wait_seconds)
        while status.get('NTP') == 'yes' and status.get('NTPSynchronized') == 'no':
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(2, remaining))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            status = read_clock(timeout=min(3, remaining))
    if status.get('NTPSynchronized') == 'yes':
        print('Clock synchronization reported; VM clock: ' + utc_now(), flush=True)
    else:
        print('Clock synchronization is not confirmed. Compare UTC with a reliable clock. '
              'Continuing with APT date checks; an unsynchronized flag alone does not prove a wrong clock.',
              flush=True)


def classify_error(line):
    text = line.lower()
    if not re.match(r'^[ew]:\s', text):
        return None
    if 'release file' in text:
        if 'not valid yet' in text:
            return 'future'
        if 'expired' in text:
            return 'expired'
    if re.search(r'''(?:file:/+cdrom(?=[/'"\s]|$)|cdrom:)''', text) and 'release file' in text:
        return 'media'
    return None


def print_recovery(kinds):
    if 'future' in kinds:
        print('\nAPT metadata is dated ahead of the VM clock (Release file is not valid yet). '
              'The VM clock may be behind; compare its UTC time with a reliable source.')
    if 'expired' in kinds:
        print('\nAPT metadata has expired. The VM clock may be ahead, or the mirror/cache may be stale. '
              'Verify UTC before changing anything; if UTC is correct, check the mirror/cache.')
    if kinds & {'future', 'expired'}:
        print('In another VM terminal run:\n  date -u\n  timedatectl status\n'
              'If this VM should use network time, enable its installed provider:\n'
              '  sudo timedatectl set-ntp true\n'
              'Wait for synchronization and verify UTC. An active service alone does not prove it has synced.\n'
              'For systemd-timesyncd: timedatectl timesync-status\n'
              'For chrony: chronyc tracking\n'
              'If time stays wrong, check the configured time server, DNS and NTP network access. '
              'If UTC is correct but metadata is still future-dated, check the repository/mirror.\n'
              'Changing the timezone does not correct UTC. Keep APT date and signature checks enabled.\n'
              'See FRESH-VM-GUIDE-V2.md, Recovery C, for Proxmox and provider-specific checks.')
    if 'media' in kinds:
        print('\nAn obsolete CD-ROM installation source has no valid Release file. '
              'Return to the installer menu and accept installation-media repair, or follow '
              'FRESH-VM-GUIDE-V2.md, Recovery A. Keep network sources enabled.')
    if not kinds:
        print('\nAPT update failed. Resolve the source, DNS, signature, sudo or package-lock error above. '
              'Clock status alone does not identify this failure.')
    print('After correcting the error, run sudo apt-get update --error-on=any. '
          'When it succeeds, choose Retry this step in the original installer. Completed setup is retained.',
          flush=True)


def update(wait_seconds=30):
    check_clock(wait_seconds)
    kinds = set()
    # Stream the real APT output. Store only classifications, never a log of
    # repository URLs or credentials, and preserve its original exit status.
    with subprocess.Popen(['apt-get', 'update', '--error-on=any'],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, env=command_env()) as process:
        try:
            for line in process.stdout:
                print(line, end='', flush=True)
                kind = classify_error(line)
                if kind:
                    kinds.add(kind)
            code = process.wait()
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
    if code:
        print_recovery(kinds)
    return code


if __name__ == '__main__':
    try:
        sys.exit(update())
    except OSError as error:
        sys.exit('Could not run APT update: ' + str(error))
    except KeyboardInterrupt:
        sys.exit(130)
