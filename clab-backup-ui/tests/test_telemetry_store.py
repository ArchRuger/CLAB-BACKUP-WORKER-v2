"""Session-only buffers: rates, resets, ordering, generations, bounds and expiry."""
import unittest

from app import telemetry_store
from app.telemetry_store import MAX_INTERFACES, MAX_PEERS, POINTS, STALE_AFTER, WINDOW, TelemetryStore

BASE = 1_757_764_800.0


def record(t, metric, value, node='r1', generation='g1', ident='Ethernet1', kind='interface', **extra):
    return dict(lab_id='lab', node=node, generation=generation, kind=kind, ident=ident, metric=metric,
                value=value, ts=t, method='gnmi-sample-10s', **extra)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = TelemetryStore()
        self.assertTrue(self.store.begin('lab', 'r1', 'g1'))

    def test_eos_last_change_timestamps_never_shadow_other_leaves(self):
        """cEOS stamps each notification with the last change time of its leaves: in one 10 s cycle
        the changing counters arrive with a fresh timestamp, idle counters with one minutes old
        (replaced by receive time beyond the collector's slack) and the interface state with the
        time it last flapped. Seen live: half the samples dropped, no receive rate, no state."""
        def cycle(received, in_octets, in_stamp):
            # Idle leaves: device stamp 12 minutes old, replaced by the receive time (synthetic).
            yield record(received, 'out-octets', 0, received=received, synthetic=True)
            yield record(received, 'out-pkts', 0, received=received, synthetic=True)
            # Changing leaves: a genuine device stamp a second or two before receipt.
            yield record(in_stamp, 'in-octets', in_octets, received=received, synthetic=False)
            yield record(in_stamp, 'in-pkts', in_octets // 100, received=received, synthetic=False)
        # The initial on-change state carries the time the interface came up, four minutes ago.
        self.assertTrue(self.store.ingest(record(BASE - 240, 'oper-status', 'UP', received=BASE, synthetic=False)))
        self.assertTrue(self.store.ingest(record(BASE - 240, 'admin-status', 'UP', received=BASE, synthetic=False)))
        for received, octets in ((BASE, 1000), (BASE + 10, 2000), (BASE + 20, 4000)):
            for item in cycle(received, octets, received - 2):
                self.assertTrue(self.store.ingest(item), item)
        snap = self.store.snapshot('lab', 'r1', now=BASE + 21)
        row = snap['interfaces'][0]
        self.assertEqual((snap['dropped'], snap['samples']), (0, 14))
        self.assertEqual((row['oper'], row['admin']), ('UP', 'UP'))
        self.assertEqual((row['rx_bps'], row['tx_bps'], row['rx_pps'], row['tx_pps']), (1600.0, 0.0, 2.0, 0.0), 'rates over receive time')
        self.assertEqual([p['t'] for p in self.store.series('lab', 'r1', 'Ethernet1', 300, now=BASE + 21)], [BASE, BASE + 10, BASE + 20], 'one point per cycle')
        # The idle group of the next cycle arrives 1.3 s before the changing group (seen live):
        # both directions stay visible in the snapshot and share one chart point.
        for item in (record(BASE + 30, 'out-octets', 0, received=BASE + 30, synthetic=True),
                     record(BASE + 30, 'out-pkts', 0, received=BASE + 30, synthetic=True)):
            self.assertTrue(self.store.ingest(item))
        early = self.store.snapshot('lab', 'r1', now=BASE + 30.5)['interfaces'][0]
        self.assertEqual((early['rx_bps'], early['tx_bps']), (1600.0, 0.0), 'the receive rate of the previous cycle stays until its own next sample')
        for item in (record(BASE + 29, 'in-octets', 6000, received=BASE + 31.3, synthetic=False),
                     record(BASE + 29, 'in-pkts', 60, received=BASE + 31.3, synthetic=False)):
            self.assertTrue(self.store.ingest(item))
        late = self.store.snapshot('lab', 'r1', now=BASE + 32)['interfaces'][0]
        self.assertAlmostEqual(late['rx_bps'], 2000 * 8 / 11.3, places=3); self.assertEqual(late['tx_bps'], 0.0)
        self.assertEqual([p['t'] for p in self.store.series('lab', 'r1', 'Ethernet1', 300, now=BASE + 32)], [BASE, BASE + 10, BASE + 20, BASE + 30])
        self.assertIn('rx_bps', self.store.series('lab', 'r1', 'Ethernet1', 300, now=BASE + 32)[-1])
        # The interface flaps: the new state carries a newer device stamp and replaces the old one;
        # a late notification about the earlier state (older stamp) is ignored.
        self.assertTrue(self.store.ingest(record(BASE + 25, 'oper-status', 'DOWN', received=BASE + 25.2, synthetic=False)))
        self.assertFalse(self.store.ingest(record(BASE - 240, 'oper-status', 'UP', received=BASE + 25.4, synthetic=False)))
        self.assertEqual(self.store.snapshot('lab', 'r1', now=BASE + 26)['interfaces'][0]['oper'], 'DOWN')
        # A device whose clock is 200 s slow: its genuine stamps are older than the synthetic ones
        # written for idle leaves, yet its next samples must still be accepted.
        self.assertTrue(self.store.ingest(record(BASE + 30, 'out-octets', 0, received=BASE + 30, synthetic=True)))
        self.assertTrue(self.store.ingest(record(BASE + 40 - 200, 'out-octets', 900, received=BASE + 40, synthetic=False)))
        self.assertEqual(self.store.snapshot('lab', 'r1', now=BASE + 41)['interfaces'][0]['tx_bps'], 720.0)

    def test_rates_use_counter_deltas_over_elapsed_receive_time(self):
        for t, rx, tx in ((BASE, 1000, 500), (BASE + 10, 2000, 1500), (BASE + 25, 5000, 1500)):
            self.assertTrue(self.store.ingest(record(t, 'in-octets', rx)))
            self.assertTrue(self.store.ingest(record(t, 'out-octets', str(tx))))
        points = self.store.series('lab', 'r1', 'Ethernet1', 300, now=BASE + 26)
        self.assertEqual([p.get('rx_bps') for p in points], [None, 800.0, 1600.0])
        self.assertEqual([p.get('tx_bps') for p in points], [None, 800.0, 0.0])
        row = self.store.snapshot('lab', 'r1', now=BASE + 26)['interfaces'][0]
        self.assertEqual((row['rx_bps'], row['tx_bps'], row['totals']['in-octets']), (1600.0, 0.0, 5000))

    def test_counter_resets_and_long_gaps_produce_no_rate(self):
        self.store.ingest(record(BASE, 'in-octets', 9000))
        self.store.ingest(record(BASE + 10, 'in-octets', 10000))
        self.store.ingest(record(BASE + 20, 'in-octets', 50))      # device or interface restarted
        row = self.store.snapshot('lab', 'r1', now=BASE + 21)['interfaces'][0]
        self.assertIsNone(row['rx_bps']); self.assertEqual(row['resets'], 1)
        self.store.ingest(record(BASE + 30, 'in-octets', 1050))
        self.assertEqual(self.store.snapshot('lab', 'r1', now=BASE + 31)['interfaces'][0]['rx_bps'], 800.0)
        self.store.ingest(record(BASE + 30 + telemetry_store.MAX_GAP + 1, 'in-octets', 999999))
        self.assertIsNone(self.store.snapshot('lab', 'r1', now=BASE + 30 + telemetry_store.MAX_GAP + 2)['interfaces'][0]['rx_bps'],
                          'a gap longer than MAX_GAP restarts the rate instead of averaging over it')

    def test_out_of_order_and_foreign_generation_samples_are_dropped(self):
        self.store.ingest(record(BASE + 10, 'in-octets', 100))
        self.assertFalse(self.store.ingest(record(BASE, 'in-octets', 50)), 'older sample after a newer one')
        self.assertFalse(self.store.ingest(record(BASE + 20, 'in-octets', 999, generation='g0')), 'previous deployment')
        self.assertFalse(self.store.ingest(record(BASE + 20, 'in-octets', 999, node='other')), 'untracked node')
        snap = self.store.snapshot('lab', 'r1', now=BASE + 11)
        self.assertEqual((snap['dropped'], self.store.rejected, snap['samples']), (2, 1, 1))
        self.store.begin('lab', 'r1', 'g2')   # redeploy with the same name and address
        self.assertFalse(self.store.ingest(record(BASE + 30, 'in-octets', 5, generation='g1')))
        self.assertTrue(self.store.ingest(record(BASE + 30, 'in-octets', 5, generation='g2')))
        self.assertEqual(self.store.snapshot('lab', 'r1', now=BASE + 31)['interfaces'][0]['totals'], {'in-octets': 5})

    def test_status_and_bgp_values_normalise_enumerations(self):
        self.assertTrue(self.store.ingest(record(BASE, 'oper-status', 'openconfig-interfaces:UP')))
        self.assertTrue(self.store.ingest(record(BASE, 'admin-status', 'up')))
        self.assertFalse(self.store.ingest(record(BASE, 'in-octets', 'not-a-number')))
        self.assertFalse(self.store.ingest(record(BASE, 'mtu', 1500)))
        self.assertTrue(self.store.ingest(record(BASE, 'session-state', 'openconfig-bgp-types:ESTABLISHED', ident='10.0.0.2', kind='bgp', instance='default')))
        self.assertTrue(self.store.ingest(record(BASE, 'received', '12', ident='10.0.0.2', kind='bgp', instance='default', afi='IPV4_UNICAST')))
        self.assertFalse(self.store.ingest(record(BASE, 'received', '1', ident='10.0.0.2', kind='bgp', instance='default', afi='IPV6_UNICAST')), 'one family per neighbour')
        snap = self.store.snapshot('lab', 'r1', now=BASE + 1)
        self.assertEqual((snap['interfaces'][0]['oper'], snap['interfaces'][0]['admin']), ('UP', 'UP'))
        self.assertEqual(snap['peers'][0]['state'], 'ESTABLISHED'); self.assertEqual(snap['peers'][0]['received'], 12)
        self.assertEqual(self.store.peer_series('lab', 'r1', 'default', '10.0.0.2', 300, now=BASE + 1), [{'t': BASE, 'received': 12}])

    def test_bounds_hold_for_points_interfaces_peers_and_nodes(self):
        for index in range(POINTS + 50):
            self.store.ingest(record(BASE + index * 10, 'in-octets', index * 100))
        series = self.store.series('lab', 'r1', 'Ethernet1', 3600, now=BASE + (POINTS + 50) * 10)
        self.assertLessEqual(len(series), POINTS)
        self.assertLessEqual(len(series), WINDOW // 10 + 1)
        for index in range(MAX_INTERFACES + 5):
            self.store.ingest(record(BASE, 'oper-status', 'UP', ident=f'Ethernet{index}'))
        for index in range(MAX_PEERS + 5):
            self.store.ingest(record(BASE, 'session-state', 'IDLE', ident=f'10.0.{index // 250}.{index % 250}', kind='bgp'))
        snap = self.store.snapshot('lab', 'r1', now=BASE)
        self.assertEqual(len(snap['interfaces']), MAX_INTERFACES); self.assertEqual(len(snap['peers']), MAX_PEERS)
        self.assertEqual(snap['overflow'], 10)
        with unittest.mock.patch.object(telemetry_store, 'MAX_NODES', 1):
            self.assertFalse(self.store.begin('lab', 'r2', 'g1'))
        self.assertTrue(self.store.begin('lab', 'r1', 'g9'), 'an existing node can always restart its buffers')

    def test_samples_age_out_and_stale_series_report_no_rate(self):
        self.store.ingest(record(BASE, 'in-octets', 0)); self.store.ingest(record(BASE + 10, 'in-octets', 1000))
        fresh = self.store.snapshot('lab', 'r1', now=BASE + 20)
        self.assertTrue(fresh['fresh']); self.assertEqual(fresh['interfaces'][0]['rx_bps'], 800.0)
        stale = self.store.snapshot('lab', 'r1', now=BASE + 10 + STALE_AFTER + 1)
        self.assertFalse(stale['fresh']); self.assertFalse(stale['interfaces'][0]['fresh']); self.assertIsNone(stale['interfaces'][0]['rx_bps'])
        self.assertEqual(stale['interfaces'][0]['totals']['in-octets'], 1000, 'recent history stays readable while stale')
        self.assertEqual(self.store.series('lab', 'r1', 'Ethernet1', 300, now=BASE + 200), [{'t': BASE}, {'t': BASE + 10, 'rx_bps': 800.0}])
        self.assertIsNone(self.store.series('lab', 'r1', 'Ethernet9', 300, now=BASE))
        self.assertEqual(self.store.series('lab', 'r1', 'Ethernet1', 4242, now=BASE + 20), self.store.series('lab', 'r1', 'Ethernet1', 300, now=BASE + 20), 'unknown windows fall back to the shortest')
        self.assertEqual(self.store.series('lab', 'r1', 'Ethernet1', 3600, now=BASE + WINDOW + 20), [], 'older than the window')
        self.assertEqual(self.store.stats()['points'], 0, 'aged points are released, not merely hidden')

    def test_clearing_forgets_a_node_a_lab_or_everything(self):
        self.store.begin('lab', 'r2', 'g1'); self.store.begin('other', 'r1', 'g1')
        self.store.clear_node('lab', 'r2'); self.assertIsNone(self.store.snapshot('lab', 'r2'))
        self.store.clear_lab('lab'); self.assertIsNone(self.store.snapshot('lab', 'r1')); self.assertIsNotNone(self.store.snapshot('other', 'r1'))
        self.store.clear_all(); self.assertEqual(self.store.stats()['nodes'], 0)


import unittest.mock  # noqa: E402  (used in one test above)

if __name__ == '__main__':
    unittest.main()
