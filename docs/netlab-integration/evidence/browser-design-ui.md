# Browser check: Network design tab

Run 2026-09-27T00:00:18+00:00 against the fixture manager (real app on scratch data `/tmp/design-ui-fixture-_wq76uyg`, real `netlab` engine, no VM), Chromium 153.0.8010.12.

20 of 20 checks passed; 0 console errors (0 handled HTTP responses); 0 page errors.

| Check | Result | Detail |
|---|---|---|
| Design tab opens from the route | ok |  |
| a lab without a design says so | ok | No design yet No design yet |
| the devices table lists the three devices with their profiles | ok | r1arista_ceoseosRouterHostExcluder2arista_ceoseosRouterHostExcluder3cisco_xrv9kiosxrRouterHostExclude |
| a pool inside the management network is refused | ok | addressing.lan.ipv4: Overlaps the lab management network containerlab default management ipv4-subnet |
| editing marks the design as unsaved | ok | Unsaved changes Unsaved changes |
| the design saves without problems | ok | No design yet No design yet \|  |
| the advanced editor shows the saved intent with the guided values | ok | {   "schema": 1,   "label": "",   "families": {     "ipv4": true,     "ipv6": true   },   "addressing": {     "loopback": {       "ipv4": "10.255.0.0/24",       |
| the plan lists every device with a loopback and interfaces | ok |        Generated planPlan generated just now.Cancel              Warnings       What changed              Compatibility       Devicebgpipv4ipv6ospfv2ospfv3r1Gen |
| the plan shows the containerlab ports beside the device ports | ok |        Generated planPlan generated just now.Cancel              Warnings       What changed              Compatibility       Devicebgpipv4ipv6ospfv2ospfv3r1Gen |
| BGP sessions appear in the plan | ok |        Generated planPlan generated just now.Cancel              Warnings       What changed              Compatibility       Devicebgpipv4ipv6ospfv2ospfv3r1Gen |
| compatibility says generated, not live tested | ok | Devicebgpipv4ipv6ospfv2ospfv3r1Generated, not yet tested liveGenerated, not yet tested liveGenerated, not yet tested liveGenerated, not yet tested liveGenerated |
| the files card lists initial, ospf and bgp for a device | ok |        Generated files       Generated configuration fragments, not backups. Applying them to devices is not available yet.       r1normalize 60 B Viewinitial 6 |
| the ZIP download link points at the generation | ok | /api/labs/8a58272b9c5c41fe81ee9633bc5c9185/design/generations/778ed4d8ed2f4afd9e2affbfd18eee9a/download |
| a generated file opens in a dialog | ok |  |
| EIGRP on cEOS fails the plan with the device and the reason named | ok | r1: eigrp is not supported on kind arista_ceos (netlab 26.09 module 'eigrp' does not support device profile 'eos')r2: eigrp is not supported on kind arista_ceos |
| a reload keeps the saved design | ok |  |
| the history lists the generated plans | ok | HistoryFailed just now The design asks for something a device in this lab cannot do. Nothing was generated.Succeeded just now Plan generated |
| the export item is present | ok |  |
| no horizontal scroll at tablet width | ok | scrollWidth=768 |
| the Design tab adds no horizontal overflow at phone width beyond the shell | ok | design=428 shell=428 |

Screenshots: 01-empty.png, 02-problems.png, 03-saved.png, 04-plan.png, 05-file.png, 06-unsupported.png, 07-tablet.png, 08-phone.png
