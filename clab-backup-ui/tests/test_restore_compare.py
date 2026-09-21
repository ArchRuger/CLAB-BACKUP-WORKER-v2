"""Unit tests for desired-state comparison: app/restore_compare.py and app/restore_drivers.py.

Replacement means configuration introduced after the desired state was captured is removed, and
comparison never hides a leftover: every assertion here pins that a statement present only on one
side is reported, that hierarchy (which parent a line sits under) is part of the statement's
identity, and that only the exclusions the modules document (comments, header timestamps, the
mandatory Junos root-authentication and `set version`) are ever tolerated.
"""
import re
import unittest

from app import restore_drivers, restore_eos, restore_junos
from app.restore_compare import (EOS_ORDERED, compare_indented, compare_junos, indented_statements,
                                  ordered_blocks_differ, set_lines)
from app.restore_shell import RestoreError


# --- indented_statements ---------------------------------------------------------------------

class IndentedStatementsTests(unittest.TestCase):
    def test_same_child_line_under_two_parents_is_two_statements(self):
        text = 'interface Ethernet1\n   no switchport\ninterface Ethernet2\n   no switchport\n'
        self.assertEqual(indented_statements(text),
                          ['interface Ethernet1', 'interface Ethernet1 > no switchport',
                           'interface Ethernet2', 'interface Ethernet2 > no switchport'])

    def test_line_moved_between_parents_is_one_missing_and_one_extra(self):
        desired = 'interface Ethernet1\n   description X\ninterface Ethernet2\n'
        actual = 'interface Ethernet1\ninterface Ethernet2\n   description X\n'
        self.assertEqual(compare_indented(desired, actual),
                          (['interface Ethernet1 > description X'],
                           ['interface Ethernet2 > description X']))

    def test_three_levels_of_nesting(self):
        text = 'router bgp 65000\n   vrf CUSTOMER\n      neighbor 10.0.0.1 remote-as 65001\n'
        self.assertEqual(indented_statements(text),
                          ['router bgp 65000',
                           'router bgp 65000 > vrf CUSTOMER',
                           'router bgp 65000 > vrf CUSTOMER > neighbor 10.0.0.1 remote-as 65001'])

    def test_comments_blank_lines_and_final_end_dropped_but_indented_end_kept(self):
        # A banner body can contain the literal word "end", once inside a longer line and once by
        # itself; both are indented (part of the block) and neither is the closing top-level `end`
        # that `show running-config` appends, so both must survive.
        text = ('banner motd\n'
                '   end of text\n'
                '   end\n'
                '!\n'
                '\n'
                'hostname ceos\n'
                '!\n'
                'end\n')
        self.assertEqual(indented_statements(text),
                          ['banner motd', 'banner motd > end of text', 'banner motd > end',
                           'hostname ceos'])


# --- compare_indented --------------------------------------------------------------------------

