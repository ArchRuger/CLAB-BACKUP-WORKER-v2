# B08: traffic through the nested vJunos-router derivative (2026-10-27, live)

Lab `camp-vrt-traffic` on the development VM (VMware guest, nested KVM, 24 vCPU, 72 GB; containerlab 0.79.0):
`h1 (network-multitool) — rtr ge-0/0/0 | ge-0/0/1 — cEOS 4.35.0F Ethernet1 | Ethernet2 — h2 (network-multitool)`,
OSPF area 0 and eBGP 65001/65002 between rtr and cEOS, LLDP, IPv4 and IPv6. `rtr` runs
`n24l/juniper_vjunos-router:26.2R1.7-nested` (image id `c85d25f77631`): the published image with one line of
`/launch.py` changed, `cpu="host"` replaced by the vJunos-switch launcher's fixed IvyBridge model string. The
published image (`sha256:0d039c60…41bb`, `-cpu host`) relaunches every 5 s on this host after the inner qemu 2.7
aborts in `kvm_put_msrs` (lab `vjunous-router-test`, node `rtr1`, 10:53–10:59 UTC); the owner reports the published
image boots on a Proxmox host with the `host` CPU type, so the limitation is the VMware virtual CPU, not "a VM".

Boot: `Startup complete in 0:12:25`, FPC 0 Online 2.5 min later, `ge-0/0/0` and `ge-0/0/1` up with addresses.

## What works (all PASS)

| Check | Result |
|---|---|
| OSPF adjacency rtr–cEOS, routes both ways, LLDP both ways | Full/BDR; `10.2.0.0/24` and `10.255.0.2/32` by OSPF on rtr, `10.1.0.0/24` and `10.255.0.1/32` on cEOS |
| eBGP 65001–65002 | Established, 1 prefix each way |
| ICMP h1→rtr, h1→cEOS (one transit hop), h1→h2 (two hops), h2→h1, rtr→h2 (also sourced from lo0) | 0 % loss |
| 1000 pings at 2 ms interval through the router | 0 % loss, avg 1.6 ms |
| traceroute and mtr h1→h2 (20 probes) | 3 hops, 0 % loss |
| IPv6 h1→rtr, h1→cEOS, h1→h2, traceroute6; 2000-byte IPv6 (Packet Too Big from rtr, then source-fragmented) | pass |
| MTU-sized IPv4 with DF (1472) | pass; 1473 with DF answered `Frag needed and DF set (mtu = 1500)` by `10.1.0.1` |
| IPv4 fragments transit (hosts at MTU 1500): 2000 and 8000 bytes both directions | 0 % loss |
| IPv4 reassembly on the router (h1→rtr, h2→rtr 2000 bytes; rtr→h2 2000, rtr→h1 8000) | 0 % loss; `140 fragments received, 60 packets reassembled ok` |
| Router-side fragmentation (ge-0/0/0 at MTU 9014, h1 at 9000, ge-0/0/1 at 1500): 2000 and 8000 bytes h1→h2; 8000 bytes to rtr | 0 % loss |
| Transit firewall filter counter on ge-0/0/0 (configure, count, delete) | counted; the `L2 and L3 Filters` license warning is cosmetic |
| TCP iperf3 h1→h2 and reverse, 4 streams | about 95 Mbit/s each way |
| UDP iperf3 at 100 Mbit/s | 97.9 Mbit/s received, 2 % loss |
| After the floods: 200 pings at 10 ms, PFE drops, OSPF, BGP | 0 % loss, no PFE drops, both adjacencies up |
| Interface errors on ge-0/0/0 and ge-0/0/1 after all tests | 0 errors, 0 drops (only the 3 intentional MTU errors from oversized frames aimed at the router) |

## What does not work, and why

1. **Throughput is capped at about 98 Mbit/s.** UDP offered at 300 Mbit/s and 1 Gbit/s arrives at 98 Mbit/s with
   67 % and 90 % loss; TCP settles at 95 Mbit/s with retransmits. `show system license` reports `VMX-BANDWIDTH`
   needed, none installed. This is the image's licensing state, not the CPU-model change; the same cap applies on
   any host. The qemu process used about 2 cores during the TCP test.
2. **Oversized frames from containerlab's default 9500-byte Linux veths.** `linux` nodes get MTU 9500 on their lab
   links; the Junos `ge-` interfaces run at 1514/1522 and cEOS forces 1500 on its veths. With the defaults, a
   2000-byte IPv4 ping from a host is dropped either by the host's own veth (`sendmsg: No buffer space available`
   towards cEOS) or by the router's MRU (`MTU errors` on `ge-0/0/0`, one per frame). Setting the hosts' link MTU to
   1500 (or the Junos interface to 9014) removes every such loss. Lab authors should pin `mtu: 1500` on links
   between Linux hosts and the VM kinds; the manager's catalog templates do not set it.

