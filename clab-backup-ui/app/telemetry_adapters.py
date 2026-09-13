"""Per-NOS telemetry adapters: what to read, the smallest lines to add, how to subscribe.

Each adapter describes one supported containerlab kind. It never talks to a device
itself: the provisioning driver runs its show commands, hands the outputs back to
``plan`` and applies the returned lines with the NOS's own scoped commit, and the
collector subscribes with the paths and encodings it lists. Every configuration line
the manager adds is native syntax that is recorded verbatim, so a later removal can
prove it only touches what the manager wrote.

Sources (retrieved 2026-09-13): containerlab kind pages for cEOS (default config
enables ``management api gnmi`` / ``transport grpc default`` on TCP 6030 without
TLS), XRv9k (gNMI pre-provisioned on 57400) and cJunosEvolved (SSH only; eth4 is
et-0/0/0); Arista openmgmt configuration guide; Cisco IOS XR gRPC guides; Juniper
gRPC services guide (``system services extension-service request-response grpc``).
"""
import re

from .telemetry_names import interface_role, physical_name

SAMPLE_NS = 10 * 1_000_000_000      # counters every 10 s (gNMI sample intervals are nanoseconds)
INTERFACE_LEAVES = ('counters', 'oper-status', 'admin-status')
BGP_STATE = 'network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/state/session-state'
BGP_PREFIXES = 'network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/afi-safis/afi-safi/state/prefixes'
BGP_NEIGHBOR = 'network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/state'
BGP_AFI = 'network-instances/network-instance/protocols/protocol/bgp/neighbors/neighbor/afi-safis/afi-safi/state'
INTERFACE_MODELS = ('openconfig-interfaces',)
BGP_MODELS = ('openconfig-network-instance', 'openconfig-bgp')
ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')


class Plan:
    """Result of reading a node: the endpoint to use and the lines still missing."""
    def __init__(self, port, transport, add=(), blockers=(), present=(), vrf=''):
        self.port = port
        self.transport = transport      # 'plaintext' or 'tls'
        self.add = list(add)            # native lines the manager must add, in order
        self.blockers = list(blockers)  # reasons no automatic change is possible
        self.present = list(present)    # manager-owned lines already found (repeat safety)
        self.vrf = vrf

    @property
    def ready(self):
        return not self.add and not self.blockers


def _lines(text):
    return [ANSI.sub('', line).rstrip() for line in (text or '').splitlines()]


class Adapter:
    kind = ''
    label = ''
    default_port = 0
    encodings = ('json_ietf', 'proto')
    prompt = re.compile(r'[>#]\s*$')
    more_prompt = None
    password_prompt = re.compile(r'(?i)password:\s*$')
    error_marks = ()
    interface_origin = ''
    bgp_origin = ''
    state_mode = 'sample'

    # ---- reading and planning -----------------------------------------------
    def prepare(self):
        """Commands that make the shell usable (paging off); enable handling is separate."""
        return []

    def show_commands(self):
        return []

    def plan(self, outputs):
        raise NotImplementedError

    def apply(self, plan):
        """CLI lines that add plan.add and return to the operational prompt."""
        raise NotImplementedError

    def abort(self):
        """CLI lines that leave configuration mode without keeping anything."""
        return []

    def remove(self, lines):
        """CLI lines that remove exactly the given manager-owned lines."""
        raise NotImplementedError

    def failed(self, text):
        """A controlled reason when apply output shows the NOS rejected something, else ''."""
        for mark in self.error_marks:
            if re.search(mark, text or ''):
                return 'The NOS rejected the telemetry configuration (' + mark.strip('^%\\() ') + ').'
        return ''

    # ---- subscriptions -------------------------------------------------------
    def path(self, origin, rest):
        return (origin + ':' if origin else '/') + rest

    def subscriptions(self, group):
        """Variants to try in order; each is a list of subscription dicts for one stream."""
        sample = {'mode': 'sample', 'sample_interval': SAMPLE_NS}
        if group == 'interfaces':
            base = 'interfaces/interface/state/'
            status_mode = ({'mode': 'on_change'} if self.state_mode == 'on_change' else sample)
            leaves = [dict(path=self.path(self.interface_origin, base + 'counters'), **sample),
                      dict(path=self.path(self.interface_origin, base + 'oper-status'), **status_mode),
                      dict(path=self.path(self.interface_origin, base + 'admin-status'), **status_mode)]
            variants = [leaves]
            if self.state_mode == 'on_change':
                variants.append([dict(path=self.path(self.interface_origin, base + leaf), **sample) for leaf in INTERFACE_LEAVES])
            variants.append([dict(path=self.path(self.interface_origin, 'interfaces/interface/state'), **sample)])
            return variants
        if group == 'bgp':
            return [[dict(path=self.path(self.bgp_origin, BGP_STATE), **sample),
                     dict(path=self.path(self.bgp_origin, BGP_PREFIXES), **sample)],
                    [dict(path=self.path(self.bgp_origin, BGP_NEIGHBOR), **sample),
                     dict(path=self.path(self.bgp_origin, BGP_AFI), **sample)]]
        return []

    def models_present(self, group, models):
        names = {m.get('name', '') for m in models or []}
        wanted = INTERFACE_MODELS if group == 'interfaces' else BGP_MODELS
        return any(any(n == w or n.startswith(w) for n in names) for w in wanted)

    # ---- names ---------------------------------------------------------------
    def role(self, name):
        return interface_role(self.kind, name)

    def physical(self, name):
        return physical_name(self.kind, name)