class CompareIndentedTests(unittest.TestCase):
    def test_identical_texts_have_no_difference(self):
        text = ('! Command: show running-config\nhostname ceos\n!\n'
                'interface Ethernet1\n   no switchport\n!\nend\n')
        self.assertEqual(compare_indented(text, text), ([], []))

    def test_statement_only_in_actual_is_extra(self):
        # The merge-only leftover this driver exists to catch: a VLAN and a static route that a
        # `load`-style merge would leave behind because it cannot remove anything.
        desired = 'hostname ceos\n!\ninterface Ethernet1\n   no switchport\n!\nend\n'
        actual = ('hostname ceos\n!\nvlan 777\n   name B-ONLY\n!\n'
                  'interface Ethernet1\n   no switchport\n!\n'
                  'ip route 198.51.100.0/24 Null0\n!\nend\n')
        missing, extra = compare_indented(desired, actual)
        self.assertEqual(missing, [])
        self.assertEqual(extra, ['ip route 198.51.100.0/24 Null0', 'vlan 777', 'vlan 777 > name B-ONLY'])

    def test_statement_only_in_desired_is_missing(self):
        desired = 'hostname ceos\n!\nip prefix-list RESTORE-A seq 10 permit 10.255.0.0/24 le 32\n!\nend\n'
        actual = 'hostname ceos\n!\nend\n'
        self.assertEqual(compare_indented(desired, actual),
                          (['ip prefix-list RESTORE-A seq 10 permit 10.255.0.0/24 le 32'], []))

    def test_changed_value_is_one_missing_and_one_extra(self):
        desired = 'interface Ethernet1\n   description A to-cjunosevolved\n!\nend\n'
        actual = 'interface Ethernet1\n   description B changed\n!\nend\n'
        self.assertEqual(compare_indented(desired, actual),
                          (['interface Ethernet1 > description A to-cjunosevolved'],
                           ['interface Ethernet1 > description B changed']))

    def test_header_comments_differing_is_no_difference(self):
        desired = '! Command: show running-config\n! device: ceos\nhostname ceos\n!\nend\n'
        actual = ('! Command: show running-config\n'
                  '! device: ceos (captured 2026-09-20T23:29:59Z)\nhostname ceos\n!\nend\n')
        self.assertEqual(compare_indented(desired, actual), ([], []))

    def test_trailing_whitespace_is_ignored(self):
        desired = 'hostname ceos   \n!\nend\n'
        actual = 'hostname ceos\n!\nend\n'
        self.assertEqual(compare_indented(desired, actual), ([], []))

    def test_skip_pattern_removes_only_matching_lines(self):
        desired = ('hostname ceos\n!\nntp server 10.0.0.1\n!\n'
                   'interface Ethernet1\n   description X\n!\nend\n')
        actual = ('hostname ceos\n!\nntp server 10.0.0.2\n!\n'
                  'interface Ethernet1\n   description Y\n!\nend\n')
        # Without a skip, both the generated ntp line and the real drift are reported.
        self.assertEqual(compare_indented(desired, actual),
                          (['interface Ethernet1 > description X', 'ntp server 10.0.0.1'],
                           ['interface Ethernet1 > description Y', 'ntp server 10.0.0.2']))
        # With it, only the ntp lines disappear; the interface description drift still shows.
        skip = re.compile(r'^ntp server ')
        self.assertEqual(compare_indented(desired, actual, skip=skip),
                          (['interface Ethernet1 > description X'],
                           ['interface Ethernet1 > description Y']))


# --- ordered_blocks_differ ----------------------------------------------------------------------

ACL_BASE = 'ip access-list TEST\n   10 permit ip any any\n   20 deny ip any any\n!\nend\n'
ACL_REORDERED = 'ip access-list TEST\n   20 deny ip any any\n   10 permit ip any any\n!\nend\n'
ACL_DIFFERENT_CONTENT = ('ip access-list TEST\n   10 permit ip any any\n'
                          '   30 permit ip host 1.2.3.4 any\n!\nend\n')


class OrderedBlocksDifferTests(unittest.TestCase):
    def test_reordered_entries_are_reported(self):
        self.assertEqual(ordered_blocks_differ(ACL_BASE, ACL_REORDERED, EOS_ORDERED), ['ip access-list TEST'])

    def test_same_order_is_not_reported(self):
        self.assertEqual(ordered_blocks_differ(ACL_BASE, ACL_BASE, EOS_ORDERED), [])

    def test_block_with_different_lines_is_not_reported_here(self):
        # A real content change (not just a reorder) is compare_indented's job, not this function's.
        self.assertEqual(ordered_blocks_differ(ACL_BASE, ACL_DIFFERENT_CONTENT, EOS_ORDERED), [])
        missing, extra = compare_indented(ACL_BASE, ACL_DIFFERENT_CONTENT)
        self.assertEqual(missing, ['ip access-list TEST > 20 deny ip any any'])
        self.assertEqual(extra, ['ip access-list TEST > 30 permit ip host 1.2.3.4 any'])


# --- restore_eos.compare ------------------------------------------------------------------------

