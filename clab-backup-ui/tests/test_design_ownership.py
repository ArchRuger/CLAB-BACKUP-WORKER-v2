"""Tests for app/design_ownership.py: the ownership algebra of PROVISIONING.md §3, statement by statement."""
import unittest

from app import design_ownership as do

EOS_BEFORE = '''! Command: show running-config
hostname ceos
!
interface Ethernet1
   no switchport
   ip address 10.0.0.1/30
!
interface Ethernet2
!
interface Management0
   ip address 172.20.20.101/24
!
no ip routing
!
end
'''
EOS_WOULD_BE = '''hostname ceos
!
ip routing
!
interface Ethernet1
   no switchport
   description ceos -> cjunosevolved
   ip address 10.0.0.1/30
   ipv6 address 2001:db8:1::1/64
!
interface Ethernet2
   no switchport
   ip address 10.0.0.13/30
!
interface Management0
   ip address 172.20.20.101/24
!
router ospf 1
   router-id 10.255.0.1
   max-lsa 12000
   passive-interface Ethernet3
!
router bgp 65000
   router-id 10.255.0.1
   neighbor 10.255.0.2 remote-as 65000
   neighbor 10.255.0.3 remote-as 65000
!
end
'''


class StatementFormTests(unittest.TestCase):
    def test_eos_statements_keep_their_parents_and_drop_banners(self):
        got = do.statements('arista_ceos', EOS_BEFORE)
        self.assertIn('interface Ethernet1 > ip address 10.0.0.1/30', got)
        self.assertIn('no ip routing', got)
        self.assertNotIn('end', got)
        self.assertFalse(any(s.startswith('!') for s in got))

    def test_xr_headers_are_dropped(self):
        got = do.statements('cisco_xrv9k', 'Sun Sep 27 00:34:20.083 UTC\n!! Building configuration...\n!! IOS XR Configuration 24.3.1\n!! Last configuration change at Sun Sep 27 00:33:33 2026 by clab\nrouter ospf 1\n router-id 1.1.1.1\n!\nend\n')
        self.assertEqual(got, {'router ospf 1', 'router ospf 1 > router-id 1.1.1.1'})

    def test_junos_set_statements_drop_the_edit_banner_and_volatile_lines(self):
        got = do.statements('juniper_vjunosswitch', '[edit]\nset version 23.2R1.14\nset system host-name x\nset protocols ospf area 0.0.0.0 interface ge-0/0/0.0 interface-type p2p\n')
        self.assertEqual(got, {'set system host-name x', 'set protocols ospf area 0.0.0.0 interface ge-0/0/0.0 interface-type p2p'})

    def test_ancestors(self):
        self.assertEqual(do.ancestors('arista_ceos', 'router bgp 65000 > address-family ipv4 > neighbor 10.255.0.2 activate'), ['router bgp 65000', 'router bgp 65000 > address-family ipv4'])
        self.assertEqual(do.ancestors('juniper_vjunosswitch', 'set protocols bgp group ibgp neighbor 10.255.0.1 description "a b"'),
                         ['set protocols', 'set protocols bgp', 'set protocols bgp group', 'set protocols bgp group ibgp', 'set protocols bgp group ibgp neighbor', 'set protocols bgp group ibgp neighbor 10.255.0.1', 'set protocols bgp group ibgp neighbor 10.255.0.1 description'],
                         'a quoted value is one word; the leaf keyword counts as a prefix too (harmless: its delete is the leaf delete)')


