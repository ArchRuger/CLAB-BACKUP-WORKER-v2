"""Tests for app/design_provision.py: what a generated fragment may reach a device with.

The fixtures are the shapes netlab 26.09 renders for the acceptance topology (docs/netlab-integration/
PROVISIONING.md §1 and §7); the rules are asserted on them, statement by statement.
"""
import unittest

from app import design_provision as dp

EOS_INITIAL = '''hostname ceos
!
logging monitor debugging
aaa authorization exec default local
!
lldp run
ip routing
ipv6 unicast-routing
!
!
ip host cjunosevolved 10.255.0.2 10.0.0.2 10.0.0.5
ipv6 host cjunosevolved 2001:db8:ff:2::1
!
interface Management1
 no lldp transmit
 no lldp receive
!
interface Loopback0
 ip address 10.255.0.1/32
 ipv6 address 2001:db8:ff:1::1/64
!
interface Ethernet1
 no switchport
 description ceos -> cjunosevolved
 ip address 10.0.0.1/30
 ipv6 nd ra interval 5
 ipv6 address 2001:db8:1::1/64
 mac-address caf0.0001.0001
!
 no shutdown
!
'''
EOS_NORMALIZE = '!\ninterface Ethernet1\n shutdown\n mac-address caf0.0001.0001\n'
EOS_OSPF = '''!
! OSPFv2 configuration
!
router ospf 1
 router-id 10.255.0.1
 passive-interface Ethernet3
!
interface Ethernet1
! ceos -> cjunosevolved
 ip ospf area 0.0.0.0
 ip ospf network point-to-point
!
'''
XR_INITIAL = '''hostname xrv9k
!
domain lookup disable
!
lldp
 no management enable
!
domain ipv4 host ceos 10.255.0.1
domain ipv6 host ceos 2001:db8:ff:1::1
!
interface Loopback0
 no shutdown
 ipv4 address 10.255.0.4 255.255.255.255
!
interface GigabitEthernet0/0/0/0
 no shutdown
 description xrv9k -> vjunos-switch
 ipv4 address 10.0.0.10 255.255.255.252
!
'''
XR_OSPF = '''!
router ospf 1
!
! These throttle timers are probably too aggressive for a production network but
! make labs run better ;)
!
 log adjacency changes
 router-id 10.255.0.4
 area 0.0.0.0
  interface Loopback0
  interface GigabitEthernet0/0/0/0
   network point-to-point
'''
JUNOS_INITIAL = '''system {
  host-name cjunosevolved;
  static-host-mapping {
    ceos inet 10.255.0.1;
    xrv9k inet 10.255.0.4;
  }
}

interfaces {

  lo0.0 {

      family inet {
        address 10.255.0.2/32;
      }
  }
  et-0/0/0.0 {
    description "cjunosevolved -> ceos";
      family inet {
        address 10.0.0.2/30;
      }
  }
}
protocols {
  lldp {
    interface re0:mgmt-0 {
      disable;
    }
    interface all;
  }
}'''
JUNOS_OSPF = '''routing-options {
  router-id 10.255.0.2
}
protocols {
  delete: ospf;
}

protocols {
  ospf {
    area 0.0.0.0 {
      interface lo0.0 {
      }
    }
    area 0.0.0.0 {
      interface et-0/0/0.0 {
        interface-type p2p;
      }
    }
  }
}
'''
JUNOS_BGP = '''policy-options {
  delete: policy-statement next-hop-ebgp-ipv4;
  delete: route-filter-list bgp-default-announce-ipv4;

  policy-statement bgp-final {
    term final-option {
      then {
        accept;
      }
    }
  }
}
protocols {
  delete: bgp;
}
protocols {
  bgp {
    group ibgp-peers-ipv4 {
      type internal;
      neighbor 10.255.0.1 {
        local-address 10.255.0.2;
        description ceos;
      }
    }
  }
}'''

