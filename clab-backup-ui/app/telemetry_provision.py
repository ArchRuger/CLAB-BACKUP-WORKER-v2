"""Read and adjust one node's telemetry service over an interactive SSH shell.

The driver is deliberately small and prompt-driven: it waits for the NOS prompt,
runs the adapter's show commands, asks the adapter which lines are missing and
applies only those with the NOS's own scoped commit (EOS running-config, XR commit,
Junos ``configure private``). Nothing here saves the whole running configuration.
Device output never leaves this module unscrubbed: callers receive controlled
messages plus the native lines the manager added.
"""
import re
import socket
import time

from .telemetry_adapters import ANSI

PROMPT_TIMEOUT = 25
APPLY_TIMEOUT = 90
LIMIT = 256 * 1024
SHELL_PROMPT = re.compile(r'[%$]\s*$')        # Junos root shell before `cli`
PASSWORD_PROMPT = re.compile(r'(?i)password:\s*$')


class ProvisionError(Exception):
    """A controlled, user-facing reason; never raw device output."""


class Shell:
    def __init__(self, channel, prompt, timeout=PROMPT_TIMEOUT):
        self.channel = channel
        self.prompt = prompt
        self.timeout = timeout
        self.received = 0

    def expect(self, patterns, timeout=None):
        """Read until the last line matches one of the patterns; returns (index, text)."""
        deadline = time.monotonic() + (timeout or self.timeout)
        buffer = ''
        while True:
            try:
                chunk = self.channel.recv(65536)
            except socket.timeout:
                chunk = None
            if chunk == b'':
                raise ProvisionError('The SSH session closed before the NOS answered.')
            if chunk:
                self.received += len(chunk)
                if self.received > LIMIT:
                    raise ProvisionError('The NOS answered with more output than expected; the shell was closed.')
                buffer += chunk.decode('utf-8', 'replace')
                text = ANSI.sub('', buffer).replace('\r', '')
                stripped = text.rstrip()
                last = stripped.rsplit('\n', 1)[-1] if stripped else ''
                for index, pattern in enumerate(patterns):
                    if pattern.search(last):
                        return index, text
            if time.monotonic() > deadline:
                raise ProvisionError('The NOS did not return to its prompt in time.')

    def send(self, line):
        self.channel.sendall((line + '\n').encode())

    def run(self, command, timeout=None):
        """Send one command and return its output without the echo and the prompt."""
        self.send(command)
        _, text = self.expect([self.prompt], timeout)
        lines = text.split('\n')
        while lines and not lines[0].strip():
            lines.pop(0)
        if lines and command.strip() and lines[0].strip().endswith(command.strip()):
            lines.pop(0)
        return '\n'.join(lines[:-1]) if lines else ''


def login(shell, adapter, creds):
    """Reach the operational prompt: EOS enable (with its password), Junos `cli` from a shell."""
    index, text = shell.expect([adapter.prompt, SHELL_PROMPT], PROMPT_TIMEOUT)
    if index == 1:
        if adapter.kind != 'juniper_cjunosevolved':
            raise ProvisionError('The login landed in a shell instead of the NOS CLI.')
        shell.send('cli')
        shell.expect([adapter.prompt], PROMPT_TIMEOUT)
        return
    if adapter.kind == 'arista_ceos':
        last = text.rstrip().rsplit('\n', 1)[-1]
        if last.endswith('>'):
            shell.send('enable')
            index, text = shell.expect([adapter.prompt, PASSWORD_PROMPT], PROMPT_TIMEOUT)
            if index == 1:
                if not creds.get('enable_password'):
                    raise ProvisionError('EOS asks for an enable password; add it to the credential profile.')
                shell.send(creds['enable_password'])
                _, text = shell.expect([adapter.prompt], PROMPT_TIMEOUT)
            if text.rstrip().rsplit('\n', 1)[-1].endswith('>'):
                raise ProvisionError('EOS did not enter enable mode; check the enable password in the credential profile.')


def provision(client, adapter, creds, mode='apply', owned=None):
    """Return a controlled result dict for one node.

    mode: 'check' reads only; 'apply' adds missing lines; 'remove' deletes the given
    manager-owned lines when they are still present.
    """
    channel = client.invoke_shell(term='vt100', width=200, height=1000)
    try:
        channel.settimeout(1.0)
        shell = Shell(channel, adapter.prompt)
        login(shell, adapter, creds)
        for command in adapter.prepare():
            shell.run(command)
        if adapter.kind == 'arista_ceos':
            probe = shell.run('show privilege')
            if 'Current privilege level is 15' not in probe and re.search(r'level is (?:[0-9]|1[0-4])\b', probe):
                raise ProvisionError('EOS session is not in privilege level 15; provide the enable password in the credential profile.')
        outputs = {command: shell.run(command) for command in adapter.show_commands()}
        plan = adapter.plan(outputs)
        result = {'port': plan.port, 'transport': plan.transport, 'vrf': plan.vrf, 'applied': [], 'removed': [],
                  'blockers': plan.blockers, 'missing': list(plan.add), 'message': ''}
        if mode == 'check':
            result['message'] = 'Telemetry service already configured.' if plan.ready else 'Telemetry service needs configuration.'
            return result
        if mode == 'remove':
            lines = [l for l in (owned or []) if l.strip()]
            commands = adapter.remove(lines)
            if not commands or plan.add:
                result['message'] = 'No manager-owned telemetry lines are present on this node.'
                return result
            transcript = ''
            for command in commands:
                transcript += shell.run(command, APPLY_TIMEOUT)
                error = adapter.failed(transcript)
                if error:
                    for step in adapter.abort():
                        try: shell.run(step, PROMPT_TIMEOUT)
                        except ProvisionError: break
                    raise ProvisionError(error)
            result['removed'] = lines
            result['message'] = 'Removed the telemetry lines the manager had added.'
            return result
        if plan.blockers:
            raise ProvisionError(' '.join(plan.blockers))
        if not plan.add:
            result['message'] = 'Telemetry service already configured; nothing changed.'
            return result
        transcript = ''
        for command in adapter.apply(plan):
            transcript += shell.run(command, APPLY_TIMEOUT)
            error = adapter.failed(transcript)
            if error:
                for step in adapter.abort():
                    try: shell.run(step, PROMPT_TIMEOUT)
                    except ProvisionError: break
                raise ProvisionError(error)
        verify = {command: shell.run(command) for command in adapter.show_commands()}
        after = adapter.plan(verify)
        if not after.ready:
            raise ProvisionError('The telemetry lines were sent but the running configuration does not show them; check the NOS session by hand.')
        result.update(port=after.port, transport=after.transport, vrf=after.vrf, applied=list(plan.add), missing=[],
                      message=f'Added {len(plan.add)} telemetry configuration line(s).')
        return result
    finally:
        try: channel.close()
        except Exception: pass
