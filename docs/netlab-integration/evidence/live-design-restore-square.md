# Live check: Network design on the running manager (restore-square)

Run 2026-09-27T00:03:43+00:00 against http://127.0.0.1:8081 (manager 1.30.44, the real product on the dev VM). Generation only: no device, VM file or Docker action.

17 of 17 checks passed.

| Check | Result | Detail |
|---|---|---|
| the manager answers and names its version | ok | 1.30.44 |
| the design view loads for the lab | ok | 200 |
| the engine is available inside the product image | ok | {'available': True, 'version': '26.9', 'path': '/usr/local/bin/netlab', 'diagnostic': ''} |
| every device of the lab has a profile or a reason | ok | ['ceos', 'cjunosevolved', 'host1', 'vjunos-switch', 'xrv9k'] |
| the design saves on the live lab | ok |  |
| a plan is queued | ok | {'id': 'd6334bf4f22c425d849432b6cdd20ea4', 'lab_id': '174386ec12ee496190c585c5796b2662', 'created': '2026-09-27T00:03:28.890229+00:00', 'status': 'queued', 'mes |
| the plan succeeded on the live lab | ok | Plan generated |
| every included device has files | ok | ['ceos', 'cjunosevolved', 'host1', 'vjunos-switch', 'xrv9k'] |
| the ledger pinned every included device | ok | {'ceos': 1, 'cjunosevolved': 2, 'host1': 5, 'vjunos-switch': 3, 'xrv9k': 4} |
| the engine is the pinned release | ok | 26.09 |
| the plan carries the containerlab ports of the real topology | ok |  |
| the ZIP downloads | ok | 12980 |
| a second plan of the same design keeps every allocation | ok | [] |
| /api/state carries the summary and no intent | ok |  |
| the live page shows the plan as ready | ok |  |
| the live page lists the real devices in the plan | ok |        Generated planPlan generated just now.Cancel              Warnings       What changed              Compatibility       Devicebgpipv4ipv6ospfv2ospfv3ceosG |
| no console or page errors on the live page | ok | [] |