# A risk-review hardening probe: every gap it found (Junos block-form root-authentication, radius-server,
# tacplus-server, authentication-order, management-instance, the mgmt_junos routing instance; EOS
# tacacs-server/radius-server/snmp-server) alongside legitimate design lines that must stay.
EOS_HARDENING = '''hostname ceos
!
tacacs-server host 10.0.0.5 key 7 0102030405
!
radius-server host 10.0.0.6 key 7 0102030405
!
snmp-server community public RO
!
interface Ethernet2
 no switchport
 ip address 10.0.0.9/30
!
router bgp 65000
 neighbor 10.0.0.10 remote-as 65001
!
'''
XR_HARDENING = '''hostname xrv9k
!
tacacs-server host 10.0.0.5 key clear 0102030405
!
radius-server host 10.0.0.6 key clear 0102030405
!
snmp-server community public RO
!
interface GigabitEthernet0/0/0/1
 no shutdown
 ipv4 address 10.0.0.13 255.255.255.252
!
router bgp 65000
 bgp router-id 10.255.0.4
 neighbor 10.0.0.14
  remote-as 65001
 !
!
'''
JUNOS_HARDENING = '''system {
  root-authentication {
    encrypted-password "$6$abc$defghijklmnop";
  }
  radius-server {
    10.0.0.5 {
      secret "$9$abc123";
    }
  }
  tacplus-server {
    10.0.0.6 {
      secret "$9$def456";
    }
  }
  login {
    user netops {
      class super-user;
    }
  }
  services {
    ssh;
  }
  syslog {
    host 10.0.0.7 {
      any any;
    }
  }
  name-server 10.0.0.8;
  authentication-order radius;
  management-instance;
}
routing-instances {
  mgmt_junos {
    routing-options {
      static {
        route 0.0.0.0/0 next-hop 172.20.20.1;
      }
    }
  }
  CUST-A {
    instance-type vrf;
    interface ge-0/0/1.0;
  }
}
interfaces {
  ge-0/0/2 {
    unit 0 {
      family inet {
        address 10.0.0.13/30;
      }
    }
  }
}
protocols {
  ospf {
    area 0.0.0.0 {
      interface ge-0/0/2.0;
    }
  }
}
'''


class EosTests(unittest.TestCase):
    def test_protected_lines_and_blocks_are_left_out_and_named(self):
        candidate, left = dp.prepare('arista_ceos', [('normalize', EOS_NORMALIZE), ('initial', EOS_INITIAL), ('ospf', EOS_OSPF)])
        statements = [l['statement'] for l in left]
        for expected in ('(whole file)', 'hostname ceos', 'logging monitor debugging', 'aaa authorization exec default local',
                         'ip host cjunosevolved 10.255.0.2 10.0.0.2 10.0.0.5', 'ipv6 host cjunosevolved 2001:db8:ff:2::1',
                         'interface Ethernet1 > mac-address caf0.0001.0001'):
            self.assertIn(expected, statements)
        self.assertIn('interface Management1', statements, 'cEOSLab refuses the LLDP-off lines under its management port: the block is left out')
        self.assertNotIn('Management1', candidate)
        self.assertEqual([l['module'] for l in left if l['statement'] == '(whole file)'], ['normalize'])
        for absent in ('hostname', 'aaa ', 'mac-address', 'ip host', 'logging', 'Management', 'shutdown\n'):
            self.assertNotIn(absent, candidate.replace(' no shutdown', ''), absent)

    def test_what_stays_and_its_order(self):
        candidate, _ = dp.prepare('arista_ceos', [('initial', EOS_INITIAL), ('ospf', EOS_OSPF)])
        lines = [l for l in candidate.splitlines() if l != '!']
        self.assertEqual(lines[:3], ['lldp run', 'ip routing', 'ipv6 unicast-routing'])
        self.assertIn('interface Ethernet1', lines)
        block = candidate[candidate.index('interface Ethernet1'):candidate.index('router ospf 1')]
        self.assertIn(' ip address 10.0.0.1/30', block)
        self.assertIn(' no switchport', block)
        self.assertLess(candidate.index('router ospf 1'), candidate.index(' ip ospf area 0.0.0.0'), 'the ospf fragment follows the initial one')

    def test_comments_do_not_split_a_block(self):
        candidate, _ = dp.prepare('arista_ceos', [('ospf', EOS_OSPF)])
        self.assertIn('interface Ethernet1\n ip ospf area 0.0.0.0\n ip ospf network point-to-point\n!', candidate)
        self.assertNotIn('! ceos', candidate)

    def test_tacacs_radius_and_snmp_are_left_out_with_design_lines_kept(self):
        candidate, left = dp.prepare('arista_ceos', [('hardening', EOS_HARDENING)])
        statements = [l['statement'] for l in left]
        for expected in ('hostname ceos', 'tacacs-server host 10.0.0.5 key 7 0102030405',
                         'radius-server host 10.0.0.6 key 7 0102030405', 'snmp-server community public RO'):
            self.assertIn(expected, statements)
        for absent in ('tacacs-server', 'radius-server', 'snmp-server', 'hostname'):
            self.assertNotIn(absent, candidate, absent)
        self.assertIn('interface Ethernet2', candidate)
        self.assertIn(' ip address 10.0.0.9/30', candidate)
        self.assertIn('router bgp 65000', candidate)
        self.assertIn(' neighbor 10.0.0.10 remote-as 65001', candidate)