Nothing attributable to the IvyBridge CPU model was found: control plane, forwarding, fragmentation, reassembly,
DF handling and IPv6 behave as a vMX should. The remaining qualification gap for the exact published image is a
host that can boot it (a KVM host with the `host` CPU type, as on Proxmox), not a functional difference.

## Raw output

Produced by the session script (login: the published containerlab.dev default for the kind; not recorded here).

```

=================== A1 router version and forwarding plane (11:14:44Z)
Hostname: rtr
Model: vmx
Family: junos
Junos: 26.2R1.7
JUNOS Juniper Malware Removal Tool (JMRT) [1.0.0+26.2R1.7]
JUNOS na telemetry [26.2R1.7]
Junos scheduler tracing [20260619.173755_builder_junos_262_r1]
JUNOS RPD Telemetry Application [26.2R1.7]
JUNOS Openconfig [26.2R1.7]
JUNOS Broadband Edge User Plane Apps [26.2R1.7]
JUNOS Juniper Malware Removal Tool (JMRT) Test [1.0.0+26.2R1.7]
                     Temp  CPU Utilization (%)   CPU Utilization (%)  Memory    Utilization (%)
Slot State            (C)  Total  Interrupt      1min   5min   15min  DRAM (MB) Heap     Buffer
  0  Online           Testing   8         0        5      1      0    1023       21          0
  1  Empty           
  2  Empty           
  3  Empty           
  4  Empty           
  5  Empty           
  6  Empty           
  7  Empty           
  8  Empty           
  9  Empty           
 10  Empty           
 11  Empty           
1 alarms currently active
Alarm time               Class  Description
2026-10-27 11:13:01 UTC  Minor  "ifstate-tracing-process process is thrashing, not restarted"
2 alarms currently active
Alarm time               Class  Description
2026-10-27 11:13:01 UTC  Minor  "ifstate-tracing-process process is thrashing, not restarted"
2026-10-27 11:12:39 UTC  Minor  Rescue configuration is not set
Hardware inventory:
Item             Version  Part number  Serial number     Description
Chassis                                VM6AE0870017      VMX
Midplane        
Routing Engine 0                                         RE-VMX
CB 0                                                     VMX SCB
FPC 0                     BUILTIN      BUILTIN           Virtual FPC
  CPU            Rev. 1.0 RIOT-LITE    BUILTIN          
  MIC 0                                                  Virtual
    PIC 0                 BUILTIN      BUILTIN           Virtual

=================== A2 interfaces (11:14:50Z)
ge-0/0/0                up    up
ge-0/0/0.0              up    up   inet     10.1.0.1/24     
ge-0/0/1                up    up
ge-0/0/1.0              up    up   inet     10.12.0.1/24    
ge-0/0/2                up    down
ge-0/0/2.16386          up    down
ge-0/0/3                up    down
ge-0/0/3.16386          up    down
ge-0/0/10               up    down
ge-0/0/10.16386         up    down
ge-0/0/11               up    down
ge-0/0/11.16386         up    down
fxp0                    up    up
fxp0.0                  up    up   inet     10.0.0.15/24    
lo0                     up    up
lo0.0                   up    up   inet     10.255.0.1          --> 0/0
lo0.16384               up    up   inet     127.0.0.1           --> 0/0
lo0.16385               up    up   inet    
  Link-level type: Ethernet, MTU: 1514, MRU: 1522, LAN-PHY mode, Speed: 1000mbps, BPDU Error: None, Loop Detect PDU Error: None, Ethernet-Switching Error: None, Remote Bounce: None, MAC-REWRITE Error:
   Output packets:                   11                    0 pps
   Output packets:                    0
  Input errors:
    Errors: 0, Drops: 0, Framing errors: 0, Runts: 0, Policed discards: 0, L3 incompletes: 0, L2 channel errors: 0, L2 mismatch timeouts: 0, FIFO errors: 0, Resource errors: 0
  Output errors:
    Carrier transitions: 1, Errors: 0, Drops: 0, Collisions: 0, Aged packets: 0, FIFO errors: 0, HS link CRC errors: 0, MTU errors: 0, Resource errors: 0
    Bit errors                             0
    CRC/Align errors                         0                0
    FIFO errors                              0                0
    Total errors                             0                0
     Output packets:                   11
     Output packets:                    8
    Output packets:                   11
    Output packets:                    0                    0 pps
     Output packets:                   0                    0 pps
     Output packets:                   0                    0 pps
    Protocol inet, MTU: 1500
    Protocol inet6, MTU: 1500
    Protocol multiservice, MTU: Unlimited, Generation: 166, Route table: 0
  Link-level type: Ethernet, MTU: 1514, MRU: 1522, LAN-PHY mode, Speed: 1000mbps, BPDU Error: None, Loop Detect PDU Error: None, Ethernet-Switching Error: None, Remote Bounce: None, MAC-REWRITE Error:
   Output packets:                   48                    0 pps
   Output packets:                    0
  Input errors:
    Errors: 0, Drops: 0, Framing errors: 0, Runts: 0, Policed discards: 0, L3 incompletes: 0, L2 channel errors: 0, L2 mismatch timeouts: 0, FIFO errors: 0, Resource errors: 0
  Output errors:
    Carrier transitions: 1, Errors: 0, Drops: 0, Collisions: 0, Aged packets: 0, FIFO errors: 0, HS link CRC errors: 0, MTU errors: 0, Resource errors: 0
    Bit errors                             0
    CRC/Align errors                         0                0
    FIFO errors                              0                0
    Total errors                             0                0
     Output packets:                   48
     Output packets:                   11
    Output packets:                   48
    Output packets:                    0                    0 pps
     Output packets:                   0                    0 pps
     Output packets:                   0                    0 pps
    Protocol inet, MTU: 1500
    Protocol inet6, MTU: 1500
    Protocol multiservice, MTU: Unlimited, Generation: 169, Route table: 0

=================== A3 pfe counters before (11:14:53Z)
    Input  packets:                  404                    0 pps
    Output packets:                   59                    0 pps
    Fabric Input  :                    0                    0 pps 
    Fabric Output :                    0                    0 pps 
    Local packets input                 :                   33
    Local packets output                :                  118   
    Software input control plane drops  :                    0
    Software input high drops           :                    0
    Software input medium drops         :                    0
    Software input low drops            :                    0
    Software output drops               :                    0
    Hardware input drops                :                    0
    Info cell drops            :                    0
    Fabric drops               :                    0
Packet Forwarding Engine Input IPv4 Header Checksum Error and Output MTU Error statistics:
    Input Checksum             :                    0
    Output MTU                 :                    0

=================== B1 control plane: OSPF, BGP, LLDP on the router (11:14:54Z)
Address          Interface              State           ID               Pri  Dead
10.12.0.2        ge-0/0/1.0             Full            10.255.0.2         1    32
Interface           State   Area            DR ID           BDR ID          Nbrs
ge-0/0/0.0          DRother 0.0.0.0         0.0.0.0         0.0.0.0            0
ge-0/0/1.0          BDR     0.0.0.0         10.255.0.2      10.255.0.1         1
lo0.0               DRother 0.0.0.0         0.0.0.0         0.0.0.0            0
Threading mode: BGP I/O
Default eBGP mode: advertise - accept, receive - accept
Groups: 1 Peers: 1 Down peers: 0
Table          Tot Paths  Act Paths Suppressed    History Damp State    Pending
inet.0               
                       1          0          0          0          0          0
Peer                     AS      InPkt     OutPkt    OutQ   Flaps Last Up/Dwn State|#Active/Received/Accepted/Damped...
10.12.0.2             65002          6          3       0       0          52 Establ
  inet.0: 0/1/1/0
Local Interface    Parent Interface    Chassis Id                               Port info          System Name
ge-0/0/1           -                   00:1c:73:4e:99:bc                        Ethernet1           ceos                

inet.0: 8 destinations, 9 routes (8 active, 0 holddown, 0 hidden)
+ = Active Route, - = Last Active, * = Both

10.2.0.0/24        *[OSPF/10] 00:00:50, metric 11
                    >  to 10.12.0.2 via ge-0/0/1.0

inet.0: 8 destinations, 9 routes (8 active, 0 holddown, 0 hidden)
+ = Active Route, - = Last Active, * = Both

10.255.0.2/32      *[OSPF/10] 00:00:51, metric 11
                    >  to 10.12.0.2 via ge-0/0/1.0
                    [BGP/170] 00:00:54, localpref 100
                      AS path: 65002 I, validation-state: unverified
                    >  to 10.12.0.2 via ge-0/0/1.0

inet6.0: 8 destinations, 8 routes (8 active, 0 holddown, 0 hidden)
+ = Active Route, - = Last Active, * = Both

2001:db8:2::/64    *[Static/5] 00:00:47
                    >  to 2001:db8:12::2 via ge-0/0/1.0
52:55:0a:00:00:02 10.0.0.2        fxp0.0                   none
aa:c1:ab:43:0b:51 10.12.0.2       ge-0/0/1.0               none
IPv6 Address                            Linklayer Address  State       Exp   Rtr  Secure  Interface               
2001:db8::1                              none               unreachable  3    no   no      fxp0.0                  
2001:db8:12::2                           aa:c1:ab:43:0b:51  stale       1180  yes  no      ge-0/0/1.0              
fe80::2                                  52:56:00:00:00:02  stale       1066  yes  no      fxp0.0                  
fe80::a8c1:abff:fe43:b51                 aa:c1:ab:43:0b:51  stale       1152  yes  no      ge-0/0/1.0              
Total entries: 4

=================== B2 control plane on cEOS (11:15:01Z)
Neighbor ID     Instance VRF      Pri State                  Dead Time   Address         Interface
10.255.0.1      1        default  128 FULL/BDR               00:00:36    10.12.0.1       Ethernet1
BGP summary information for VRF default
Router identifier 10.255.0.2, local AS number 65002
Neighbor Status Codes: m - Under maintenance
  Neighbor  V AS           MsgRcvd   MsgSent  InQ OutQ  Up/Down State   PfxRcd PfxAcc PfxAdv
  10.12.0.1 4 65001              7         8    0    0 00:00:56 Estab   1      1      1
Last table change time   : 0:00:45 ago
Number of table inserts  : 1
Number of table deletes  : 0
Number of table drops    : 0
Number of table age-outs : 0

Port Neighbor Device ID Neighbor Port ID TTL
---- ------------------ ---------------- ---
Et1  rtr                529              120


VRF: default
Source Codes:
       C - connected, S - static, K - kernel,
       O - OSPF, O IA - OSPF inter area, O E1 - OSPF external type 1,
       O E2 - OSPF external type 2, O N1 - OSPF NSSA external type 1,
       O N2 - OSPF NSSA external type2, O3 - OSPFv3,
       O3 IA - OSPFv3 inter area, O3 E1 - OSPFv3 external type 1,
       O3 E2 - OSPFv3 external type 2,
       O3 N1 - OSPFv3 NSSA external type 1,
       O3 N2 - OSPFv3 NSSA external type2, B - Other BGP Routes,
       B I - iBGP, B E - eBGP, R - RIP, I L1 - IS-IS level 1,
       I L2 - IS-IS level 2, A B - BGP Aggregate,
       A O - OSPF Summary, NG - Nexthop Group Static Route,
       V - VXLAN Control Service, M - Martian,
       DH - DHCP client installed default route,
       DP - Dynamic Policy Route, L - VRF Leaked,
       G  - gRIBI, RC - Route Cache Route,
       CL - CBF Leaked Route

 O        10.1.0.0/24 [110/11]
           via 10.12.0.1, Ethernet1


VRF: default
Source Codes:
       C - connected, S - static, K - kernel,
       O - OSPF, O IA - OSPF inter area, O E1 - OSPF external type 1,
       O E2 - OSPF external type 2, O N1 - OSPF NSSA external type 1,
       O N2 - OSPF NSSA external type2, O3 - OSPFv3,
       O3 IA - OSPFv3 inter area, O3 E1 - OSPFv3 external type 1,
       O3 E2 - OSPFv3 external type 2,
       O3 N1 - OSPFv3 NSSA external type 1,
       O3 N2 - OSPFv3 NSSA external type2, B - Other BGP Routes,
       B I - iBGP, B E - eBGP, R - RIP, I L1 - IS-IS level 1,
       I L2 - IS-IS level 2, A B - BGP Aggregate,
       A O - OSPF Summary, NG - Nexthop Group Static Route,
       V - VXLAN Control Service, M - Martian,
       DH - DHCP client installed default route,
       DP - Dynamic Policy Route, L - VRF Leaked,
       G  - gRIBI, RC - Route Cache Route,
       CL - CBF Leaked Route

 O        10.255.0.1/32 [110/10]
           via 10.12.0.1, Ethernet1


VRF: default
Displaying 4 of 10 IPv6 routing table entries
Source Codes:
       C - connected, S - static, K - kernel, O3 - OSPFv3,
       O3 IA - OSPFv3 inter area, O3 E1 - OSPFv3 external type 1,
       O3 E2 - OSPFv3 external type 2,
       O3 N1 - OSPFv3 NSSA external type 1
       O3 N2 - OSPFv3 NSSA external type2, B - Other BGP Routes,
       A B - BGP Aggregate, R - RIP,
       I L1 - IS-IS level 1, I L2 - IS-IS level 2, DH - DHCP,
       NG - Nexthop Group Static Route, M - Martian,
       DP - Dynamic Policy Route, L - VRF Leaked,
       G  - gRIBI, RC - Route Cache Route,
       CL - CBF Leaked Route

 S        2001:db8:1::/64 [1/0]
           via 2001:db8:12::1, Ethernet1
 C        2001:db8:2::/64 [0/0]
           via Ethernet2, directly connected
 C        2001:db8:12::/64 [0/0]
           via Ethernet1, directly connected
 C        3fff:172:20:20::/64 [0/0]
           via Management0, directly connected


=================== C1 ping from h1: router, one hop, two hops (11:15:01Z)
PING 10.1.0.1 (10.1.0.1) 56(84) bytes of data.
64 bytes from 10.1.0.1: icmp_seq=1 ttl=64 time=124 ms
64 bytes from 10.1.0.1: icmp_seq=2 ttl=64 time=0.650 ms
64 bytes from 10.1.0.1: icmp_seq=3 ttl=64 time=0.739 ms
64 bytes from 10.1.0.1: icmp_seq=4 ttl=64 time=0.644 ms
64 bytes from 10.1.0.1: icmp_seq=5 ttl=64 time=0.776 ms

--- 10.1.0.1 ping statistics ---
5 packets transmitted, 5 received, 0% packet loss, time 4089ms
rtt min/avg/max/mdev = 0.644/25.450/124.441/49.495 ms
PING 10.12.0.2 (10.12.0.2) 56(84) bytes of data.
64 bytes from 10.12.0.2: icmp_seq=1 ttl=63 time=1.44 ms
64 bytes from 10.12.0.2: icmp_seq=2 ttl=63 time=0.989 ms
64 bytes from 10.12.0.2: icmp_seq=3 ttl=63 time=1.35 ms
64 bytes from 10.12.0.2: icmp_seq=4 ttl=63 time=1.29 ms
64 bytes from 10.12.0.2: icmp_seq=5 ttl=63 time=1.17 ms

--- 10.12.0.2 ping statistics ---
5 packets transmitted, 5 received, 0% packet loss, time 4006ms
rtt min/avg/max/mdev = 0.989/1.246/1.444/0.157 ms
PING 10.2.0.10 (10.2.0.10) 56(84) bytes of data.
64 bytes from 10.2.0.10: icmp_seq=1 ttl=62 time=2.79 ms
64 bytes from 10.2.0.10: icmp_seq=2 ttl=62 time=1.74 ms
64 bytes from 10.2.0.10: icmp_seq=3 ttl=62 time=1.84 ms
64 bytes from 10.2.0.10: icmp_seq=4 ttl=62 time=1.85 ms
64 bytes from 10.2.0.10: icmp_seq=5 ttl=62 time=2.03 ms

--- 10.2.0.10 ping statistics ---
5 packets transmitted, 5 received, 0% packet loss, time 4006ms
rtt min/avg/max/mdev = 1.741/2.050/2.794/0.382 ms

=================== C2 return path from h2 and from the router itself (11:15:14Z)
PING 10.1.0.10 (10.1.0.10) 56(84) bytes of data.
64 bytes from 10.1.0.10: icmp_seq=1 ttl=62 time=2.93 ms
64 bytes from 10.1.0.10: icmp_seq=2 ttl=62 time=2.28 ms
64 bytes from 10.1.0.10: icmp_seq=3 ttl=62 time=2.11 ms
64 bytes from 10.1.0.10: icmp_seq=4 ttl=62 time=2.14 ms
64 bytes from 10.1.0.10: icmp_seq=5 ttl=62 time=3.27 ms

--- 10.1.0.10 ping statistics ---
5 packets transmitted, 5 received, 0% packet loss, time 4005ms
rtt min/avg/max/mdev = 2.109/2.546/3.271/0.469 ms
PING 10.2.0.10 (10.2.0.10): 56 data bytes
64 bytes from 10.2.0.10: icmp_seq=0 ttl=63 time=6.632 ms
64 bytes from 10.2.0.10: icmp_seq=1 ttl=63 time=33.329 ms
64 bytes from 10.2.0.10: icmp_seq=2 ttl=63 time=6.924 ms
64 bytes from 10.2.0.10: icmp_seq=3 ttl=63 time=5.626 ms
64 bytes from 10.2.0.10: icmp_seq=4 ttl=63 time=5.064 ms

--- 10.2.0.10 ping statistics ---
5 packets transmitted, 5 packets received, 0% packet loss
round-trip min/avg/max/stddev = 5.064/11.515/33.329/10.928 ms
PING 10.2.0.10 (10.2.0.10): 56 data bytes
64 bytes from 10.2.0.10: icmp_seq=0 ttl=63 time=4.506 ms
64 bytes from 10.2.0.10: icmp_seq=1 ttl=63 time=22.789 ms
64 bytes from 10.2.0.10: icmp_seq=2 ttl=63 time=8.141 ms
64 bytes from 10.2.0.10: icmp_seq=3 ttl=63 time=7.953 ms
64 bytes from 10.2.0.10: icmp_seq=4 ttl=63 time=5.270 ms

--- 10.2.0.10 ping statistics ---
5 packets transmitted, 5 packets received, 0% packet loss
round-trip min/avg/max/stddev = 4.506/9.732/22.789/6.684 ms

=================== C3 packet sizes: MTU-sized with DF, fragmented 2000 and 8000 bytes, small flood (11:15:28Z)
PING 10.2.0.10 (10.2.0.10) 1472(1500) bytes of data.
1480 bytes from 10.2.0.10: icmp_seq=1 ttl=62 time=2.30 ms
1480 bytes from 10.2.0.10: icmp_seq=2 ttl=62 time=1.59 ms
1480 bytes from 10.2.0.10: icmp_seq=3 ttl=62 time=1.97 ms
1480 bytes from 10.2.0.10: icmp_seq=4 ttl=62 time=2.01 ms
1480 bytes from 10.2.0.10: icmp_seq=5 ttl=62 time=1.98 ms

--- 10.2.0.10 ping statistics ---
5 packets transmitted, 5 received, 0% packet loss, time 4004ms
rtt min/avg/max/mdev = 1.589/1.969/2.303/0.226 ms
PING 10.2.0.10 (10.2.0.10) 1473(1501) bytes of data.
From 10.1.0.1 icmp_seq=1 Frag needed and DF set (mtu = 1500)
ping: sendmsg: Message too large
ping: sendmsg: Message too large
ping: sendmsg: Message too large
ping: sendmsg: Message too large

--- 10.2.0.10 ping statistics ---
5 packets transmitted, 0 received, +5 errors, 100% packet loss, time 4065ms

PING 10.2.0.10 (10.2.0.10) 2000(2028) bytes of data.

--- 10.2.0.10 ping statistics ---
5 packets transmitted, 0 received, 100% packet loss, time 4129ms

PING 10.2.0.10 (10.2.0.10) 8000(8028) bytes of data.

--- 10.2.0.10 ping statistics ---
5 packets transmitted, 0 received, 100% packet loss, time 4110ms

PING 10.2.0.10 (10.2.0.10) 56(84) bytes of data.

--- 10.2.0.10 ping statistics ---
1000 packets transmitted, 1000 received, 0% packet loss, time 2054ms
rtt min/avg/max/mdev = 0.928/1.610/5.117/0.401 ms

=================== C4 traceroute and mtr (11:15:52Z)
traceroute to 10.2.0.10 (10.2.0.10), 30 hops max, 46 byte packets
 1  10.1.0.1  1.967 ms  1.417 ms  1.022 ms
 2  10.12.0.2  1.487 ms  1.166 ms  1.247 ms
 3  10.2.0.10  1.892 ms  1.516 ms  1.911 ms
Start: 2026-10-27T11:15:52+0000
HOST: h1                          Loss%   Snt   Last   Avg  Best  Wrst StDev
  1.|-- 10.1.0.1                   0.0%    20    1.3   1.6   0.9   4.6   1.0
  2.|-- 10.12.0.2                  0.0%    20    1.1   1.3   1.0   2.6   0.4
  3.|-- 10.2.0.10                  0.0%    20    3.0   2.3   1.8   3.1   0.4

=================== C5 IPv6 through the router (11:16:17Z)
PING 2001:db8:1::1 (2001:db8:1::1) 56 data bytes
64 bytes from 2001:db8:1::1: icmp_seq=1 ttl=64 time=66.0 ms
64 bytes from 2001:db8:1::1: icmp_seq=2 ttl=64 time=0.871 ms
64 bytes from 2001:db8:1::1: icmp_seq=3 ttl=64 time=0.574 ms
64 bytes from 2001:db8:1::1: icmp_seq=4 ttl=64 time=0.779 ms
64 bytes from 2001:db8:1::1: icmp_seq=5 ttl=64 time=0.704 ms

--- 2001:db8:1::1 ping statistics ---
5 packets transmitted, 5 received, 0% packet loss, time 4112ms
rtt min/avg/max/mdev = 0.574/13.791/66.028/26.118 ms
PING 2001:db8:12::2 (2001:db8:12::2) 56 data bytes
64 bytes from 2001:db8:12::2: icmp_seq=1 ttl=63 time=1.20 ms
64 bytes from 2001:db8:12::2: icmp_seq=2 ttl=63 time=1.90 ms
64 bytes from 2001:db8:12::2: icmp_seq=3 ttl=63 time=1.19 ms
64 bytes from 2001:db8:12::2: icmp_seq=4 ttl=63 time=1.75 ms
64 bytes from 2001:db8:12::2: icmp_seq=5 ttl=63 time=1.70 ms

--- 2001:db8:12::2 ping statistics ---
5 packets transmitted, 5 received, 0% packet loss, time 4007ms
rtt min/avg/max/mdev = 1.193/1.549/1.901/0.295 ms
PING 2001:db8:2::10 (2001:db8:2::10) 56 data bytes
64 bytes from 2001:db8:2::10: icmp_seq=1 ttl=62 time=2.94 ms
64 bytes from 2001:db8:2::10: icmp_seq=2 ttl=62 time=5.44 ms
64 bytes from 2001:db8:2::10: icmp_seq=3 ttl=62 time=2.21 ms
64 bytes from 2001:db8:2::10: icmp_seq=4 ttl=62 time=1.51 ms
64 bytes from 2001:db8:2::10: icmp_seq=5 ttl=62 time=2.69 ms

--- 2001:db8:2::10 ping statistics ---
5 packets transmitted, 5 received, 0% packet loss, time 4007ms
rtt min/avg/max/mdev = 1.506/2.957/5.436/1.332 ms
traceroute to 2001:db8:2::10 (2001:db8:2::10), 30 hops max, 72 byte packets
 1  2001:db8:1::1  2.305 ms  1.158 ms  1.386 ms
 2  2001:db8:12::2  1.603 ms  1.368 ms  1.222 ms
 3  2001:db8:2::10  1.986 ms  2.361 ms  1.818 ms
PING 2001:db8:2::10 (2001:db8:2::10) 2000 data bytes
From 2001:db8:1::1 icmp_seq=1 Packet too big: mtu=1500
2008 bytes from 2001:db8:2::10: icmp_seq=2 ttl=62 time=1.91 ms
2008 bytes from 2001:db8:2::10: icmp_seq=3 ttl=62 time=1.89 ms
2008 bytes from 2001:db8:2::10: icmp_seq=4 ttl=62 time=2.25 ms
2008 bytes from 2001:db8:2::10: icmp_seq=5 ttl=62 time=2.13 ms

--- 2001:db8:2::10 ping statistics ---
5 packets transmitted, 4 received, +1 errors, 20% packet loss, time 4007ms
rtt min/avg/max/mdev = 1.891/2.043/2.249/0.150 ms

=================== C6 iperf3 TCP h1 to h2 and reverse, UDP 100 Mbit (11:16:33Z)
[  5]   0.00-10.00  sec   116 MBytes  97.2 Mbits/sec  1295            sender
[  5]   0.00-10.00  sec   113 MBytes  94.8 Mbits/sec                  receiver

iperf Done.
[  5]   0.00-10.00  sec   115 MBytes  96.4 Mbits/sec  1327            sender
[  5]   0.00-10.00  sec   114 MBytes  95.3 Mbits/sec                  receiver

iperf Done.
[  5]   0.00-10.00  sec   119 MBytes   100 Mbits/sec  0.000 ms  0/86329 (0%)  sender
[  5]   0.00-10.00  sec   117 MBytes  97.9 Mbits/sec  0.143 ms  1750/86329 (2%)  receiver

iperf Done.
[SUM]   0.00-10.00  sec   112 MBytes  93.9 Mbits/sec                  receiver

iperf Done.

=================== C7 UDP and TCP to the loopbacks learned through OSPF and BGP (11:17:17Z)
PING 10.255.0.1 (10.255.0.1) 56(84) bytes of data.
64 bytes from 10.255.0.1: icmp_seq=1 ttl=64 time=1.42 ms
64 bytes from 10.255.0.1: icmp_seq=2 ttl=64 time=0.782 ms
64 bytes from 10.255.0.1: icmp_seq=3 ttl=64 time=0.676 ms

--- 10.255.0.1 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 2028ms
rtt min/avg/max/mdev = 0.676/0.958/1.416/0.326 ms
PING 10.255.0.2 (10.255.0.2) 56(84) bytes of data.
64 bytes from 10.255.0.2: icmp_seq=1 ttl=63 time=1.22 ms
64 bytes from 10.255.0.2: icmp_seq=2 ttl=63 time=1.41 ms
64 bytes from 10.255.0.2: icmp_seq=3 ttl=63 time=1.30 ms

--- 10.255.0.2 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 2002ms
rtt min/avg/max/mdev = 1.217/1.308/1.413/0.080 ms

=================== D1 pfe counters after, interface errors after (11:17:21Z)
    Input  packets:               441540                 7297 pps
    Output packets:               433754                 7093 pps
    Fabric Input  :                    0                    0 pps 
    Fabric Output :                    0                    0 pps 
    Local packets input                 :                   80
    Local packets output                :                  224   
    Software input control plane drops  :                    0
    Software input high drops           :                    0
    Software input medium drops         :                    0
    Software input low drops            :                    0
    Software output drops               :                    0
    Hardware input drops                :                    0
    Info cell drops            :                    0
    Fabric drops               :                    0
Packet Forwarding Engine Input IPv4 Header Checksum Error and Output MTU Error statistics:
    Input Checksum             :                    0
    Output MTU                 :                    2
   Output packets:               160218                    0 pps
   Output packets:                    0
  Input errors:
    Errors: 0, Drops: 0, Framing errors: 0, Runts: 0, Policed discards: 0, L3 incompletes: 0, L2 channel errors: 0, L2 mismatch timeouts: 0, FIFO errors: 0, Resource errors: 0
  Output errors:
    Carrier transitions: 1, Errors: 0, Drops: 0, Collisions: 0, Aged packets: 0, FIFO errors: 0, HS link CRC errors: 0, MTU errors: 0, Resource errors: 0
    Bit errors                             0
    CRC/Align errors                         0                0
    FIFO errors                              0                0
    Total errors                             0                0
     Output packets:               160218
     Output packets:                   42
    Output packets:                   20
    Output packets:               160198                    0 pps
     Output packets:              160165                    0 pps
     Output packets:                  33                    0 pps
   Output packets:               273544                    0 pps
   Output packets:                    0
  Input errors:
    Errors: 0, Drops: 0, Framing errors: 0, Runts: 0, Policed discards: 0, L3 incompletes: 0, L2 channel errors: 0, L2 mismatch timeouts: 0, FIFO errors: 0, Resource errors: 0
  Output errors:
    Carrier transitions: 1, Errors: 0, Drops: 0, Collisions: 0, Aged packets: 0, FIFO errors: 0, HS link CRC errors: 0, MTU errors: 0, Resource errors: 0
    Bit errors                             0
    CRC/Align errors                         0                0
    FIFO errors                              0                0
    Total errors                             0                0
     Output packets:               273544
     Output packets:                   35
    Output packets:                   92
    Output packets:               273452                    0 pps
     Output packets:              273428                    0 pps
     Output packets:                  24                    0 pps
Address          Interface              State           ID               Pri  Dead
10.12.0.2        ge-0/0/1.0             Full            10.255.0.2         1    31
10.12.0.2             65002         12          9       0       0        3:23 Establ

=================== D2 firewall filter counter on transit traffic (configure, count, remove) (11:17:26Z)
    warning: requires 'L2 and L3 Filters' license
commit complete
Exiting configuration mode
20 packets transmitted, 20 received, 0% packet loss, time 3815ms
rtt min/avg/max/mdev = 1.515/2.107/3.165/0.419 ms

Filter: CNT                                                  
Counters:
Name                                                                            Bytes              Packets
transit                                                                          1344                   16
commit complete
Exiting configuration mode

=================== D3 log messages mentioning the forwarding plane or errors since boot (11:18:19Z)
Jun 19 19:26:00   clksyncd[39769]: CLKSYNCD_OUTPUT: clksyncd_acb_rev_check: Unable to read the ACBC FPGA revision, fd (-1) Error 9[Bad file descriptor]
Jun 19 19:26:02   dfwd[39766]: DFWD_SOCKET_LISTEN_INIT_FAIL: Not initializing dfwlib_listen_socket on backup
---(more 100%)---                                        
=================== DONE (11:18:19Z)
```