class EosAdapter(Adapter):
    kind = 'arista_ceos'
    label = 'EOS'
    default_port = 6030
    encodings = ('json_ietf', 'json', 'proto')
    prompt = re.compile(r'^[^\s>#]+[>#]\s*$')
    error_marks = (r'(?m)^% ', r'(?m)^\s*% Invalid', r'(?m)^\s*% Incomplete')
    state_mode = 'on_change'

    def prepare(self):
        return ['terminal length 0', 'terminal width 32767']

    def show_commands(self):
        return ['show running-config | section management api gnmi',
                'show running-config | section interface Management0']

    def plan(self, outputs):
        gnmi = _lines(outputs.get(self.show_commands()[0], ''))
        mgmt = _lines(outputs.get(self.show_commands()[1], ''))
        vrf = ''
        for line in mgmt:
            match = re.match(r'^\s+vrf\s+(\S+)\s*$', line)
            if match:
                vrf = match[1]
        transports = []
        current = None
        for line in gnmi:
            match = re.match(r'^\s+transport grpc\s+(\S+)\s*$', line)
            if match:
                current = {'name': match[1], 'port': self.default_port, 'tls': False, 'shutdown': False, 'vrf': ''}
                transports.append(current)
                continue
            if current is None or not line.startswith(' ' * 6):
                if line and not line.startswith(' '):
                    current = None
                continue
            body = line.strip()
            if body == 'shutdown':
                current['shutdown'] = True
            elif body.startswith('port '):
                try: current['port'] = int(body.split()[1])
                except (ValueError, IndexError): pass
            elif body.startswith('ssl profile '):
                current['tls'] = True
            elif body.startswith('vrf '):
                current['vrf'] = body.split()[1]
        usable = [t for t in transports if not t['shutdown']]
        if usable:
            chosen = usable[0]
            blockers = []
            if vrf and chosen['vrf'] != vrf:
                blockers.append(f"gNMI transport '{chosen['name']}' is not bound to the management VRF {vrf}; move it there or add a transport in that VRF.")
            return Plan(chosen['port'], 'tls' if chosen['tls'] else 'plaintext', blockers=blockers, vrf=chosen['vrf'])
        if transports:
            return Plan(self.default_port, 'plaintext', blockers=['Every gNMI transport on this node is shut down. Enable one, or remove the shutdown, before telemetry can connect.'])
        add = ['management api gnmi', '   transport grpc default']
        if vrf:
            add.append('      vrf ' + vrf)
        return Plan(self.default_port, 'plaintext', add=add, vrf=vrf)

    def apply(self, plan):
        lines = ['configure terminal']
        lines.extend(line.strip() for line in plan.add)
        lines.append('end')
        return lines

    def abort(self):
        return ['end']

    def remove(self, lines):
        owned = [l.strip() for l in lines]
        if 'management api gnmi' in owned and 'transport grpc default' in owned:
            # The manager created the whole block; remove only the transport it added
            # and the block when nothing else is left in it.
            return ['configure terminal', 'management api gnmi', 'no transport grpc default', 'exit', 'end']
        return []