class RestoreEosCompareTests(unittest.TestCase):
    def test_acl_reorder_reported_as_missing_order(self):
        self.assertEqual(restore_eos.compare(ACL_BASE, ACL_REORDERED), (['(order) ip access-list TEST'], []))

    def test_two_interface_running_config_drift(self):
        # A sanitized two-interface cEOS running-config pair, styled after the live evidence in
        # docs/multi-platform-restore/evidence/10-ceos-restore-A-over-B.json: desired state A vs. a
        # drifted running state B (description changed, a prefix-list removed by drift, an extra
        # VLAN and an extra static route introduced by drift).
        desired = (
            '! Command: show running-config\n'
            '! device: ceos\n'
            '!\n'
            'hostname ceos\n'
            '!\n'
            'username admin secret sha512 <redacted>\n'
            '!\n'
            'vlan 10\n'
            '   name USERS\n'
            '!\n'
            'interface Management0\n'
            '   ip address 172.20.20.101/24\n'
            '!\n'
            'interface Ethernet1\n'
            '   description A to-cjunosevolved\n'
            '   no switchport\n'
            '   ip address 10.0.12.1/31\n'
            '!\n'
            'interface Ethernet2\n'
            '   description A to-vjunos-switch\n'
            '   no switchport\n'
            '   ip address 10.0.41.2/31\n'
            '!\n'
            'interface Loopback0\n'
            '   ip address 10.255.0.1/32\n'
            '!\n'
            'router ospf 1\n'
            '   router-id 10.255.0.1\n'
            '   network 10.0.12.0/31 area 0\n'
            '   network 10.0.41.0/31 area 0\n'
            '   network 10.255.0.1/32 area 0\n'
            '!\n'
            'ip prefix-list RESTORE-A seq 10 permit 10.255.0.0/24 le 32\n'
            '!\n'
            'ip route 172.16.0.0/24 Null0\n'
            '!\n'
            'end\n'
        )
        actual = (
            '! Command: show running-config\n'
            '! device: ceos\n'
            '! device: ceos (captured at 2026-09-20T23:29:59Z)\n'
            '!\n'
            'hostname ceos\n'
            '!\n'
            'username admin secret sha512 <redacted>\n'
            '!\n'
            'vlan 10\n'
            '   name USERS\n'
            '!\n'
            'vlan 777\n'
            '   name B-ONLY\n'
            '!\n'
            'interface Management0\n'
            '   ip address 172.20.20.101/24\n'
            '!\n'
            'interface Ethernet1\n'
            '   description B changed\n'
            '   no switchport\n'
            '   ip address 10.0.12.1/31\n'
            '!\n'
            'interface Ethernet2\n'
            '   description A to-vjunos-switch\n'
            '   no switchport\n'
            '   ip address 10.0.41.2/31\n'
            '!\n'
            'interface Loopback0\n'
            '   ip address 10.255.0.1/32\n'
            '!\n'
            'router ospf 1\n'
            '   router-id 10.255.0.1\n'
            '   network 10.0.12.0/31 area 0\n'
            '   network 10.0.41.0/31 area 0\n'
            '   network 10.255.0.1/32 area 0\n'
            '!\n'
            'ip route 172.16.0.0/24 Null0\n'
            '!\n'
            'ip route 198.51.100.0/24 Null0\n'
            '!\n'
            'end\n'
        )
        missing, extra = restore_eos.compare(desired, actual)
        self.assertEqual(missing, ['interface Ethernet1 > description A to-cjunosevolved',
                                    'ip prefix-list RESTORE-A seq 10 permit 10.255.0.0/24 le 32'])
        self.assertEqual(extra, ['interface Ethernet1 > description B changed',
                                  'ip route 198.51.100.0/24 Null0', 'vlan 777',
                                  'vlan 777 > name B-ONLY'])


# --- compare_junos -------------------------------------------------------------------------------

class CompareJunosTests(unittest.TestCase):
    DESIRED = ('set system host-name r1\n'
               'set interfaces ge-0/0/0 unit 0 family inet address 10.0.0.1/31\n')

    def test_tolerates_extra_root_authentication_and_version_lines(self):
        actual = (self.DESIRED +
                  'set system root-authentication encrypted-password "$6$abc$def"\n' +
                  'set version 21.4R3.15\n')
        self.assertEqual(compare_junos(self.DESIRED, actual), ([], []))

    def test_does_not_tolerate_any_other_extra_line(self):
        actual = self.DESIRED + 'set interfaces ge-0/0/0 unit 0 disable\n'
        self.assertEqual(compare_junos(self.DESIRED, actual),
                          ([], ['set interfaces ge-0/0/0 unit 0 disable']))

    def test_reports_missing_lines(self):
        desired = self.DESIRED + 'set system time-zone UTC\n'
        self.assertEqual(compare_junos(desired, self.DESIRED), (['set system time-zone UTC'], []))

    def test_ignores_comment_lines(self):
        desired = '# generated\nset system host-name r1\n'
        actual = '# generated differently\nset system host-name r1\n'
        self.assertEqual(compare_junos(desired, actual), ([], []))
        self.assertEqual(set_lines(desired), ['set system host-name r1'])


# --- restore_drivers registry --------------------------------------------------------------------

