"""The pure half of the serial console: a minimal telnet codec and the gate's two status-line readers.

qemu's telnet chardev (vrnetlab's TCP 5000) negotiates WILL ECHO, WILL SGA, WILL BINARY, DO BINARY at once and then
relays the guest's serial port. The codec strips the server's IAC sequences from the output (xterm must never see
them), answers each option once and doubles 0xFF on input. Nothing here stores, logs or redacts console bytes: the
output is raw for a terminal, exactly as the SSH channel's bytes are (docs/parity-campaign/C04-DESIGN.md §2.4).
"""
import re

from .discovery import uptime_seconds

IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240
BINARY, ECHO, SGA = 0, 1, 3
ACCEPT_WILL = {ECHO, SGA, BINARY}      # the server may: answered DO
ACCEPT_DO = {BINARY}                   # we will: answered WILL; every other request is refused (DONT / WONT)
NEGOTIATIONS = {WILL, WONT, DO, DONT}


class TelnetCodec:
    """Strips the server's IAC sequences from output and answers its options; carries state across chunks."""

    def __init__(self):
        self.state = 'data'        # 'data' | 'iac' | 'option' | 'sb' | 'sb_iac'
        self.command = 0           # the pending WILL/WONT/DO/DONT while in 'option'
        self.answered = set()      # (command, option) pairs already replied to: a repeat is not answered again

    def feed(self, data):
        """(bytes for the terminal, replies for the device) for one chunk; a chunk may end inside a sequence."""
        output = bytearray(); replies = bytearray()
        for byte in data:
            if self.state == 'data':
                if byte == IAC: self.state = 'iac'
                else: output.append(byte)
            elif self.state == 'iac':
                if byte == IAC: output.append(IAC); self.state = 'data'
                elif byte in NEGOTIATIONS: self.command = byte; self.state = 'option'
                elif byte == SB: self.state = 'sb'
                else: self.state = 'data'                     # NOP, GA, AYT, …: two bytes dropped
            elif self.state == 'option':
                replies += self.reply(self.command, byte); self.state = 'data'
            elif self.state == 'sb':
                if byte == IAC: self.state = 'sb_iac'
            elif self.state == 'sb_iac':
                self.state = 'data' if byte == SE else 'sb'   # IAC IAC inside a subnegotiation is an escaped byte
        return bytes(output), bytes(replies)

    def reply(self, command, option):
        if command == WILL: answer = DO if option in ACCEPT_WILL else DONT
        elif command == DO: answer = WILL if option in ACCEPT_DO else WONT
        else: return b''                                      # a WONT or DONT needs no answer
        if (command, option) in self.answered: return b''
        self.answered.add((command, option))
        return bytes([IAC, answer, option])


def telnet_escape(data):
    """Input for the device: 0xFF doubled (a no-op for UTF-8 text, kept for correctness)."""
    return data.replace(b'\xff', b'\xff\xff')


HEALTH = re.compile(r'\((health: starting|healthy|unhealthy)\)')


def health_part(runtime_status):
    """'starting', 'healthy' or 'unhealthy' from Docker's status line ('Up 12 minutes (health: starting)'), else ''."""
    match = HEALTH.search(runtime_status or '')
    if not match: return ''
    return match.group(1).replace('health: ', '')


def container_age(runtime_status, inspected_epoch, now):
    """The container's age in seconds as of `now`: the uptime discovery read plus the time since that inspection
    (a status one discovery interval old is not read as younger than it is); None when the status line gives no
    uptime to the minute (hours, days, stopped). A clock that went backwards adds nothing."""
    uptime = uptime_seconds(runtime_status)
    if uptime is None: return None
    return uptime + max(0, int(now - (inspected_epoch or 0)))