class IosxrAdapter(Adapter):
    kind = 'cisco_xrv9k'
    label = 'IOS-XR'
    default_port = 57400
    encodings = ('json_ietf', 'proto')
    prompt = re.compile(r'^RP/\S+:\S+#\s*$')
    error_marks = (r'(?m)^% Failed', r'(?m)^% Invalid', r'(?m)^% Incomplete', r'!! SEMANTIC ERRORS', r'!! SYNTAX', r'(?m)^% This session')
    interface_origin = 'openconfig-interfaces'
    bgp_origin = 'openconfig-network-instance'

    def prepare(self):
        return ['terminal length 0', 'terminal width 512']

    def show_commands(self):
        return ['show running-config grpc', 'show running-config interface MgmtEth0/RP0/CPU0/0']

    def plan(self, outputs):
        grpc = _lines(outputs.get(self.show_commands()[0], ''))
        mgmt = _lines(outputs.get(self.show_commands()[1], ''))
        vrf = ''
        for line in mgmt:
            match = re.match(r'^\s+vrf\s+(\S+)\s*$', line)
            if match:
                vrf = match[1]
        present = any(re.match(r'^grpc\s*$', line) for line in grpc)
        if not present:
            add = ['grpc', ' port ' + str(self.default_port)]
            if vrf:
                add.append(' vrf ' + vrf)
            return Plan(self.default_port, 'tls', add=add, vrf=vrf)
        port = self.default_port
        transport = 'tls'
        grpc_vrf = ''
        for line in grpc:
            body = line.strip()
            match = re.match(r'^port\s+(\d+)$', body)
            if match:
                port = int(match[1])
            elif body == 'no-tls':
                transport = 'plaintext'
            elif body.startswith('vrf '):
                grpc_vrf = body.split()[1]
        blockers = []
        if vrf and grpc_vrf != vrf:
            blockers.append(f'gRPC is not bound to the management VRF {vrf} (add "vrf {vrf}" under grpc) so the collector cannot reach it.')
        return Plan(port, transport, blockers=blockers, vrf=grpc_vrf)

    def apply(self, plan):
        lines = ['configure terminal']
        lines.extend(line.strip() for line in plan.add)
        lines.extend(['commit', 'end'])
        return lines

    def abort(self):
        return ['abort']

    def remove(self, lines):
        owned = [l.strip() for l in lines]
        if 'grpc' in owned:
            return ['configure terminal', 'no grpc', 'commit', 'end']
        return []


class JunosEvoAdapter(Adapter):
    kind = 'juniper_cjunosevolved'
    label = 'Junos Evolved'
    default_port = 32767
    encodings = ('json_ietf', 'proto')
    prompt = re.compile(r'^[\w.-]+@[\w.-]+[>#]\s*$')
    error_marks = (r'(?m)^error:', r'(?m)^\s*syntax error', r'(?m)^\s*unknown command', r'commit failed')
    grpc = 'set system services extension-service request-response grpc'

    def prepare(self):
        return ['set cli screen-length 0', 'set cli screen-width 0']

    def show_commands(self):
        return ['show configuration system services extension-service | display set',
                'show configuration system management-instance | display set']

    def plan(self, outputs):
        service = _lines(outputs.get(self.show_commands()[0], ''))
        mgmt = _lines(outputs.get(self.show_commands()[1], ''))
        instance = any(line.startswith('set system management-instance') for line in mgmt)
        clear_port = ssl_port = None
        routing = ''
        for line in service:
            body = line.strip()
            match = re.match(r'^' + re.escape(self.grpc) + r' clear-text(?: port (\d+))?$', body)
            if match:
                clear_port = int(match[1]) if match[1] else (clear_port or self.default_port)
            match = re.match(r'^' + re.escape(self.grpc) + r' ssl(?: port (\d+))?$', body)
            if match:
                ssl_port = int(match[1]) if match[1] else (ssl_port or self.default_port)
            match = re.match(r'^' + re.escape(self.grpc) + r' routing-instance (\S+)$', body)
            if match:
                routing = match[1]
        if clear_port or ssl_port:
            blockers = []
            if instance and routing != 'mgmt_junos':
                blockers.append('gRPC is not bound to the mgmt_junos routing instance that carries the management interface; add "routing-instance mgmt_junos" under the grpc service.')
            if clear_port:
                return Plan(clear_port, 'plaintext', blockers=blockers, vrf=routing)
            return Plan(ssl_port, 'tls', blockers=blockers, vrf=routing)
        add = [self.grpc + ' clear-text port ' + str(self.default_port)]
        if instance:
            add.append(self.grpc + ' routing-instance mgmt_junos')
        return Plan(self.default_port, 'plaintext', add=add, vrf='mgmt_junos' if instance else '')

    def apply(self, plan):
        return ['configure private', *plan.add, 'commit and-quit']

    def abort(self):
        return ['rollback 0', 'exit configuration-mode']

    def remove(self, lines):
        owned = [l.strip() for l in lines]
        deletes = []
        for line in owned:
            if line.startswith(self.grpc + ' clear-text'):
                deletes.append('delete system services extension-service request-response grpc clear-text')
            elif line.startswith(self.grpc + ' routing-instance'):
                deletes.append('delete system services extension-service request-response grpc routing-instance')
        return ['configure private', *deletes, 'commit and-quit'] if deletes else []


ADAPTERS = {a.kind: a for a in (EosAdapter(), IosxrAdapter(), JunosEvoAdapter())}
SUPPORTED = tuple(ADAPTERS)


def adapter_for(platform):
    return ADAPTERS.get(platform or '')