class IosXrTests(unittest.TestCase):
    def test_protected_lines_and_comment_bodies(self):
        candidate, left = dp.prepare('cisco_xrv9k', [('initial', XR_INITIAL), ('ospf', XR_OSPF)])
        statements = [l['statement'] for l in left]
        for expected in ('hostname xrv9k', 'domain ipv4 host ceos 10.255.0.1', 'domain ipv6 host ceos 2001:db8:ff:1::1'):
            self.assertIn(expected, statements)
        self.assertIn('lldp\n no management enable\n!', candidate, 'the global LLDP statement is not a management interface')
        self.assertIn('domain lookup disable', candidate)
        self.assertIn('router ospf 1\n log adjacency changes\n router-id 10.255.0.4\n area 0.0.0.0\n  interface Loopback0\n  interface GigabitEthernet0/0/0/0\n   network point-to-point\n!', candidate,
                      'the comment lines between the header and the body do not detach the body')
        self.assertNotIn('hostname', candidate)

    def test_design_static_routes_stay_but_the_management_vrf_is_protected(self):
        text = 'router static\n address-family ipv4 unicast\n  10.9.0.0/24 10.1.0.1\n !\n vrf clab-mgmt\n  address-family ipv4 unicast\n   0.0.0.0/0 172.20.20.1\n  !\n !\n!\nvrf clab-mgmt\n description Containerlab management VRF\n!\n'
        candidate, left = dp.prepare('cisco_xrv9k', [('routing', text)])
        self.assertIn('router static\n address-family ipv4 unicast\n  10.9.0.0/24 10.1.0.1\n!', candidate)
        self.assertNotIn('172.20.20.1', candidate)
        self.assertNotIn('description Containerlab', candidate)
        self.assertEqual([l['statement'] for l in left], ['router static > vrf clab-mgmt', 'vrf clab-mgmt'])

    def test_a_management_interface_block_is_left_out(self):
        candidate, left = dp.prepare('cisco_xrv9k', [('initial', 'interface MgmtEth0/RP0/CPU0/0\n ipv4 address 1.1.1.1 255.255.255.0\n!\ninterface Loopback0\n ipv4 address 2.2.2.2 255.255.255.255\n')])
        self.assertEqual([l['statement'] for l in left], ['interface MgmtEth0/RP0/CPU0/0'])
        self.assertNotIn('1.1.1.1', candidate)
        self.assertIn('interface Loopback0\n ipv4 address 2.2.2.2 255.255.255.255\n!', candidate)

    def test_tacacs_radius_and_snmp_are_left_out_with_design_lines_kept(self):
        candidate, left = dp.prepare('cisco_xrv9k', [('hardening', XR_HARDENING)])
        statements = [l['statement'] for l in left]
        for expected in ('hostname xrv9k', 'tacacs-server host 10.0.0.5 key clear 0102030405',
                         'radius-server host 10.0.0.6 key clear 0102030405', 'snmp-server community public RO'):
            self.assertIn(expected, statements)
        for absent in ('tacacs-server', 'radius-server', 'snmp-server', 'hostname'):
            self.assertNotIn(absent, candidate, absent)
        self.assertIn('interface GigabitEthernet0/0/0/1', candidate)
        self.assertIn(' ipv4 address 10.0.0.13 255.255.255.252', candidate)
        self.assertIn('router bgp 65000', candidate)
        self.assertIn('  remote-as 65001', candidate)


