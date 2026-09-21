#!/usr/bin/env python3
"""Run CLI lines on one restore-square node over an interactive SSH shell and keep the transcript.

Independent of the manager's drivers on purpose: acceptance checks read a device back through this
tool, never through the code under test. Raw transcripts may hold configuration and password hashes,
so they go to ~/research/multi-platform-restore/raw/ (outside Git); commit only sanitized extracts.

    nodecli.py ceos 'show version' 'show running-config'
    nodecli.py xrv9k --file lines.txt --timeout 120
    nodecli.py vjunos-switch --ctrl-d-after 3 'configure' 'load override terminal' '<text>' ...

Run it with the application's virtual environment (it needs paramiko):
    clab-backup-ui/.venv/bin/python docs/multi-platform-restore/tools/nodecli.py ...
Logins are the kinds' published containerlab defaults; override with NODECLI_USER / NODECLI_PASSWORD.
"""
import argparse
import os
import pathlib
import re
import sys
import time

import paramiko

NODES = {
    'ceos': ('172.20.20.101', 'admin', 'admin', 'eos'),
    'cjunosevolved': ('172.20.20.102', 'admin', 'admin@123', 'junos'),
    'vjunos-switch': ('172.20.20.103', 'admin', 'admin@123', 'junos'),
    'xrv9k': ('172.20.20.104', 'clab', 'clab@123', 'iosxr'),
}
PROMPT = {
    'eos': re.compile(r'^[\w.\-]+(?:\([\w.\-+/:]+\))?[>#]\s*$'),
    'junos': re.compile(r'^(?:[\w.\-]+@[\w.\-]+[>#%]|\[?[\w.\-]+@[\w.\-]+[^\n]*\]?[#$])\s*$'),
    'iosxr': re.compile(r'^RP/\d+/\w+/CPU\d+:[\w.\-]+(?:\([\w.\-]+\))?#\s*$'),
}
SETUP = {
    'eos': ['enable', 'terminal length 0', 'terminal width 500'],   # 32767 made cEOS close the product driver's channel
    'junos': ['set cli screen-length 0', 'set cli screen-width 0', 'set cli complete-on-space off'],
    'iosxr': ['terminal length 0', 'terminal width 512'],
}
ANSI = re.compile(r'(\x1b\[[0-9;?]*[A-Za-z])|[\x07\x00]')
RAW = pathlib.Path.home() / 'research' / 'multi-platform-restore' / 'raw'


class Session:
    def __init__(self, node, timeout=60):
        ip, user, password, self.family = NODES[node]
        self.node, self.timeout = node, timeout
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(ip, username=os.environ.get('NODECLI_USER', user),
                            password=os.environ.get('NODECLI_PASSWORD', password), timeout=10,
                            banner_timeout=15, auth_timeout=15, look_for_keys=False, allow_agent=False)
        self.channel = self.client.invoke_shell(term='vt100', width=500, height=10000)
        self.channel.settimeout(1.0)
        self.log = []
        self.read()
        for line in SETUP[self.family]:
            self.run(line)

    def read(self, timeout=None):
        deadline, buffer = time.monotonic() + (timeout or self.timeout), ''
        while time.monotonic() < deadline:
            try:
                chunk = self.channel.recv(65536)
            except Exception:
                chunk = None
            if chunk == b'':
                break
            if chunk:
                buffer += chunk.decode('utf-8', 'replace')
                text = ANSI.sub('', buffer).replace('\r', '')
                last = text.rstrip().rsplit('\n', 1)[-1] if text.strip() else ''
                if PROMPT[self.family].match(last.strip()):
                    break
        text = ANSI.sub('', buffer).replace('\r', '')
        self.log.append(text)
        return text

    def run(self, line, timeout=None):
        self.channel.sendall((line + '\n').encode())
        return self.read(timeout)

    def raw(self, data):
        self.channel.sendall(data)

    def close(self):
        self.client.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('node', choices=sorted(NODES))
    parser.add_argument('lines', nargs='*')
    parser.add_argument('--file', help='read CLI lines from this file (one per line)')
    parser.add_argument('--timeout', type=int, default=60)
    parser.add_argument('--ctrl-d-after', type=int, default=0, metavar='N',
                        help='send Ctrl-D after the Nth line (ends "load ... terminal")')
    parser.add_argument('--tag', default='adhoc', help='transcript file label')
    args = parser.parse_intermixed_args()
    lines = list(args.lines)
    if args.file:
        lines += pathlib.Path(args.file).read_text().splitlines()
    session = Session(args.node, args.timeout)
    try:
        for number, line in enumerate(lines, 1):
            sys.stdout.write(session.run(line))
            if number == args.ctrl_d_after:
                session.raw(b'\x04')
                sys.stdout.write(session.read())
        print()
    finally:
        session.close()
        RAW.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime('%Y%m%dT%H%M%S')
        (RAW / f'{stamp}-{args.node}-{args.tag}.log').write_text('\n'.join(session.log))


if __name__ == '__main__':
    main()
