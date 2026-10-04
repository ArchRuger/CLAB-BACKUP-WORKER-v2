# Naming and structure for lab courses

This manager is a single-tenant tool: one student, one VM, one manager, one Git repository
that the student pushes to as themselves. This guide standardises the few names the system
depends on and recommends conventions for the rest, so an instructor can build a library of
lab states once and every student's box loads them cleanly.

Related: [GIT-PROGRESS.md](GIT-PROGRESS.md) (saving, uploading and **Load**),
[LAB-OPERATIONS.md](LAB-OPERATIONS.md). The scaffold tool that creates the structure below is
`deploy/scaffold-lab.py`; a template topology is in `deploy/lab-template/`.

## What the manager keys on — freeze these

**Load** maps a saved state to a running node by **exact node name and platform**,
and the node name the manager stores is the full container name, `clab-<labname>-<node>`. So the
identity of every saved state is `clab-<labname>-<node>` per node. (That is containerlab's default
`prefix`; a topology that sets `prefix: __lab-name` has containers named `<labname>-<node>` and
one that sets `prefix: ""` has the bare node name, and the manager stores whichever name
containerlab gives.) Two rules follow:

1. **Ship the exact topology.** Build your saved states on the same topology file the student
   deploys — same containerlab `name:` and same node names. If your build box uses
   `name: bgp-core` and a student deploys the lab as `my-lab`, none of your saved states map,
   and the load preflight refuses rather than guessing.
2. **Decide names once, never rename.** Renaming a lab or a node orphans every saved state that
   referenced the old name. Choose the names below before you record any state.

| Thing | Rule |
|---|---|
| containerlab `name:` (the lab slug) | one lowercase, hyphenated token, e.g. `bgp-core`; identical on every box |
| node names | role-based, lowercase, short, stable, e.g. `pe1 pe2 rr1 ce1` |
| node `kind:` / image | the platform lives here, not in the node name; pin the image |
| login | one standard per platform (the kind default, or one credential profile) |

Live load covers Junos (`juniper_cjunosevolved`, `juniper_vjunosswitch`), Arista EOS (`arista_ceos`) and Cisco IOS XR
(`cisco_xrv9k`); see [GIT-PROGRESS.md](GIT-PROGRESS.md).

## Node names

Use the **role**, not the box: `pe1`, `pe2`, `rr1`, `ce1`, or `r1…rN` for a plain router lab;
`spine1`, `leaf1` for a fabric. Keep them short and never encode the platform (`PTX1`, `SW1`) —
the `kind:` already says what the node is, and role names read better and travel across labs.
Same names on the instructor build box and every student clone.

## Lab slug

Pick one token and reuse it for the topology `name:`, the `.clab.yaml` filename and the Git
folder: `bgp-core` → `bgp-core.clab.yaml`, containerlab `name: bgp-core`, Git folder `bgp-core/`.
Lowercase and hyphenated. No spaces or capitals (a space becomes an underscore and you get
`BGP-LAB_BASE` instead of a clean slug).

## Git repository structure

A lab saves into **one** folder of the repository (its *lab folder*) and can **Load** a saved
state from **any** folder. The lab folder is the folder named after the lab by default;
the student can pick another place on the first save, and labs may sit inside, above or
beside each other, or at the top level. So keep the states you give the student apart from
the folder they save into, and give them the same few names in every lab:

```
<repo>/
  <lab-slug>/             # the lab saves here: latest/, baseline/, checkpoints/<name>/
    start/                # lab states you author with "Save as a lab state…"
    broken/               #   (Start, Broken and Final in the Load list)
    final/
```

- **The student's own saves** go to `<lab-slug>/latest` (**Save**), and their own milestones to
  `<lab-slug>/checkpoints/<name>` (**Keep as a checkpoint**). Their starting point is
  `<lab-slug>/baseline`.
- **You author a lab state** on your build box: bring the running lab to that state, open
  the chip's panel, press **Save as a lab state…**, accept the suggested folder
  (`<lab-slug>/start`) and name, and **Upload**. The lab keeps saving to its own folder; only the
  new folder is written. A state is a normal saved folder (topology, map and every device
  configuration), so a folder that already holds one asks before it is replaced.
