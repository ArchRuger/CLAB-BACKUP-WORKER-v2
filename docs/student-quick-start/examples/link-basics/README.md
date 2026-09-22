# link-basics

Two Arista cEOS routers, `r1` and `r2`, joined by one link (`r1:eth1` to `r2:eth1`).
This is the instructor lab used by the *Containerlab Node Manager student quick start*.

## What is in this folder

| Item | What it is |
|---|---|
| `link-basics.clab.yml` | The containerlab topology. The same file is staged on the lab VM under `/srv/containerlab-node-manager/projects/link-basics/`. Deploy that copy; do not rename the lab or its nodes. |
| `link-basics.clab.yml.annotations.json` | The map layout the manager draws on the Topology tab. |
| `reference/start` | Saved state to begin from: the link is addressed (`10.0.0.1/30` on r1, `10.0.0.2/30` on r2) and nothing else is configured. |
| `reference/solution` | The finished exercise: each router also has a `Loopback0` and interface descriptions. |
| `reference/broken-01` | A fault to diagnose: the solution with `Ethernet1` shut down on r2, so the ping across the link fails. |
| `work/` | Your folder. Your saves go to `work/latest`, your checkpoints to `work/checkpoints/<name>`. It appears in the repository with your first save. |

Each `reference/<state>/latest` folder holds a `manifest.json` written by the manager and the
captured configuration of both routers (`r1.cfg`, `r2.cfg`, plus the `.eoscfg` restore artifacts).
The manager offers **Apply to running lab…** for every folder that holds a manifest.

Logins are the cEOS default (`admin` / `admin`). Nothing secret is stored here.
