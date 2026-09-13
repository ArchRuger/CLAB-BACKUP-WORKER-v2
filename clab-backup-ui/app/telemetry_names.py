"""Interface name resolution between containerlab wiring, imported aliases and NOS telemetry.

A topology link names its ends the containerlab way (``eth1``) or with the alias the
YAML author used (``Gi0/0/0/1``, ``et-0/0/0``, ``Ethernet1``). Telemetry names the
same port the way the NOS does. The mapping is explicit per kind; an unknown form
resolves to '' rather than to a guess, because ``eth1`` is a data port on cEOS, the
first Gigabit port on XRv9k and a reserved internal interface on cJunosEvolved.
"""
import re

MANAGEMENT = {
    'arista_ceos': re.compile(r'^Management\d', re.I),
    'cisco_xrv9k': re.compile(r'^MgmtEth', re.I),
    'juniper_cjunosevolved': re.compile(r'^(?:re\d:mgmt-\d|mgmt-\d|fxp\d|em\d)', re.I),
}
PHYSICAL = {
    'arista_ceos': re.compile(r'^Ethernet\d+(?:/\d+)*$'),
    'cisco_xrv9k': re.compile(r'^(?:GigabitEthernet|TenGigE|TwentyFiveGigE|FortyGigE|HundredGigE|Bundle-Ether)\S+$'),
    'juniper_cjunosevolved': re.compile(r'^(?:et|xe|ge)-\d+/\d+/\d+(?::\d+)?$'),
}
SUPPORTED_KINDS = tuple(PHYSICAL)


def nos_interface(kind, name):
    """The telemetry name of a wired port, or '' when the form is not understood for the kind."""
    if not isinstance(name, str) or not name or not isinstance(kind, str):
        return ''
    value = name.strip()
    if kind == 'arista_ceos':
        match = re.fullmatch(r'(?i)(?:eth|et)(\d+)(?:[_/](\d+))?', value)
        if match:
            return 'Ethernet' + match[1] + ('/' + match[2] if match[2] else '')
        match = re.fullmatch(r'(?i)ethernet(\d+(?:/\d+)*)', value)
        if match:
            return 'Ethernet' + match[1]
        match = re.fullmatch(r'(?i)(?:ma|management)(\d+)', value)
        if match:
            return 'Management' + match[1]
        return ''
    if kind == 'cisco_xrv9k':
        match = re.fullmatch(r'(?i)eth(\d+)', value)
        if match:
            index = int(match[1])
            # eth0 is the container management side; eth1 is the first data port.
            return 'GigabitEthernet0/0/0/' + str(index - 1) if index >= 1 else ''
        match = re.fullmatch(r'(?i)(?:gi|gige|gigabitethernet)(\d+/\d+/\d+/\d+)', value)
        if match:
            return 'GigabitEthernet' + match[1]
        match = re.fullmatch(r'(?i)(?:te|tengige|tengigabitethernet)(\d+/\d+/\d+/\d+)', value)
        if match:
            return 'TenGigE' + match[1]
        match = re.fullmatch(r'(?i)(?:hu|hundredgige)(\d+/\d+/\d+/\d+)', value)
        if match:
            return 'HundredGigE' + match[1]
        match = re.fullmatch(r'(?i)(?:mg|mgmteth)(\d+/[A-Z0-9]+/[A-Z0-9]+/\d+)', value)
        if match:
            return 'MgmtEth' + match[1]
        match = re.fullmatch(r'(?i)(?:lo|loopback)(\d+)', value)
        if match:
            return 'Loopback' + match[1]
        return ''
    if kind == 'juniper_cjunosevolved':
        match = re.fullmatch(r'(?i)eth(\d+)', value)
        if match:
            index = int(match[1])
            # eth1 to eth3 are reserved by the cJunosEvolved container; eth4 is et-0/0/0.
            return 'et-0/0/' + str(index - 4) if index >= 4 else ''
        match = re.fullmatch(r'(?i)(et|xe|ge)-(\d+)/(\d+)/(\d+)(?::(\d+))?(?:\.(\d+))?', value)
        if match:
            base = f'{match[1].lower()}-{match[2]}/{match[3]}/{match[4]}'
            if match[5]:
                base += ':' + match[5]
            return base
        match = re.fullmatch(r'(?i)(?:re\d:mgmt-\d|mgmt-\d|fxp\d|em\d|lo\d)', value)
        if match:
            return value.lower()
        return ''
    return ''


def physical_name(kind, name):
    """The physical port behind a telemetry name: Junos units (et-0/0/0.0) fold onto the port."""
    if not isinstance(name, str):
        return ''
    if kind == 'juniper_cjunosevolved':
        return name.split('.', 1)[0]
    return name


def interface_role(kind, name):
    """'physical', 'management' or 'other' for grouping and for the first-shown list."""
    if not isinstance(name, str):
        return 'other'
    if MANAGEMENT.get(kind) and MANAGEMENT[kind].match(name):
        return 'management'
    if PHYSICAL.get(kind) and PHYSICAL[kind].match(physical_name(kind, name)):
        return 'physical'
    return 'other'


def endpoint_candidates(kind, name):
    """Every telemetry name that may report this wired port, most specific first."""
    mapped = nos_interface(kind, name)
    result = []
    for value in (mapped, name if isinstance(name, str) else ''):
        if value and value not in result:
            result.append(value)
    return result