class DiffTests(unittest.TestCase):
    def setUp(self):
        self.before = do.statements('arista_ceos', EOS_BEFORE)
        self.would_be = do.statements('arista_ceos', EOS_WOULD_BE)

    def test_first_apply_adds_and_creates_ancestors_without_conflicts(self):
        result = do.diff('arista_ceos', self.before, self.would_be, owned=set(), desired=self.would_be - self.before)
        self.assertIn('router ospf 1 > max-lsa 12000', result['added'], 'device defaults inside a created container are added, hence owned')
        self.assertEqual(result['conflicts'], set())
        self.assertEqual(result['expected'], {'no ip routing'}, 'the merge replaced the default `no ip routing` by `ip routing`: expected, not a conflict')
        self.assertEqual(result['removed'], set())
        anc = do.created_ancestors('arista_ceos', result['added'], self.before)
        self.assertIn('router ospf 1', anc); self.assertIn('router bgp 65000', anc)
        self.assertNotIn('interface Ethernet1', anc, 'an interface that existed before is not a created container')

    def test_a_manual_value_the_merge_replaces_is_a_conflict(self):
        before = self.before | {'interface Ethernet2 > ip address 10.9.9.9/24'}
        result = do.diff('arista_ceos', before, self.would_be, owned=set(), desired=self.would_be - before)
        self.assertIn('interface Ethernet2 > ip address 10.9.9.9/24', result['conflicts'])
        result = do.diff('arista_ceos', before, self.would_be, owned={'interface Ethernet2 > ip address 10.9.9.9/24'}, desired=self.would_be - before)
        self.assertNotIn('interface Ethernet2 > ip address 10.9.9.9/24', result['conflicts'], 'an owned value may be replaced')

    def test_an_unowned_ipv6_sibling_is_a_conflict_although_both_would_stay(self):
        before = self.before | {'interface Ethernet1 > ipv6 address 2001:db8:9::1/64'}
        would_be = self.would_be | {'interface Ethernet1 > ipv6 address 2001:db8:9::1/64'}
        result = do.diff('arista_ceos', before, would_be, owned=set(), desired=would_be - before)
        self.assertIn('interface Ethernet1 > ipv6 address 2001:db8:9::1/64', result['conflicts'])

    def test_junos_second_address_beside_a_manual_one_is_a_conflict(self):
        before = {'set interfaces et-0/0/0 unit 0 family inet address 10.0.12.1/31'}
        would_be = before | {'set interfaces et-0/0/0 unit 0 family inet address 10.0.0.2/30'}
        result = do.diff('juniper_cjunosevolved', before, would_be, owned=set(), desired=would_be - before)
        self.assertEqual(result['conflicts'], {'set interfaces et-0/0/0 unit 0 family inet address 10.0.12.1/31'})

    def test_xr_shutdown_removed_by_no_shutdown_is_expected_not_a_conflict(self):
        before = {'interface GigabitEthernet0/0/0/0 > shutdown'}
        would_be = {'interface GigabitEthernet0/0/0/0 > no shutdown', 'interface GigabitEthernet0/0/0/0 > ipv4 address 10.0.0.10 255.255.255.252'}
        result = do.diff('cisco_xrv9k', before, would_be, owned=set(), desired=would_be)
        self.assertEqual(result['expected'], {'interface GigabitEthernet0/0/0/0 > shutdown'})
        self.assertEqual(result['conflicts'], set())

    def test_xr_shutdown_that_vanishes_under_a_designed_interface_is_expected_without_a_no_shutdown_line(self):
        # Live fact (XRv9k 24.3.1): `show configuration merge` never prints `no shutdown`; the port's `shutdown` just disappears.
        before = {'interface GigabitEthernet0/0/0/0', 'interface GigabitEthernet0/0/0/0 > shutdown', 'interface GigabitEthernet0/0/0/2 > shutdown', 'interface GigabitEthernet0/0/0/2'}
        would_be = {'interface GigabitEthernet0/0/0/0', 'interface GigabitEthernet0/0/0/0 > ipv4 address 10.1.0.7 255.255.255.254', 'interface GigabitEthernet0/0/0/2'}
        desired = {'interface GigabitEthernet0/0/0/0', 'interface GigabitEthernet0/0/0/0 > ipv4 address 10.1.0.7 255.255.255.254', 'interface GigabitEthernet0/0/0/0 > no shutdown'}
        result = do.diff('cisco_xrv9k', before, would_be, owned=set(), desired=desired)
        self.assertEqual(result['expected'], {'interface GigabitEthernet0/0/0/0 > shutdown'})
        self.assertEqual(result['conflicts'], {'interface GigabitEthernet0/0/0/2 > shutdown'}, 'a port the design does not touch losing its shutdown is somebody else\'s change')

    def test_stale_is_what_the_manager_owns_no_longer_wants_and_is_still_there(self):
        owned = {'router bgp 65000 > neighbor 10.255.0.3 remote-as 65000', 'router bgp 65000 > neighbor 10.255.0.2 remote-as 65000', 'router bgp 65000 > neighbor 10.255.0.9 remote-as 65000'}
        before = self.would_be   # the earlier apply is on the device (without .9: somebody removed it already)
        desired = {'router bgp 65000 > neighbor 10.255.0.2 remote-as 65000'}
        result = do.diff('arista_ceos', before, before, owned=owned, desired=desired)
        self.assertEqual(result['stale'], {'router bgp 65000 > neighbor 10.255.0.3 remote-as 65000'})


