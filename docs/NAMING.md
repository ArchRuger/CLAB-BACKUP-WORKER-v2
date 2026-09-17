# Naming and structure for lab courses

This manager is a single-tenant tool: one student, one VM, one manager, one Git repository
that the student pushes to as themselves. This guide standardises the few names the system
depends on and recommends conventions for the rest, so an instructor can build a library of
lab states once and every student's box applies them cleanly.

Related: [GIT-PROGRESS.md](GIT-PROGRESS.md) (save locations and *Apply to running lab*),
[LAB-OPERATIONS.md](LAB-OPERATIONS.md). The scaffold tool that creates the structure below is
`deploy/scaffold-lab.py`; a template topology is in `deploy/lab-template/`.

## What the manager keys on — freeze these

*Apply to running lab* maps a saved state to a running node by **exact node name and platform**,
and the node name the manager stores is the full container name, `clab-<labname>-<node>`. So the
identity of every saved state is `clab-<labname>-<node>` per node. Two rules follow:

1. **Ship the exact topology.** Build your saved states on the same topology file the student
   deploys — same containerlab `name:` and same node names. If your build box uses
   `name: bgp-core` and a student deploys the lab as `my-lab`, none of your saved states map,
   and the restore preflight refuses rather than guessing.
2. **Decide names once, never rename.** Renaming a lab or a node orphans every saved state that
   referenced the old name. Choose the names below before you record any state.

| Thing | Rule |
|---|---|
| containerlab `name:` (the lab slug) | one lowercase, hyphenated token, e.g. `bgp-core`; identical on every box |
| node names | role-based, lowercase, short, stable, e.g. `pe1 pe2 rr1 ce1` |
| node `kind:` / image | the platform lives here, not in the node name; pin the image |
| login | one standard per platform (the kind default, or one credential profile) |

Live restore is Junos only for now (`juniper_cjunosevolved`, `juniper_vjunosswitch`).

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

The manager binds a lab to **one** folder for saving, and applies states from **any** folder.
So separate the states you give the student from the folder they save into:

```
<repo>/
  <lab-slug>/
    reference/            # instructor states — read-only by convention, applied with "Apply to running lab…"
      start/              #   the starting configuration (apply to begin)
      solution/           #   the target / final configuration (apply to check)
      broken-01/          #   a fault to diagnose (add broken-02, … as needed)
    work/                 # the lab binds here; the student's Save progress + checkpoints live here
```

- **Bind the lab to `<lab-slug>/work`.** The student's *Save progress* writes `work/latest`, and
  their own milestones go to `work/checkpoints/<name>` via *Create checkpoint…*.
- **The student applies `reference/*`** from the **Progress** tab: *Saved versions* lists them
  under *Instructor and reference versions* with an *Apply to running lab…* button, the folder
  browser under *Save location › Change folder…* shows the same button on each folder, and
  *Full history…* labels every version by its folder (`reference/broken-01 · latest`) instead
  of a bare "latest".
- **Never save into `reference/*`.** They are the given states; leave the lab bound to `work`.
- Keep the state vocabulary small and identical across every lab: `start`, `solution`,
  `broken-NN`, plus the student's own checkpoints. A predictable set makes the UI predictable
  from lab to lab.

## Repositories

- **One master repository you own** is the source of truth for all labs.
- **Each student uses their own copy** — a fork of the master (or a repository created from it as
  a template). In the manager, the student uses *Use a different repository → Connect by URL* with
  their fork's HTTPS URL and their own GitHub login, so their *Save progress* pushes to their repo.
- **Updates:** *Update from remote* only fast-forwards the student's own remote. If you revise
  labs after students fork, they sync their fork from your master on GitHub, or you hand out a
  fresh template per cohort. The manager does not track a second "upstream" remote.

## Building a lab's state library (instructor)

On your build box, once per lab:

1. Deploy the standardised topology and let the NOS finish booting.
2. `python3 deploy/scaffold-lab.py init <lab-slug>` — registers `reference/{start,solution,broken-01}`
   and `work`, and binds the lab to `work`.
3. Configure the running node to the **start** state, then
   `python3 deploy/scaffold-lab.py snapshot <lab-slug> start` — captures the running config and
   saves it (and its restore-grade candidate) into `reference/start`, then rebinds to `work`.
4. Repeat for `solution` and `broken-01` (configure, then `snapshot <lab-slug> <state>`).
5. Push is automatic; the states are now in your master repo for students to clone and apply.

The student then applies `reference/start` to begin, works in `work`, applies `reference/solution`
to check, and applies `reference/broken-01` to practise recovery — all without a reboot and
without changing where they save.
