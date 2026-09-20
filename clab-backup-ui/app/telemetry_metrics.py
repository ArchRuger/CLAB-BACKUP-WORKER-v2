"""Prometheus exposition of the session store, for the optional Grafana dashboards.

One text document per scrape: the latest rate and state of every interface and BGP
neighbour of every linked lab, plus node and link states. It is derived from the same
bounded snapshots the Telemetry tab reads, carries names only (no addresses, logins
or configuration) and is served under /api/ with the manager's usual guards.
"""

RATES = (('rx_bps', 'clab_interface_receive_bits_per_second', 'Received bit rate derived from counter deltas'),
         ('tx_bps', 'clab_interface_transmit_bits_per_second', 'Transmitted bit rate derived from counter deltas'),
         ('rx_pps', 'clab_interface_receive_packets_per_second', 'Received packet rate derived from counter deltas'),
         ('tx_pps', 'clab_interface_transmit_packets_per_second', 'Transmitted packet rate derived from counter deltas'))
# The node state as a number, for dashboards that colour by value (the Grafana lab map).
STATE_CODES = {'failed': -1, 'disabled': 0, 'unsupported': 0, 'unmonitored': 0,
               'waiting': 1, 'configuring': 1, 'connecting': 1, 'stale': 2, 'streaming': 3}
TOTALS = (('in-errors', 'clab_interface_receive_errors_total', 'Device receive error counter'),
          ('out-errors', 'clab_interface_transmit_errors_total', 'Device transmit error counter'),
          ('in-discards', 'clab_interface_receive_discards_total', 'Device receive discard counter'),
          ('out-discards', 'clab_interface_transmit_discards_total', 'Device transmit discard counter'),
          ('in-octets', 'clab_interface_receive_bytes_total', 'Device receive byte counter'),
          ('out-octets', 'clab_interface_transmit_bytes_total', 'Device transmit byte counter'))


def escape(value):
    return str(value).replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')


def labels(**items):
    return '{' + ','.join(f'{key}="{escape(value)}"' for key, value in items.items() if value not in (None, '')) + '}'


def number(value):
    if isinstance(value, bool):
        return '1' if value else '0'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value) if value == value and value not in (float('inf'), float('-inf')) else 'NaN'
    return '0'


def render(views, now):
    """views: iterable of TelemetryManager.lab_view() results for linked labs."""
    families = {}

    def add(name, kind, help_text, sample_labels, value):
        family = families.setdefault(name, (kind, help_text, []))
        family[2].append(labels(**sample_labels) + ' ' + number(value))

    for view in views:
        lab = {'lab': view['lab_name'], 'lab_id': view['lab_id']}
        for node in view['nodes']:
            base = {**lab, 'node': node['short_name'], 'container': node['name'], 'platform': node.get('platform', '')}
            add('clab_telemetry_node_state', 'gauge', 'Current telemetry state of the node (one series per node, value 1)',
                {**base, 'state': node['state']}, 1)
            add('clab_telemetry_node_state_code', 'gauge', 'Telemetry state as a number: -1 failed, 0 off or unsupported, 1 waiting, configuring or connecting, 2 stale, 3 streaming',
                base, STATE_CODES.get(node['state'], 0))
            if node.get('last_sample'):
                add('clab_telemetry_node_sample_age_seconds', 'gauge', 'Seconds since the last usable sample from the node',
                    base, max(0.0, now - node['last_sample']))
            for row in node.get('interfaces', []):
                where = {**base, 'interface': row['name'], 'peer': row.get('peer', ''), 'peer_interface': row.get('peer_interface', ''), 'role': row.get('role', '')}
                if row.get('oper'):
                    add('clab_interface_oper_up', 'gauge', '1 when the interface reports oper-status UP', where, row['oper'] == 'UP')
                if row.get('admin'):
                    add('clab_interface_admin_up', 'gauge', '1 when the interface reports admin-status UP', where, row['admin'] == 'UP')
                if row.get('at'):
                    add('clab_interface_sample_age_seconds', 'gauge', 'Seconds since the last sample for the interface', where, max(0.0, now - row['at']))
                if not row.get('fresh'):
                    continue
                for key, name, help_text in RATES:
                    if isinstance(row.get(key), (int, float)):
                        add(name, 'gauge', help_text, where, float(row[key]))
                totals = row.get('totals') or {}
                for key, name, help_text in TOTALS:
                    if isinstance(totals.get(key), int):
                        add(name, 'counter', help_text, where, totals[key])
            for peer in node.get('peers', []):
                where = {**base, 'neighbor': peer['peer'], 'instance': peer.get('instance', ''), 'afi': peer.get('afi', '')}
                if peer.get('state'):
                    add('clab_bgp_neighbor_state', 'gauge', 'Current BGP session state of the neighbour (one series per neighbour, value 1)',
                        {**where, 'state': peer['state']}, 1)
                    add('clab_bgp_neighbor_established', 'gauge', '1 when the BGP session is ESTABLISHED', where, peer['state'] == 'ESTABLISHED')
                if not peer.get('fresh'):
                    continue
                for key, name in (('received', 'clab_bgp_neighbor_prefixes_received'), ('sent', 'clab_bgp_neighbor_prefixes_sent'), ('installed', 'clab_bgp_neighbor_prefixes_installed')):
                    if isinstance(peer.get(key), int):
                        add(name, 'gauge', 'BGP prefixes ' + key + ' for the neighbour and address family', where, peer[key])
        for link in view.get('links', []):
            ends = link['ends']
            where = {**lab, 'a_node': ends[0]['label'], 'a_interface': ends[0]['interface'], 'z_node': ends[1]['label'], 'z_interface': ends[1]['interface']}
            add('clab_link_status', 'gauge', 'Link status judged from both ends (one series per link, value 1)', {**where, 'status': link['status']}, 1)
            if link['status'] in ('up', 'down'):
                add('clab_link_up', 'gauge', '1 when both ends report UP, 0 when either end reports DOWN, absent otherwise',
                    where, 1 if link['status'] == 'up' else 0)
    lines = []
    for name, (kind, help_text, samples) in families.items():
        lines.append(f'# HELP {name} {escape(help_text)}')
        lines.append(f'# TYPE {name} {kind}')
        lines.extend(name + sample for sample in samples)
    return '\n'.join(lines) + ('\n' if lines else '')
