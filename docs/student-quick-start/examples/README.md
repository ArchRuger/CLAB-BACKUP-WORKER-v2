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

How the instructor's saved states were made (once, on the development VM, release 1.30.32):

1. Stage the package: `sudo install -d -o $USER -g clab_admins -m 2775 /srv/containerlab-node-manager/projects/link-basics` and copy the two files there.
2. Create the course repository on GitHub with a README (`gh repo create pruger-dev/netlab-course --public --add-readme`).
3. In the manager: Home › **Choose a file on the lab VM…** › `link-basics.clab.yml` › **Deploy lab** › **Start lab**; wait for both routers to read **Ready**.
4. Progress tab › **Connect a repository by URL** with the course repository's HTTPS URL and folder `link-basics/work`.
5. `python3 deploy/scaffold-lab.py init link-basics` (registers `link-basics/reference/{start,solution,broken-01}` and `link-basics/work`, binds the lab to `work`).
6. Configure the routers to each state over SSH (the exact commands are in the guide: `start` = Ethernet1 addressed 10.0.0.1/30 and 10.0.0.2/30 with `ip routing`; `solution` = `start` plus `Loopback0` 10.255.0.1/32 and 10.255.0.2/32 with descriptions; `broken-01` = `solution` plus `interface Ethernet1` / `shutdown` on r2) and after each one run `python3 deploy/scaffold-lab.py snapshot link-basics <state> --yes`.
7. Commit the topology, map and README into `link-basics/` of the course checkout (`~/labs/netlab-course`) and push.
8. Mark the repository as a template (`gh repo edit pruger-dev/netlab-course --template`). A student's own copy is made with GitHub's **Use this template** (the walkthrough's copy is `pruger-dev/netlab-course-student`, private).
9. Destroy the lab (**Lab actions ▾ › Destroy lab…**) and remove it from the manager (**Remove from this manager…**), so that the student starts from an empty My labs.

`tools/reset_scenario_a.sh <student-repo-name>` brings the development VM back to that starting state.

## `my-first-lab/` — the personal lab of Scenario B

What the student produces in Scenario B, kept here as the expected result:

| File | Where it came from |
|---|---|
| `my-first-lab.clab.yml`, `my-first-lab.clab.yml.annotations.json` | Written to `/srv/containerlab-node-manager/projects/my-first-lab/` by the lab builder's **Save to the VM…** (two cEOS routers `r1`, `r2`, image `n24l/ceos:4.35.0F`, management addresses 172.20.20.21/.22 set in the Node Editor, one link, one text note). |
| `README.md` | The five-line README the student writes on the lab VM in step B7 before publishing the topology with Git. |
| `remote-tree.txt` | The repository tree of `pruger-dev/my-network-labs` after step B8: the topology, the map and the README next to `latest/` (the checkpoint `link-up` is added in step B9). |

The saved configurations themselves (`my-first-lab/latest`, `my-first-lab/checkpoints/link-up`) live in the student's
repository and are not copied here; Scenario A's reference states show what such a folder holds.
