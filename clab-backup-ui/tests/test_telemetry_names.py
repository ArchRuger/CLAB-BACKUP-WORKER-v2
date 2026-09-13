"""Interface alias mapping: containerlab endpoints, imported aliases and NOS telemetry names."""
import unittest

from app.telemetry_names import endpoint_candidates, interface_role, nos_interface, physical_name


class NameMappingTests(unittest.TestCase):
    def test_ceos_ports_follow_the_eth_to_ethernet_rule(self):
        self.assertEqual(nos_interface('arista_ceos', 'eth1'), 'Ethernet1')
        self.assertEqual(nos_interface('arista_ceos', 'eth1_1'), 'Ethernet1/1')
        self.assertEqual(nos_interface('arista_ceos', 'et2'), 'Ethernet2')
        self.assertEqual(nos_interface('arista_ceos', 'ethernet3'), 'Ethernet3')
        self.assertEqual(nos_interface('arista_ceos', 'Ma0'), 'Management0')
        self.assertEqual(nos_interface('arista_ceos', 'Gi0/0/0/1'), '', 'an XR alias is not guessed on cEOS')

    def test_xrv9k_eth1_is_the_first_gigabit_port(self):
        self.assertEqual(nos_interface('cisco_xrv9k', 'eth1'), 'GigabitEthernet0/0/0/0')
        self.assertEqual(nos_interface('cisco_xrv9k', 'eth2'), 'GigabitEthernet0/0/0/1')
        self.assertEqual(nos_interface('cisco_xrv9k', 'Gi0/0/0/3'), 'GigabitEthernet0/0/0/3')
        self.assertEqual(nos_interface('cisco_xrv9k', 'GigabitEthernet0/0/0/3'), 'GigabitEthernet0/0/0/3')
        self.assertEqual(nos_interface('cisco_xrv9k', 'Te0/0/0/1'), 'TenGigE0/0/0/1')
        self.assertEqual(nos_interface('cisco_xrv9k', 'eth0'), '', 'eth0 is the container side of management')

    def test_cjunosevolved_reserves_eth1_to_eth3(self):
        for reserved in ('eth1', 'eth2', 'eth3'):
            self.assertEqual(nos_interface('juniper_cjunosevolved', reserved), '', reserved)
        self.assertEqual(nos_interface('juniper_cjunosevolved', 'eth4'), 'et-0/0/0')
        self.assertEqual(nos_interface('juniper_cjunosevolved', 'eth8'), 'et-0/0/4')
        self.assertEqual(nos_interface('juniper_cjunosevolved', 'et-0/0/1'), 'et-0/0/1')
        self.assertEqual(nos_interface('juniper_cjunosevolved', 'et-0/0/1.0'), 'et-0/0/1', 'logical units fold onto the port')
        self.assertEqual(physical_name('juniper_cjunosevolved', 'et-0/0/2.0'), 'et-0/0/2')

    def test_unknown_kinds_and_forms_never_guess(self):
        self.assertEqual(nos_interface('linux', 'eth1'), '')
        self.assertEqual(nos_interface('arista_ceos', ''), '')
        self.assertEqual(nos_interface('arista_ceos', None), '')
        self.assertEqual(endpoint_candidates('cisco_xrv9k', 'eth1'), ['GigabitEthernet0/0/0/0', 'eth1'])
        self.assertEqual(endpoint_candidates('linux', 'eth1'), ['eth1'])

    def test_roles_group_management_and_physical_ports(self):
        self.assertEqual(interface_role('arista_ceos', 'Ethernet1'), 'physical')
        self.assertEqual(interface_role('arista_ceos', 'Management0'), 'management')
        self.assertEqual(interface_role('arista_ceos', 'Vlan10'), 'other')
        self.assertEqual(interface_role('cisco_xrv9k', 'MgmtEth0/RP0/CPU0/0'), 'management')
        self.assertEqual(interface_role('cisco_xrv9k', 'Null0'), 'other')
        self.assertEqual(interface_role('juniper_cjunosevolved', 're0:mgmt-0'), 'management')
        self.assertEqual(interface_role('juniper_cjunosevolved', 'et-0/0/0.0'), 'physical')
        self.assertEqual(interface_role('juniper_cjunosevolved', 'pfe-0/0/0'), 'other')


if __name__ == '__main__':
    unittest.main()