class RemovalPlanTests(unittest.TestCase):
    def test_a_removed_peer_is_one_leaf_removal(self):
        before = do.statements('arista_ceos', EOS_WOULD_BE)
        owned = {s for s in before if s.startswith('router bgp') or s.startswith('router ospf')}
        anc = {'router bgp 65000', 'router ospf 1'}
        desired = owned - {'router bgp 65000 > neighbor 10.255.0.3 remote-as 65000'}
        plan = do.plan_removals('arista_ceos', before, owned, anc, desired)
        # EOS: the neighbour's lines belong together; when every one of them is stale, one `no neighbor X` (live fact:
        # per-line negation leaves an explicit `no neighbor X activate` behind).
        self.assertEqual(plan['leaves'], ['router bgp 65000 > neighbor 10.255.0.3'])
        self.assertEqual(plan['remove'], [])
        self.assertEqual(do.render_removals('arista_ceos', plan), ['router bgp 65000', ' no neighbor 10.255.0.3', '!'])

    def test_a_dropped_module_removes_the_container_it_created_in_one_command(self):
        before = do.statements('arista_ceos', EOS_WOULD_BE)
        owned = {s for s in before if s.startswith('router bgp')}
        plan = do.plan_removals('arista_ceos', before, owned, {'router bgp 65000'}, desired=set())
        self.assertEqual(plan['remove'], ['router bgp 65000'])
        self.assertEqual(plan['leaves'], [])
        self.assertEqual(do.render_removals('arista_ceos', plan), ['no router bgp 65000', '!'])

    def test_a_manual_statement_under_a_created_container_is_not_owned(self):
        before = do.statements('arista_ceos', EOS_WOULD_BE) | {'router bgp 65000 > neighbor 10.9.9.9 remote-as 65009'}
        owned = {s for s in before if s.startswith('router bgp') and '10.9.9.9' not in s}
        result = do.diff('arista_ceos', before, before - {'router bgp 65000 > neighbor 10.9.9.9 remote-as 65009'}, owned, desired=owned, anc={'router bgp 65000'})
        self.assertIn('router bgp 65000 > neighbor 10.9.9.9 remote-as 65009', result['conflicts'], 'taking a manual neighbour away is a conflict even under a container the manager created')

    def test_a_container_with_a_manual_child_is_not_removed_whole(self):
        before = do.statements('arista_ceos', EOS_WOULD_BE) | {'router bgp 65000 > neighbor 10.9.9.9 remote-as 65009'}
        owned = {s for s in before if s.startswith('router bgp') and '10.9.9.9' not in s}
        plan = do.plan_removals('arista_ceos', before, owned, {'router bgp 65000'}, desired=set())
        self.assertEqual(plan['remove'], [])
        self.assertIn('router bgp 65000 > neighbor 10.255.0.2', plan['leaves'])
        self.assertIn('router bgp 65000 > router-id 10.255.0.1', plan['leaves'])
        self.assertNotIn('router bgp 65000', plan['leaves'], 'the container stays: a manual neighbour lives under it')
        self.assertEqual(plan['kept_manual'], ['router bgp 65000'])
        rendered = do.render_removals('arista_ceos', plan)
        self.assertNotIn('no router bgp 65000', rendered)
        self.assertIn(' no neighbor 10.255.0.2', rendered)
        self.assertNotIn(' no neighbor 10.9.9.9', rendered, 'the manual neighbour is untouched')
        missing, remaining = do.verify('arista_ceos', after={'router bgp 65000', 'router bgp 65000 > neighbor 10.9.9.9 remote-as 65009'},
                                       desired=set(), stale=owned, removed_ancestors=[], kept=plan['kept_manual'])
        self.assertEqual((missing, remaining), ([], []), 'a container kept on purpose is not a verification failure')

    def test_identity_change_removes_the_old_owned_container_first(self):
        before = do.statements('arista_ceos', EOS_WOULD_BE)
        owned = {s for s in before if s.startswith('router bgp 65000')}
        desired = {s.replace('65000', '65010') for s in owned}
        plan = do.plan_removals('arista_ceos', before, owned, {'router bgp 65000'}, desired)
        self.assertEqual(plan['remove'], ['router bgp 65000'])

    def test_negated_leaf_is_removed_with_default_and_side_effects_are_kept(self):
        before = {'interface Ethernet1', 'interface Ethernet1 > no switchport', 'interface Ethernet1 > ip address 10.0.0.1/30', 'interface Ethernet1 > description manual'}
        owned = {'interface Ethernet1 > no switchport', 'interface Ethernet1 > ip address 10.0.0.1/30'}
        plan = do.plan_removals('arista_ceos', before, owned, set(), desired=set())
        self.assertEqual(plan['kept_manual'], ['interface Ethernet1 > no switchport'], 'switchport back would strip the manual description holder; kept and reported')
        self.assertEqual(plan['leaves'], ['interface Ethernet1 > ip address 10.0.0.1/30'])
        plan2 = do.plan_removals('arista_ceos', {'interface Ethernet1', 'interface Ethernet1 > no switchport'}, {'interface Ethernet1 > no switchport'}, set(), desired=set())
        self.assertEqual(do.render_removals('arista_ceos', plan2), ['interface Ethernet1', ' default switchport', '!'])

    def test_admin_state_is_never_re_applied(self):
        before = {'interface GigabitEthernet0/0/0/0', 'interface GigabitEthernet0/0/0/0 > no shutdown', 'interface GigabitEthernet0/0/0/0 > ipv4 address 10.0.0.10 255.255.255.252'}
        owned = {'interface GigabitEthernet0/0/0/0 > no shutdown', 'interface GigabitEthernet0/0/0/0 > ipv4 address 10.0.0.10 255.255.255.252'}
        plan = do.plan_removals('cisco_xrv9k', before, owned, set(), desired=set())
        self.assertEqual(plan['skipped'], ['interface GigabitEthernet0/0/0/0 > no shutdown'])
        self.assertEqual(do.render_removals('cisco_xrv9k', plan), ['interface GigabitEthernet0/0/0/0', ' no ipv4 address 10.0.0.10 255.255.255.252', '!'])

    def test_junos_peer_removal_deletes_the_created_ancestor_not_three_leaves(self):
        before = {'set protocols bgp group ibgp type internal',
                  'set protocols bgp group ibgp neighbor 10.255.0.1 local-address 10.255.0.2',
                  'set protocols bgp group ibgp neighbor 10.255.0.1 description ceos',
                  'set protocols bgp group ibgp neighbor 10.255.0.1 family inet unicast',
                  'set protocols bgp group ibgp neighbor 10.255.0.4 description xrv9k'}
        owned = set(before)
        anc = do.created_ancestors('juniper_cjunosevolved', before, set())
        self.assertIn('set protocols bgp group ibgp neighbor 10.255.0.1', anc)
        desired = {s for s in before if '10.255.0.1' not in s}
        plan = do.plan_removals('juniper_cjunosevolved', before, owned, anc, desired)
        self.assertEqual(plan['remove'], ['set protocols bgp group ibgp neighbor 10.255.0.1'])
        self.assertEqual(plan['leaves'], [])
        self.assertEqual(do.render_removals('juniper_cjunosevolved', plan), ['delete protocols bgp group ibgp neighbor 10.255.0.1'])

    def test_junos_dropping_the_whole_protocol_deletes_at_the_top(self):
        before = {'set protocols ospf area 0.0.0.0 interface lo0.0', 'set protocols ospf area 0.0.0.0 interface et-0/0/0.0 interface-type p2p', 'set interfaces et-0/0/0 unit 0 family inet address 10.0.0.2/30'}
        anc = do.created_ancestors('juniper_cjunosevolved', before, {'set system host-name x'})
        plan = do.plan_removals('juniper_cjunosevolved', before, before, anc, desired={'set interfaces et-0/0/0 unit 0 family inet address 10.0.0.2/30'})
        self.assertEqual(plan['remove'], ['set protocols'])
        self.assertEqual(do.render_removals('juniper_cjunosevolved', plan), ['delete protocols'])

    def test_eos_neighbour_with_a_manual_line_is_removed_line_by_line(self):
        before = do.statements('arista_ceos', EOS_WOULD_BE) | {'router bgp 65000 > neighbor 10.255.0.3 description manual',
                                                               'router bgp 65000 > address-family ipv4', 'router bgp 65000 > address-family ipv4 > neighbor 10.255.0.3 activate'}
        owned = {'router bgp 65000 > neighbor 10.255.0.3 remote-as 65000', 'router bgp 65000 > address-family ipv4 > neighbor 10.255.0.3 activate'}
        plan = do.plan_removals('arista_ceos', before, owned, set(), desired=set())
        self.assertNotIn('router bgp 65000 > neighbor 10.255.0.3', plan['leaves'], 'a manual line of the neighbour keeps it: no `no neighbor X`')
        self.assertEqual(sorted(plan['leaves']), sorted(owned))
        rendered = do.render_removals('arista_ceos', plan)
        self.assertIn('  no neighbor 10.255.0.3 activate', rendered); self.assertIn(' no neighbor 10.255.0.3 remote-as 65000', rendered)

    def test_eos_address_family_removed_whole_drops_its_network_statements_by_name_first(self):
        # Live fact: `no address-family ipv4` keeps the family's `network` statements at the process level.
        extra = {'router bgp 65000 > address-family ipv4', 'router bgp 65000 > address-family ipv4 > network 10.255.0.1/32',
                 'router bgp 65000 > address-family ipv4 > network 172.16.0.0/24', 'router bgp 65000 > address-family ipv4 > neighbor 10.255.0.2 activate',
                 'router bgp 65000 > neighbor 10.9.9.9 remote-as 65009'}
        before = do.statements('arista_ceos', EOS_WOULD_BE) | extra
        owned = {s for s in before if s.startswith('router bgp') and '10.9.9.9' not in s}
        plan = do.plan_removals('arista_ceos', before, owned, {'router bgp 65000', 'router bgp 65000 > address-family ipv4'}, desired=set())
        self.assertEqual(plan['remove'], ['router bgp 65000 > address-family ipv4'])
        self.assertEqual(plan['leaves'][:2], ['router bgp 65000 > address-family ipv4 > network 10.255.0.1/32', 'router bgp 65000 > address-family ipv4 > network 172.16.0.0/24'])
        rendered = do.render_removals('arista_ceos', plan)
        self.assertLess(rendered.index('  no network 10.255.0.1/32'), rendered.index(' no address-family ipv4'), 'networks go before the family')
        self.assertIn(' no neighbor 10.255.0.2', rendered, 'the whole neighbour goes in one command, its activate line with it')
        self.assertNotIn('  no neighbor 10.255.0.2 activate', rendered)

    def test_junos_blocks_and_created_ancestors_limited_to_real_containers(self):
        tree = ("interfaces {\n    et-0/0/0 {\n        unit 0 {\n            family inet {\n                address 10.1.0.1/31;\n            }\n        }\n    }\n"
                "    lo0.0 {\n        family inet {\n            address 10.255.0.2/32;\n        }\n    }\n}\nprotocols {\n    delete: bgp;\n    bgp {\n"
                "        group ibgp-peers-ipv4 {\n            type internal;\n            neighbor 10.255.0.1 {\n                description ceos;\n            }\n        }\n    }\n"
                "    inactive: lldp {\n        interface all;\n    }\n}\n")
        blocks = do.junos_blocks(tree)
        self.assertIn('set interfaces lo0 unit 0 family inet', blocks, 'the X.N shorthand becomes interface and unit')
        self.assertIn('set interfaces lo0', blocks)
        self.assertIn('set protocols bgp group ibgp-peers-ipv4 neighbor 10.255.0.1', blocks)
        self.assertIn('set protocols lldp', blocks, 'inactive blocks are blocks')
        self.assertNotIn('set protocols bgp group ibgp-peers-ipv4 neighbor', blocks, 'a keyword-only level is not a block')
        self.assertNotIn('set protocols bgp group', blocks)
        added = {'set protocols bgp group ibgp-peers-ipv4 type internal', 'set protocols bgp group ibgp-peers-ipv4 neighbor 10.255.0.1 description ceos'}
        before = {'set protocols lldp interface all', 'set interfaces lo0 unit 0 family inet address 10.255.0.2/32'}
        anc = do.created_ancestors('juniper_vjunosswitch', added, before, blocks)
        self.assertEqual(anc, {'set protocols bgp', 'set protocols bgp group ibgp-peers-ipv4', 'set protocols bgp group ibgp-peers-ipv4 neighbor 10.255.0.1'})
        unlimited = do.created_ancestors('juniper_vjunosswitch', added, before)
        self.assertIn('set protocols bgp group ibgp-peers-ipv4 neighbor', unlimited, 'without the device blocks every word prefix counts')

    def test_xr_typed_negations_are_verified_as_absence(self):
        desired = {'interface Loopback0 > ipv4 address 10.255.0.4 255.255.255.255', 'interface Loopback0 > no shutdown', 'lldp > no management enable'}
        after = {'interface Loopback0', 'interface Loopback0 > ipv4 address 10.255.0.4 255.255.255.255', 'lldp'}
        self.assertEqual(do.verify('cisco_xrv9k', after, desired, stale=set()), ([], []), 'the running configuration never shows `no shutdown`')
        still_down = after | {'interface Loopback0 > shutdown'}
        self.assertEqual(do.verify('cisco_xrv9k', still_down, desired, stale=set()), ([], ['interface Loopback0 > shutdown']))
        present, absent = do.split_negations('arista_ceos', {'interface Ethernet1 > no switchport'})
        self.assertEqual((present, absent), ({'interface Ethernet1 > no switchport'}, set()), 'EOS renders its desired set itself: nothing to translate')

    def test_takeover_leftovers_are_the_conflicts_a_merge_leaves_in_place(self):
        conflicts = {'interface Ethernet2 > ipv6 address 2001:db8:9::1/64', 'interface Ethernet2 > ip address 10.9.0.0/31'}
        would_be = {'interface Ethernet2 > ipv6 address 2001:db8:9::1/64', 'interface Ethernet2 > ipv6 address 2001:db8:1:1::1/64', 'interface Ethernet2 > ip address 10.1.0.2/31'}
        self.assertEqual(do.takeover_leftovers(conflicts, would_be), ['interface Ethernet2 > ipv6 address 2001:db8:9::1/64'], 'the replaced IPv4 address needs nothing; the second IPv6 address must be removed')
        self.assertEqual(do.render_removals('arista_ceos', {'leaves': do.takeover_leftovers(conflicts, would_be), 'remove': []}), ['interface Ethernet2', ' no ipv6 address 2001:db8:9::1/64', '!'])

    def test_after_apply_and_verify(self):
        owned = {'a > b', 'a > c'}; added = {'a > d', 'x > y'}; after = {'a > b', 'a > d', 'x > y', 'z'}
        self.assertEqual(do.after_apply('arista_ceos', owned, added, after), {'a > b', 'a > d', 'x > y'})
        missing, remaining = do.verify('arista_ceos', after, desired={'a > d', 'q'}, stale={'a > c'}, removed_ancestors=['r'])
        self.assertEqual((missing, remaining), (['q'], []))
        missing, remaining = do.verify('arista_ceos', after | {'r > s'}, desired=set(), stale={'a > b'}, removed_ancestors=['r'])
        self.assertEqual(remaining, ['a > b', 'r > s'])
        missing, remaining = do.verify('arista_ceos', after | {'r > s'}, desired={'r > s'}, stale=set(), removed_ancestors=['r'])
        self.assertEqual(remaining, [], 'what the design put back under a removed container is not a leftover')


if __name__ == '__main__':
    unittest.main()
