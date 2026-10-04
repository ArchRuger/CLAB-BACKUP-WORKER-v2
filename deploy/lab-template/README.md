# Lab template and scaffold

Standardised starting point for a new lab in a single-tenant course. Read
[docs/NAMING.md](../../docs/NAMING.md) first — it explains the names the manager keys on.

## Files

- `bgp-core.clab.yaml` — a template containerlab topology with role-based, lowercase node names
  (`pe1`, `pe2`) and a lowercase lab slug (`name: bgp-core`). Copy it to your labs directory,
  rename to `<lab-slug>.clab.yaml`, set `name:` to the same slug, and edit nodes/links.

## Build a lab's state library

Run these on the build box after the lab's NOS has finished booting. The scaffold talks to the
local manager API (default `http://127.0.0.1:8081`) and drives the same actions as the buttons.

```bash
# 1. Create the folder structure and bind the lab's saves to <slug>/work
python3 deploy/scaffold-lab.py init bgp-core

# 2. For each state: configure the running device to that state, then snapshot it.
#    (Configure by hand in an SSH session, or load a config, then run:)
python3 deploy/scaffold-lab.py snapshot bgp-core start
python3 deploy/scaffold-lab.py snapshot bgp-core solution
python3 deploy/scaffold-lab.py snapshot bgp-core broken-01
```

`init` registers `reference/{start,solution,broken-01}` and `work` and points the lab at `work`.
`snapshot <slug> <state>` captures whatever the node is running right now, saves it (and its
restore-grade candidate) to `<slug>/reference/<state>`, lists what it saved and asks before it uploads
(`--yes` answers for a script; no keeps the state on the lab VM), and rebinds the lab to `work`.

Prerequisites: the lab is deployed and reachable, and the lab already saves into the target
Git repository (press **Save** in the lab header once; the first save connects the lab, and a
repository that is not on the VM yet is connected there by its HTTPS address). The scaffold needs one
connected repository to create folders in.

Students then use your repository on their VM, press **Load** in the lab header and choose the
state (`start`, `solution` or `broken-01`) under **Lab states**. They save their own work with
**Save**, which goes to `work` (and to `work/checkpoints/<name>` with **Keep as a checkpoint**).

## Custom state names

Pass a comma-separated set to change the reference states:

```bash
python3 deploy/scaffold-lab.py init ospf-areas --states start,solution,broken-01,broken-02
```
