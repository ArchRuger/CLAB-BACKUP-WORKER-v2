# Browser check: Network design tab

Run 2026-09-27T20:24:41+00:00 against the fixture manager (real app on scratch data `<scratch>/acceptance-opus/fx-8145-design-ui/design-ui-fixture-j8rgvud8`, real `netlab` engine, no VM), Chromium 153.0.8010.12.

29 of 29 checks passed; 0 console errors (0 handled HTTP responses); 0 page errors.

| Check | Result | Detail |
|---|---|---|
| Design tab opens from the route | ok |  |
| a lab without a design says so | ok | No design yet No design yet |
| the devices table lists the three devices with their profiles | ok | r1arista_ceoseosRouterHostExcluder2arista_ceoseosRouterHostExcluder3cisco_xrv9kiosxrRouterHostExclude |
| a pool inside the management network is refused | ok | addressing.lan.ipv4: Overlaps the lab management network containerlab default management ipv4-subnet |
| editing marks the design as unsaved | ok | Unsaved changes Unsaved changes |
| the design saves without problems | ok | Design saved, no plan yet Design saved, no plan yet \|  |
| the advanced editor shows the saved intent with the guided values | ok | {   "schema": 1,   "label": "",   "families": {     "ipv4": true,     "ipv6": true   },   "addressing": {     "loopback": {       "ipv4": "10.255.0.0/24",       |
| the design-vrfs table is rendered | ok |  |
| the design-vlans table is rendered | ok |  |
| the design-links table is rendered | ok |  |
| the design-static table is rendered | ok |  |
| a VRF added through the table reaches the JSON with its loopback | ok | {   "schema": 1,   "label": "",   "families": {     "ipv4": true,     "ipv6": true   },   "addressing": {     "loopback": {       "ipv4": "10.255.0.0/24",       |
| the link table attaches the link to the VRF | ok | {   "schema": 1,   "label": "",   "families": {     "ipv4": true,     "ipv6": true   },   "addressing": {     "loopback": {       "ipv4": "10.255.0.0/24",       |
| a static route added through the table reaches the JSON | ok | {   "schema": 1,   "label": "",   "families": {     "ipv4": true,     "ipv6": true   },   "addressing": {     "loopback": {       "ipv4": "10.255.0.0/24",       |
| the vrf and routing modules were switched on with the tables | ok | {   "schema": 1,   "label": "",   "families": {     "ipv4": true,     "ipv6": true   },   "addressing": {     "loopback": {       "ipv4": "10.255.0.0/24",       |
| the design with the guided tables saves without problems | ok |  |
| the plan lists every device with a loopback and interfaces | ok |        Generated planPlan generated just now.Back to newest planCancel              Warnings (1)Warning in vrf: Node r3 uses no VRFs, removing 'vrf' from node m |
| the plan shows the containerlab ports beside the device ports | ok |        Generated planPlan generated just now.Back to newest planCancel              Warnings (1)Warning in vrf: Node r3 uses no VRFs, removing 'vrf' from node m |
| BGP sessions appear in the plan | ok |        Generated planPlan generated just now.Back to newest planCancel              Warnings (1)Warning in vrf: Node r3 uses no VRFs, removing 'vrf' from node m |
| compatibility says generated, not live tested | ok | Devicebgpipv4ipv6ospfv2ospfv3static_routesvrfr1Generated, not yet tested liveGenerated, not yet tested liveGenerated, not yet tested liveGenerated, not yet test |
| the files card lists initial, ospf, bgp, vrf and routing for a device | ok |        Generated files       Generated configuration fragments, not backups. They reach devices only through Apply to devices… on the plan card.       r1normali |
| the ZIP download link points at the generation | ok | /api/labs/d01ed2f3a9bc4beeb7f38d6029a4ea99/design/generations/afe9129b37914d9f82ed45216a9f3ac8/download |
| a generated file opens in a dialog | ok |  |
| EIGRP on cEOS fails the plan with the device and the reason named | ok | r1: eigrp is not supported on kind arista_ceos (netlab 26.09 module 'eigrp' does not support device profile 'eos')r2: eigrp is not supported on kind arista_ceos |
| a reload keeps the saved design | ok |  |
| the history lists the generated plans | ok | HistoryFailed just now The design asks for something a device in this lab cannot do. Nothing was generated. Shown aboveSucceeded just now Plan generated View |
| the export item is present | ok |  |
| no horizontal scroll at tablet width | ok | scrollWidth=768 |
| the Design tab adds no horizontal overflow at phone width beyond the shell | ok | design=428 shell=428 |

Screenshots: 01-empty.png, 02-problems.png, 03-saved.png, 03b-tables.png, 04-plan.png, 05-file.png, 06-unsupported.png, 07-tablet.png, 08-phone.png