- **The student loads them** with **Load** in the lab header: the list shows the lab's own
  saves and checkpoints, then the lab states found in the repository as **Start**, **Broken**
  and **Final**. Load lists the devices with what differs, and the red **Load** confirms; **Undo this load**
  loads the automatic backup that was taken first.
- **Never save the student's lab into a lab-state folder.** They are the given states; the
  lab keeps saving in its own folder.
- Keep the state vocabulary small and identical across every lab: `start`, `broken`,
  `final` (and `broken-02`, … when you need more faults), plus the student's own
  checkpoints. A predictable set makes the UI predictable from lab to lab.
- A folder inside another lab's `latest`, `baseline` or `checkpoints` cannot be a lab
  folder, so a state such as `bgp/latest/start` is not possible; `bgp/start` is.

## Repositories

- **One master repository you own** is the source of truth for all labs.
- **Each student uses their own copy** — a fork of the master (or a repository created from it as
  a template). In the manager, the student pastes their fork's HTTPS address in the first-save panel (or
  uses **Use a different repository…** or **Connect by URL…** under **Save settings**) with
  their own GitHub login, so their **Save** and **Upload** go to their repo.
- **Updates:** *Update from the repository* only fast-forwards the student's own remote. If you revise
  labs after students fork, they sync their fork from your master on GitHub, or you hand out a
  fresh template per cohort. The manager does not track a second "upstream" remote.

## Building a lab's state library (instructor)

On your build box, once per lab, the manager's own way:

1. Deploy the standardised topology and let the NOS finish booting.
2. Press **Save** once so the lab is connected to the repository, then bring the devices to
   the **start** state.
3. Open the chip's panel, press **Save as a lab state…**, accept `<lab-slug>/start` (or
   change the folder) and the name `start`, and press **Upload** when it offers it.
4. Repeat for `broken` and `final` (configure, then **Save as a lab state…**).

The student then loads **Start** to begin, works and saves in the lab's own folder, loads
**Final** to check and **Broken** to practise recovery, all without a reboot and without
changing where they save.

### The scaffold tool (scripted alternative)

`deploy/scaffold-lab.py` does the same with a script and creates the older layout, in which
the states sit in a `reference/` folder and the student's saves in `work/`:

1. `python3 deploy/scaffold-lab.py init <lab-slug>` creates the folders
   `reference/{start,solution,broken-01}` and `work` inside `<lab-slug>/` and points the lab's
   saves at `work`; `--states start,broken,final` names the states differently.
2. Configure the running node to the **start** state, then
   `python3 deploy/scaffold-lab.py snapshot <lab-slug> start` captures the running config and
   saves it (and its restore-grade candidate) into `reference/start`, then points the lab
   back at `work`.
3. Repeat for the other states (configure, then `snapshot <lab-slug> <state>`).
4. Each `snapshot` lists the files it saved and asks before it uploads, because the manager
   uploads a save only when it is told to; `--yes` states that you reviewed it for scripted use.
   Answering no keeps the state on the lab VM only (it goes up with the next upload of the
   repository). Either way the lab is pointed back at `work`. If the save cannot start, times
   out, cannot be set aside or the upload fails, the tool tries to point the lab back at `work`
   and says what happened: either "rebound to `<lab-slug>/work`", or that the lab still saves
   to `reference/<state>` (a save that still waits for upload refuses the folder change). In
   that case upload that save from the chip in the lab header, then run
   `scaffold-lab.py init <lab-slug>` again before the student saves. If the manager stops
   answering (a restart mid-request, a reset or a timeout), the tool exits with "Cannot reach
   the manager" and the same account of where the lab saves; when the lost answer belonged to a
   folder change it says the lab **may** still save to `reference/<state>`, because the change
   may have happened. The tool talks to the manager directly and ignores `http_proxy`.

The states it writes are ordinary saved folders: **Load** lists them with the other lab
states in the repository.