class JunosTests(unittest.TestCase):
    def test_identity_mapping_management_lldp_and_delete_tags_are_left_out(self):
        candidate, left = dp.prepare('juniper_cjunosevolved', [('initial', JUNOS_INITIAL), ('ospf', JUNOS_OSPF), ('bgp', JUNOS_BGP)])
        statements = [l['statement'] for l in left]
        for expected in ('host-name cjunosevolved;', 'static-host-mapping', 'delete: ospf;', 'delete: bgp;',
                         'delete: policy-statement next-hop-ebgp-ipv4;', 'delete: route-filter-list bgp-default-announce-ipv4;'):
            self.assertIn(expected, statements)
        for absent in ('host-name', 'static-host-mapping', 'delete:', 'inet 10.255.0.4'):
            self.assertNotIn(absent, candidate, absent)
        self.assertNotIn('system {', candidate, 'an emptied system block is dropped')
        self.assertIn('    interface re0:mgmt-0 {\n      disable;\n    }\n    interface all;', candidate, 'LLDP stays off the management network')
        self.assertIn('      interface lo0.0 {\n      }', candidate, 'a presence block is meaningful and stays')
        self.assertIn('        address 10.0.0.2/30;', candidate)
        self.assertIn('      interface et-0/0/0.0 {\n        interface-type p2p;\n      }', candidate)
        self.assertIn('  policy-statement bgp-final {', candidate)
        self.assertIn('      neighbor 10.255.0.1 {', candidate)
        self.assertEqual(candidate.count('{'), candidate.count('}'), 'braces stay balanced')

    def test_the_same_rules_apply_to_vjunos_switch_and_a_management_block_elsewhere_is_protected(self):
        candidate, left = dp.prepare('juniper_vjunosswitch', [('initial', JUNOS_INITIAL.replace('re0:mgmt-0', 'fxp0') + '\ninterfaces {\n  fxp0 {\n    unit 0 {\n      family inet {\n        address 10.0.0.9/24;\n      }\n    }\n  }\n}\n')])
        self.assertIn('interface fxp0 {\n      disable;', candidate, 'the LLDP-off stays')
        self.assertIn('fxp0', [l['statement'] for l in left], 'an addressed management interface block is protected')
        self.assertNotIn('10.0.0.9', candidate)

    def test_hardening_gaps_are_left_out_with_design_lines_and_the_customer_vrf_kept(self):
        candidate, left = dp.prepare('juniper_cjunosevolved', [('hardening', JUNOS_HARDENING)])
        statements = [l['statement'] for l in left]
        for expected in ('root-authentication', 'radius-server', 'tacplus-server', 'login', 'services', 'syslog',
                         'name-server 10.0.0.8;', 'authentication-order radius;', 'management-instance;', 'mgmt_junos'):
            self.assertIn(expected, statements)
        for absent in ('root-authentication', 'encrypted-password', 'radius-server', 'tacplus-server', 'secret',
                       'super-user', 'ssh;', 'syslog', 'name-server', 'authentication-order', 'management-instance',
                       'mgmt_junos', '172.20.20.1'):
            self.assertNotIn(absent, candidate, absent)
        self.assertNotIn('system {', candidate, 'an emptied system block is dropped')
        self.assertIn('routing-instances {', candidate, 'the customer VRF keeps the parent block alive')
        self.assertIn('  CUST-A {', candidate)
        self.assertIn('    instance-type vrf;', candidate)
        self.assertIn('    interface ge-0/0/1.0;', candidate)
        self.assertIn('        address 10.0.0.13/30;', candidate, 'the design interface stays')
        self.assertIn('      interface ge-0/0/2.0;', candidate, 'the design OSPF interface stays')
        self.assertEqual(candidate.count('{'), candidate.count('}'), 'braces stay balanced')

    def test_a_kind_without_a_driver_is_refused(self):
        with self.assertRaises(KeyError):
            dp.prepare('nokia_srlinux', [('initial', 'x')])


if __name__ == '__main__':
    unittest.main()
