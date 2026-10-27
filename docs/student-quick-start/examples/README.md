# Example materials for the student quick start

Everything the two walkthroughs use, so that the guide can be replayed on another VM. Nothing here is
secret: the device logins are the kinds' published defaults, and the captured configurations contain
only the default `admin` account of the cEOS lab image.

## `link-basics/` — the instructor's lab package (Scenario A)

| File | Where it goes | Made how |
|---|---|---|
| `link-basics.clab.yml` | On the lab VM: `/srv/containerlab-node-manager/projects/link-basics/` | Written by hand: two Arista cEOS routers `r1`, `r2` (`n24l/ceos:4.35.0F`), one link `r1:eth1 – r2:eth1`, management addresses pinned to 172.20.20.11 and .12 so that saved states apply after a redeploy. |
| `link-basics.clab.yml.annotations.json` | Next to the topology on the VM | The map: both routers placed, one text note. Same format as the manager's own *Edit map* and the VS Code containerlab extension. |
| `README.md` | In the course repository under `link-basics/` | What each item is, for the student. |
| `reference/start/latest/`, `reference/solution/latest/`, `reference/broken-01/latest/` | In the course repository under `link-basics/reference/` | Recorded through the manager with `deploy/scaffold-lab.py` (see below). Each folder holds `manifest.json`, `r1.cfg`, `r2.cfg` and the `.eoscfg` restore artifacts. |

How the instructor's saved states were made (once, on the development VM, release 1.30.32, with the old Progress tab and
`deploy/scaffold-lab.py`; they are schema 2 states that hold the device configurations only, and a current manager lists them
under **Load › Lab states** as **Start**, **Solution** and **Broken-01**, named from their folders). With a current manager the
instructor's way is **Save as a lab state…** in the save chip's panel ([Lab states for a course](../../COURSE-STATES.md)):

1. Stage the package: `sudo install -d -o $USER -g clab_admins -m 2775 /srv/containerlab-node-manager/projects/link-basics` and copy the two files there.
2. Create the course repository on GitHub with a README and make it a template (`gh repo edit <account>/netlab-course --template`).
3. In the manager: Home › **Choose a file on the lab VM…** › `link-basics.clab.yml` › **Deploy lab** › **Start lab**; wait for both routers to read **Ready**.
4. Bring the routers to each state over SSH (`start` = Ethernet1 addressed 10.0.0.1/30 and 10.0.0.2/30 with `ip routing`; `solution` = `start` plus `Loopback0` 10.255.0.1/32 and 10.255.0.2/32 with descriptions; `broken-01` = `solution` plus `interface Ethernet1` / `shutdown` on r2) and after each one use the chip's **Save as a lab state…** with the names `start`, `solution`, `broken-01`, then **Upload**.
5. A student's own copy is made with GitHub's **Use this template** (the 2026-10 replay used `ArchRuger/campaign2-netlab-course-student`, private).

`tools/reset_scenario_a.sh` brings the development VM back to the starting state of Scenario A.

## `my-first-lab/`: the personal lab of Scenario B

What the student produces in Scenario B, kept here as the expected result:

| File | Where it came from |
|---|---|
| `my-first-lab.clab.yml`, `my-first-lab.clab.yml.annotations.json` | Written to `/srv/containerlab-node-manager/projects/my-first-lab/` by the lab builder's **Save to the VM…** (two cEOS routers `r1`, `r2`, image `n24l/ceos:4.35.0F`, management addresses 172.20.20.21/.22 set in the Node Editor, one link, one text note). Since 1.31.0 a **Save** copies both files into the repository with the device configurations, so nothing is copied by hand. |
| `remote-tree.txt` | The repository tree of the student's repository after Scenario B: `my-first-lab/latest/` and `my-first-lab/checkpoints/link-up/`, each with the topology, the map, `manifest.json` and one `.cfg` and `.eoscfg` per router. |

The saved configurations themselves live in the student's repository and are not copied here.