class RegistryTests(unittest.TestCase):
    def test_for_platform_maps_junos_kinds_to_the_junos_driver(self):
        self.assertIs(restore_drivers.for_platform('juniper_cjunosevolved'), restore_junos)
        self.assertIs(restore_drivers.for_platform('juniper_vjunosswitch'), restore_junos)

    def test_for_platform_maps_ceos_to_the_eos_driver(self):
        self.assertIs(restore_drivers.for_platform('arista_ceos'), restore_eos)

    def test_for_platform_xrv9k_today_and_the_flip(self):
        # Today `cisco_xrv9k` has no registered driver (see docs/multi-platform-restore/PICKUP.md,
        # chunk 4). Written so that once a driver is registered for it, this assertion flips to
        # checking the new driver's contract instead of silently passing either way.
        driver = restore_drivers.for_platform('cisco_xrv9k')
        if driver is None:
            self.assertIsNone(driver)
        else:
            self.assertIn('cisco_xrv9k', driver.SUPPORTED_KINDS)

    def test_for_platform_unknown_kind_is_none(self):
        self.assertIsNone(restore_drivers.for_platform('nokia_srlinux'))
        self.assertIsNone(restore_drivers.for_platform(None))

    def test_supported_kinds_is_the_union(self):
        kinds = restore_drivers.supported_kinds()
        self.assertEqual(set(kinds), set(restore_junos.SUPPORTED_KINDS) | set(restore_eos.SUPPORTED_KINDS))
        self.assertEqual(len(kinds), len(restore_junos.SUPPORTED_KINDS) + len(restore_eos.SUPPORTED_KINDS))

    def test_every_registered_driver_exposes_the_whole_contract(self):
        for driver in restore_drivers.DRIVERS:
            self.assertTrue(hasattr(driver, 'SUPPORTED_KINDS'), driver.__name__)
            self.assertTrue(hasattr(driver, 'RESTORE_FORMAT'), driver.__name__)
            for name in ('validate_candidate', 'apply_candidate', 'confirm', 'pending', 'capture', 'compare'):
                self.assertTrue(callable(getattr(driver, name, None)), '%s.%s' % (driver.__name__, name))

    def test_options_returns_enable_password_only_for_eos(self):
        self.assertEqual(restore_drivers.options(restore_eos, {'enable_password': 'zebra'}),
                          {'enable_password': 'zebra'})
        self.assertEqual(restore_drivers.options(restore_eos, {}), {'enable_password': ''})
        self.assertEqual(restore_drivers.options(restore_eos, None), {'enable_password': ''})
        self.assertEqual(restore_drivers.options(restore_junos, {'enable_password': 'zebra'}), {})
        self.assertEqual(restore_drivers.options(restore_junos, {}), {})
        self.assertEqual(restore_drivers.options(restore_junos, None), {})


# --- cross-platform validate_candidate refusal ---------------------------------------------------

JUNOS_CANDIDATE = (
    'system {\n'
    '    host-name SECRET-HOSTNAME-JUNOS;\n'
    '    root-authentication {\n'
    '        encrypted-password "$6$abcdefg$redactedredactedredacted";\n'
    '    }\n'
    '}\n'
    'interfaces {\n'
    '    ge-0/0/0 {\n'
    '        unit 0 {\n'
    '            family inet {\n'
    '                address 10.0.0.1/31;\n'
    '            }\n'
    '        }\n'
    '    }\n'
    '}\n'
)

EOS_CANDIDATE = (
    '! Command: show running-config\n'
    '! device: ceos\n'
    '!\n'
    'hostname SECRET-HOSTNAME-EOS\n'
    '!\n'
    'interface Ethernet1\n'
    '   no switchport\n'
    '!\n'
    'end\n'
)


class ValidateCandidateCrossPlatformTests(unittest.TestCase):
    def test_junos_driver_refuses_an_eos_candidate(self):
        with self.assertRaises(RestoreError) as ctx:
            restore_junos.validate_candidate(EOS_CANDIDATE)
        self.assertNotIn('SECRET-HOSTNAME-EOS', str(ctx.exception))

    def test_eos_driver_refuses_a_junos_candidate(self):
        with self.assertRaises(RestoreError) as ctx:
            restore_eos.validate_candidate(JUNOS_CANDIDATE)
        self.assertNotIn('SECRET-HOSTNAME-JUNOS', str(ctx.exception))

    def test_junos_driver_refuses_empty_text(self):
        for text in ('', '   \n  \n'):
            with self.assertRaises(RestoreError):
                restore_junos.validate_candidate(text)

    def test_eos_driver_refuses_empty_text(self):
        for text in ('', '   \n  \n'):
            with self.assertRaises(RestoreError):
                restore_eos.validate_candidate(text)


if __name__ == '__main__':
    unittest.main()
