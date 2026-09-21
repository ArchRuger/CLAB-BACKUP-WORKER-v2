"""The prompt-driven SSH shell every restore driver shares.

A restore driver (:mod:`restore_junos`, :mod:`restore_eos`, :mod:`restore_iosxr`) talks to the
node's interactive CLI over a paramiko channel, or over any object with ``recv``/``sendall`` in the
tests. This module holds what is identical for all of them: the controlled error type, ANSI
stripping, the bounded read-until-prompt loop and the echo/prompt trimming of one command's output.
What a prompt looks like, and every command, belongs to the driver.

Device output never leaves a driver unscrubbed: callers get controlled messages and a review diff
that they redact before display or logging.
"""
import re
import socket
import time

ANSI = re.compile(r'(\x1b\[[0-9;?]*[A-Za-z])|[\x07\x00]')
PROMPT_TIMEOUT = 30
LIMIT = 4 * 1024 * 1024


class RestoreError(Exception):
    """A controlled, user-facing reason; never raw device configuration."""


class SessionLost(RestoreError):
    """The session closed, stalled or overflowed: what the node did with the last command is unknown.

    A driver's own refusals (validation, load, check or commit rejected and the candidate discarded)
    are plain RestoreError and mean "nothing changed". This one does not, so the service reads the
    node back before it says anything about the configuration.
    """


def clean(text):
    return ANSI.sub('', text).replace('\r', '')


class Shell:
    """Prompt-driven wrapper over a paramiko channel (or any recv/sendall object)."""

    any_prompt = None  # a driver's subclass sets the pattern that ends one command's output

    def __init__(self, channel, timeout=PROMPT_TIMEOUT):
        self.channel = channel
        self.timeout = timeout
        self.received = 0

    def expect(self, patterns, timeout=None):
        deadline = time.monotonic() + (timeout or self.timeout)
        buffer = ''
        while True:
            try:
                chunk = self.channel.recv(65536)
            except socket.timeout:
                chunk = None
            if chunk == b'':
                raise SessionLost('The SSH session to the node closed before it answered.')
            if chunk:
                self.received += len(chunk)
                if self.received > LIMIT:
                    raise SessionLost('The node returned more output than expected; the session was closed.')
                buffer += chunk.decode('utf-8', 'replace')
                text = clean(buffer)
                last = text.rstrip().rsplit('\n', 1)[-1] if text.strip() else ''
                for index, pattern in enumerate(patterns):
                    if pattern.search(last):
                        return index, text
            if time.monotonic() > deadline:
                raise SessionLost('The node did not return to its prompt in time.')

    def send(self, line):
        self.channel.sendall((line + '\n').encode())

    def send_raw(self, data):
        self.channel.sendall(data)

    def run(self, command, timeout=None):
        """Send one command; return its output without the echo or the trailing prompt."""
        self.send(command)
        _, text = self.expect([self.any_prompt], timeout)
        lines = clean(text).split('\n')
        while lines and not lines[0].strip():
            lines.pop(0)
        if lines and command.strip() and lines[0].strip().endswith(command.strip()):
            lines.pop(0)
        return '\n'.join(lines[:-1]) if lines else ''


def open_shell(client, shell_class):
    channel = client.invoke_shell(term='vt100', width=240, height=100000)
    channel.settimeout(1.0)
    return channel, shell_class(channel)


def close_channel(channel):
    try:
        channel.close()
    except Exception:
        pass
