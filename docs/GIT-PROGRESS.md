# Save lab progress to Git

Choose where a lab's progress is saved once (the first **Save progress** asks; the
**Progress** tab's *Save location* card holds the setting afterwards), then use
**Save progress** to capture its selected devices, save the complete capture in that
repository, commit changed configurations and, after you have reviewed the changes, push. Ben keeps his existing Git login and
commit identity. The manager never asks for his Git token.

The Git helper is installed on the VM by the guided installer and refreshed by every
upgrade; see [the installation guide](INSTALL.md) and [VM connection](VM-CONNECTION.md).

## What each save means

Capture, local commit and remote push have separate outcomes. **Saved on VM**
means a configuration snapshot or Git commit exists locally; **Pushed** means
the push was verified. A failed push does not turn a successful device capture
into a failed backup.

```mermaid
flowchart TD
    A[Save progress] --> B[Capture selected devices]
    B --> C{Complete capture?}
    C -- No --> D[Keep successful local files; latest unchanged]
    C -- Yes --> E[Keep immutable backup snapshot]
    E --> F[Export exact files and manifest]
    F --> G{Configuration changes?}
    G -- Yes --> H[Commit to selected branch]
    G -- No --> I[Keep existing commit]
    H --> R{Review before uploading}
    R -- Upload these changes --> J[Push]
    R -- Not now --> M[Saved on the VM; waiting for your review]
    I --> R
    J -- Verified --> K[Saved to Git]
    J -- Unavailable or rejected --> L[Saved locally; retry push]
```

Only configurations and their manifest enter the Git commit. Existing topology
YAML, annotations, README files and unrelated edits stay outside the export. The
manifest records the lab, selected and excluded nodes, capture identity, topology
provenance, configuration formats and file checksums. Git export uses one completed
backup job, not the rolling `latest` backup directory that can contain files from
different capture attempts.

A progress save supports up to 500 devices, with nonempty UTF-8 configurations
up to 2 MiB each and 16 MiB in total. Oversized or incomplete captures do not
replace the repository snapshot.

## One-time setup

Start with [GIT-SETUP.md](GIT-SETUP.md). On the Ubuntu VM, run this as the existing
ordinary account, without sudo, from any directory:

```bash
bash "$HOME/projects/clab-manager/deploy/setup-git.sh"
```

The guided flow prepares the checkout, owner-scoped HTTPS login and commit
identity, then registers the current branch after noninteractive validation.
No additional Linux account is needed on a standalone VM. Linux and GitHub
usernames do not need to match. Existing working installations should upgrade
with `start-manager.sh` or `setup-git.sh --refresh` and retain their current owner.

In the lab, open the **Progress** tab. The first **Save progress** asks where the
lab's progress should be saved — the registered repository, a folder in it and the
devices to include — and the *Save location* card keeps the same settings for later
changes. **Save progress** then captures and commits automatically and shows the changes
for review before anything is uploaded (see *Everyday buttons*); the review cannot be
switched off. A separate Commit button is not needed.

The following sections are manual authentication and recovery reference. The
quickstart guide covers advanced registration, other HTTPS providers and separate
owners. Git authentication remains separate from the `clab-discovery` VM password.

## GitHub HTTPS login on the VM

GitHub does not accept the account's website password for HTTPS Git operations.
Use GitHub CLI to configure the repository owner's Git authentication.
The GitHub account must have write access to the intended repository.
See [GitHub authentication](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github).

On Ubuntu 24.04, the VM administrator can install the
[GitHub CLI package](https://packages.ubuntu.com/noble/gh):

```bash
sudo apt update
sudo apt install gh
```

Then run the following **as the registered repository owner**, without sudo.
For the standalone installation, this can be the existing VM account; creating a
separate engineer account is optional.

```bash
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git --hostname github.com
gh auth status --hostname github.com
```

Complete the browser authorization using the URL and one-time code shown by the
command. On a VM without a desktop, use your workstation browser. The login and
Git credential helper must belong to the same Linux account selected by
`--owner`. See [CLI login](https://cli.github.com/manual/gh_auth_login) and
[Git credential setup](https://cli.github.com/manual/gh_auth_setup-git).

Git commit identity is configured separately. Inside the checkout, verify it:

```bash
git var GIT_AUTHOR_IDENT
git var GIT_COMMITTER_IDENT
```

If identity is missing, set repository-local `user.name` and `user.email` to your
intended author name and email before the first manager save. Authentication
alone does not supply these settings.

### Recovery after manually committing a failed manager export

If you already committed the exported files from the CLI, finish publishing that
manual commit as the repository owner. For a checkout on `main` with `origin`:

```bash
git push origin main
git status -sb
```

After the push succeeds, use **Keep snapshot only** on the superseded failed
manager saves, then start a new **Save progress**. Dismissal preserves backup
files and Git commits. A CLI commit changes the original export's expected
history; the old operation cannot always resume it, and the manager will not
automatically push unrelated unpublished commits. Normal manager saves commit
automatically; after an ordinary failure, retry the original job first.

## Repository layout

```text
BENS-BGP-LAB/
├── BENS-BGP-LAB.clab.yaml          existing file; not rewritten by saves
├── latest/
│   ├── PE1.cfg
│   ├── PE2.cfg
│   └── manifest.json
├── baseline/
│   ├── PE1.cfg
│   └── manifest.json
└── checkpoints/
    └── bgp-peering-working/
        ├── PE1.cfg
        └── manifest.json
```

Names above illustrate the layout; the exporter chooses stable filenames from
node identity and configuration format: `<node>.cfg` for Junos (display-set text), EOS and
IOS XR alike, plus the machine restore artifact beside it on a restore-capable platform
(Junos `<node>.jcfg`, EOS `<node>.eoscfg`, IOS XR `<node>.xrcfg`) — never the extension the
manager keeps for that same capture in its own internal storage. A folder saved before
Junos moved to `.cfg` may still hold `<node>.set`; it keeps listing, comparing (paired with
a later save of the same node whatever its extension) and restoring exactly like a `.cfg`
save, since every reader works from the version's `manifest.json`, never from a filename
guess. The folder a lab saves to (its **lab
folder**, `BENS-BGP-LAB/` above, or a subfolder of a shared repository) is where Save
progress writes `latest/`, `baseline/` and `checkpoints/`; those three are the
**snapshot folders** inside it. Repeated saves update the same `latest/` in place:
changed files get a new commit and an ordinary push, and Git history preserves the
earlier contents. Saving never creates `latest/latest`, a timestamped copy or a
checkpoint of its own; a separately named state is only ever made by **Create
checkpoint…**. Capture timestamps alone do not create an extra commit when the
configurations and meaningful metadata are unchanged.

Because `latest`, `baseline` and `checkpoints` are the names of the snapshot folders, they
cannot be a lab folder themselves: choosing `working/latest` in the folder browser resolves
to `working`, whose saves go to `working/latest`, and a typed folder name or an API request
naming such a folder is refused with that explanation. A folder named `latest` higher up
(`course/latest/working`) is an ordinary folder name and stays allowed.

**Set baseline…** changes `baseline/` explicitly. Replacing an existing baseline
requires review. **Create checkpoint…** creates a named milestone; choose a new name
for another milestone (the dialog shows the folder name it becomes as you type). The helpers reject unsafe paths, overlapping registered
destinations and unsupported repository layouts rather than guessing a location.

When one repository holds several labs, each lab registers a **subfolder** and the
whole `latest/`, `baseline/` and `checkpoints/` layout nests under it, for example
`bgp/latest/` and `eth/latest/`. Guided setup prompts for the subfolder; see
[GIT-SETUP.md](GIT-SETUP.md#one-repository-one-subfolder-per-lab). Each lab in the
manager connects to its own subfolder registration, so saving one lab never rewrites
another lab's folder.

## Everyday buttons

The lab header carries **Save progress** with a small menu (Create checkpoint…, Save on
this VM only, Saved versions & history, Save location settings…) that explains the option
under the pointer or the keyboard focus: what it does and where its result goes; the **Progress** tab
repeats them on its status card, whose **More ▾** adds the rest.

Every save asks a short question first — **What changed?** — before it reads a single device.
That label (up to 120 characters, one line, required) becomes the Git commit message and is how
the save is named everywhere afterwards: the pending list ("waiting to be uploaded"), *Recent
saves*, the save window and the commit history. A cancelled or interrupted save keeps its typed
label ready to offer again the next time you save; it is only forgotten once the save is actually
created. A save made before this label was required (or the checkpoint/baseline dialogs, which ask
for the same label under **What changed?**) falls back to its plain status sentence and date.

| Action | Result |
|---|---|
| **Save progress** | Ask for the save's label, then capture the configured device selection, export `latest`, commit changes on the VM, then open **Review before uploading**: what the save changed, with **Upload these changes** and **Not now — keep it on the VM**. Nothing is pushed without that choice (the manager refuses an upload that does not state the review, whatever an older save location setting said), and declining leaves the save on the VM as *Waiting for your review*. The save window opens on its own when something else needs you. A save that finds nothing new since a save that was already uploaded ends as *Saved to Git* with *Nothing changed since your last save*: there is nothing to review or upload, and it does not hold up a folder change. While the last save is still waiting for its review, a save with nothing new waits with it. |
| **Save on this VM only** | Capture and commit without pushing. |
| **Create checkpoint…** | Capture a named milestone in `checkpoints/<name>`. |
| **Set baseline…** | Select a complete recorded capture for `baseline`; replacing one is reviewed explicitly. |
| **Saved versions** (View / Compare with my latest save / Apply to running lab…) | The card lists *Latest*, *Checkpoints*, *Baseline*, the *Instructor and reference versions* kept in other folders of the repository and, folded, the other labs saving to it and everything else in the repository. *View* shows a version's files and offers the ZIP download; *Compare with my latest save* shows a real line-by-line diff of every changed file against the lab's `latest/` (never against the running devices), a device whose saved file changed extension between releases still reads as one changed file; *Apply to running lab…* replaces the running configuration of the selected devices (Junos, EOS or IOS XR) with that version (no reboot; backed up first) without changing where the lab saves. |
| **Full history…** | Every commit of the lab's folder with its versions. |
| **Upload saved progress** / **Review and upload…** | Publish a saved commit without recapturing devices, through the same review (a save reviewed before, whose upload failed, reads **Upload now**). |
| **Update from the repository** | Update an eligible clean checkout using a fast-forward; no merge/rebase conflict resolution. |
| **Recent saves** (Open / Review and upload… / Keep snapshot only) | One row per save with what happened; *Open* shows the save window with the details and retries. |
| **Save location settings…** / the *Save location* card | The repository and folder the lab saves to, the devices included in every save; **Change folder…** (unfolded when the card opens) holds the folder browser, *Git repo details* shows the push destination, branch, VM account and checkout path, **Browse the repository…** under *Saved versions* opens the same browser. |
| **Save this lab here** | Move this lab to the selected folder of its repository, optionally with the files already saved. |
| **New folder…** | Create a folder in the repository for this lab (or for a later lab). |
| **Use a different repository…** / **Connect by URL…** | Switch to another registered checkout, or connect a repository by its HTTPS URL. |

Every save window, the review before an upload and the pending-saves list show where a save is
going as `<repository> · <branch> · <path>` (for example `Course-Labs · main ·
Gtel-100G-G8032/Working/latest`), frozen at the moment the save is captured — moving the lab to a
different folder afterwards never rewrites an earlier save's own destination line. Beside it is one
of four plain states: *saved on this VM*, *waiting for your review*, *uploaded to `<remote>`* or
*verified on remote* (a save whose commit was carried along by a later upload of the same
folder). The Details under a save keep the exact checkout path on the VM and the commit.

<a id="where-this-lab-lives"></a>

## Save location

The **Progress** tab's *Save location* card names the repository and folder the lab
saves to. **Change folder…** (or **Browse the repository…** under *Saved versions*)
shows the connected repository as a file browser would: the folder path at the top, a
folder outline on the left and the contents of the selected folder on the right. The listing is the repository's current commit as it is on the VM,
so it matches what GitHub shows once the last save was pushed. The manager reads the
checkout through the Git helper; it never reads GitHub, and the browser sends only
registration IDs and folder names.

- Each folder with subfolders has an arrow that opens and closes it without selecting it; the
  tree keeps the branches you opened, your selection and the keyboard focus across refreshes.
  Looking at a folder never changes where the lab saves.
- The folder this lab saves to is tagged **This lab**; a folder another lab saves to is
  tagged with that lab's name. `latest/`, `baseline/` and `checkpoints/` are described in
  plain words. A folder that holds nothing yet reads *not in the repository until the first
  save*: Git keeps no empty folders, so the manager remembers the folders made or chosen here
  and keeps listing them, also after the lab moved to another folder (the VM registers only
  the folder a lab saves to now). **New folder…** without *Save … here from now on* only adds
  the folder to the list; **Remove empty folder** takes an unused one off it again. Neither
  changes anything in the repository or where the lab saves.
- **Save this lab here** moves the lab to the selected folder. The folder becomes the
  lab's registered destination, the device selection stays as it
  was, and the lab's previous folder registration is retired. When files were already
  saved under the old folder, the confirmation offers to move them along: every
  `latest/`, `baseline/` and `checkpoints/` file of the old folder is moved in one commit
  and pushed, and the move is recorded as a *Folder move* job with the same retry and push
  handling as a save. A folder move changes no configuration, so it is uploaded on that
  confirmation (the dialog says so) and has no separate *Review before uploading* step. Earlier versions stay in Git history either way; a pending
  save has to finish or be dismissed first.
- **New folder…** creates a folder beside the existing ones. It accepts a whole nested
  path such as `Week-04/BGP/Final-State`, so a deep destination like
  `CCNP-SP/Labs/Week-04/BGP/Final-State` is created in one step; the dialog shows the
  resulting `repository / folder` destination as you type. With *Save … here from now on*
  ticked, the lab moves into it immediately; otherwise, for a lab that already saves to
  this repository, the folder is only added to the manager's list (see above) and nothing
  is registered on the VM. For a lab that is not connected yet, the new folder is
  registered and preselected for **Connect**.
- Folders of one repository never overlap: a folder cannot be created inside another
  lab's folder or inside a saved configuration, `baseline/` and `checkpoints/` cannot be
  chosen as destinations, choosing a `latest/` folder means the folder above it (the
  browser says *Saves go to …/latest*), a folder that itself holds a `manifest.json` is a
  saved configuration and not a destination, and a repository that a lab saves to at its
  root cannot also hold lab folders unless that lab moves first. The manager and the VM
  helper enforce the same rules again, so a folder named `latest`, `baseline` or
  `checkpoints/<name>` is never registered as a lab folder.
- A lab that an older release registered at a `…/latest` folder keeps working exactly as
  it is (its saves go to `…/latest/latest`, and nothing is rewritten). To end the nesting,
  choose the folder above it with **Save this lab here** *without* moving the files: the
  next save updates the original `…/latest` snapshot again, and the nested copy stays in the
  repository as its own saved configuration (visible in the browser, appliable, and removable
  with Git on the VM whenever you want).

A moved lab keeps working with its old saves: *Saved versions* and *Full history…*
read the commits of the new folder, and the commit that moved the files lists
every file as moved. A dismissed save whose commit was never pushed stays outside the
new folder's history; publish it as the repository owner if it is still wanted.

Git commands are constructed by the helper from fixed operations. The UI accepts
repository IDs and reviewed choices, not arbitrary command lines. Commits include
the exact exported paths. A dirty checkout, unexpected staged work, changed branch
or remote, hooks/filters that alter exported files, or conflicting history can
require attention.
There is no force push, automatic stash, destructive reset or broad `git add .`.

Ordinary backup schedules still create manager backups. They do not automatically
publish configurations to Ben's remote repository. Saving progress is an explicit
action, and the downloads under **Tools › Configuration backups** remain available.

## Running account and persistence

```mermaid
flowchart TD
    A[Browser: trusted VM operator] --> B[Manager: capture and coordinate]
    B --> C[Encrypted manager state and immutable backup files]
    B -->|VM password over pinned SSH| D[clab-discovery forced gateway]
    D --> E[Restricted Git helper]
    E -->|Registered execution owner| F[Ben's working repository]
    F -->|Ben's external Git authentication| G[HTTPS Git remote]
```

The privileged entry point validates the registered owner/repository and drops
privileges before running Git. Git uses Ben's HOME, author configuration and
credential helper. The manager container neither mounts Ben's checkout nor needs
his token. The existing restricted VM SSH gateway stays in place.

The browser has no account login in this release. **Ben is the VM execution owner**,
not a signed-in web user. People with access to this manager share its authority
over the registered repositories. Use one trusted operator per VM, or a group
deliberately sharing that authority. Separate Ben/Alice browser permissions are
not implemented by registering two Linux owners.

| Data | Location / recovery requirement |
|---|---|
| Lab repository selection, scope and progress jobs | Encrypted manager state under `/srv/containerlab-node-manager/data`; keep `state.key` with `state.enc`. |
| Immutable captured configurations | Manager `backups/<lab-id>/history/<backup-job-id>`; included in a complete data archive. |
| Exported configurations and local Git commits | Ben's registered checkout; back it up independently until all intended commits are pushed. |
| Git credentials | Ben's external credential configuration; provision it again when rebuilding a VM. |
| Host registration | `/etc/clab-manager/git.json`, written by guided setup and by the manager's folder and connect actions through the helper; retain the root-owned registration when backing up the VM. |
| Host journal and transfer snapshots | `<checkout>/.git/clab-manager/`; retain these with the complete checkout for interrupted-save recovery. |

Back up the whole manager data directory, the registered checkout and its helper
registration/journal. A manager data archive alone does not include Ben's working
repository or external Git authentication. A remote Git repository alone does not
include unpublished snapshots, manager device credentials or diagram edits.

## Failure and recovery

```mermaid
flowchart TD
    A[Save needs attention] --> B{Last durable outcome}
    B -- Partial capture --> C[Fix device access; start a fresh capture]
    B -- Complete snapshot --> D[Fix checkout; Retry save, then review]
    B -- Local commit --> E[Fix login/network/remote; Review and upload, or Upload now]
    B -- Interrupted response --> F[Reconcile recorded job with host journal]
    C --> G[Keep previous latest until capture completes]
    D --> H[Reuse recorded capture]
    E --> I[Reuse recorded commit]
    F --> H
```

| Message or condition | Next step |
|---|---|
| A selected device failed | Inspect the save under **Recent saves** (or the backup under Tools › Configuration backups), repair access and start a new save. Successful files remain local; the repository's complete latest is retained. |
| Complete snapshot; repository needs attention | Resolve the reported checkout problem as Ben, then open that save under **Recent saves** and choose **Retry save, then review** (or **Retry save on this VM only**). |
| Commit exists; its review is still open or the push failed | **Review and upload…** on its row opens the review and uploads on your choice; after a reviewed upload failed the row reads **Upload now** (or use the banner's *Retry*). No new capture is needed. |
| Remote advanced / push rejected | Inspect the repository as Ben. Resolve divergence outside the app; never force push merely to clear the status. |
| Unexpected branch, URL, owner or repository identity | Restore the registered destination or deliberately register/reconnect the intended checkout after resolving pending work. |
| The wrong repository is connected | Choose **Use a different repository…** on the *Save location* card: pick another registered checkout, or connect the right one by its HTTPS URL. Nothing is deleted from either repository; files already saved stay where they are. |
| The lab saves to the wrong folder | **Change folder…** on the *Save location* card, select the intended folder and choose **Save this lab here**, optionally moving the files already saved. |
| Helper unavailable or older than the manager | Run `sudo bash "$HOME/projects/clab-manager/deploy/setup-git.sh" --refresh` from the source that matches the running manager and refresh repository status. |
| Manager restarted during a save | Open the recorded job and retry. The coordinator reconciles the recorded operation with the VM journal rather than silently recapturing. |
| Git authentication expired | Repair Ben's Git login on the VM, then retry the existing push. Changing the VM SSH password does not repair Git credentials. |

Active progress jobs prevent conflicting lab operations. Pending saves also block
actions that would forget or redirect their context, including removing the lab,
starting fresh, replacing the repository connection and changing the VM identity.
Password rotation for the same VM/account is allowed so that access can be repaired.

To stop pursuing a pending export, choose **Keep snapshot only** and confirm the
explicit dismissal. It retains the captured backup and any existing Git commit,
then permits disconnect/removal. This does not unpublish a remote commit or undo
files already saved to the checkout. A later **Start fresh** still deletes manager
backup files after its normal confirmation; Ben's checkout and Git remote remain
outside manager storage.

## Loading an earlier lab version

**View** on a saved version (or a commit in **Full history…**) retrieves its files:
review the manifest and download the configuration ZIP. Downloading does not
switch the repository branch, rewrite the original lab YAML or redeploy the lab.

Older backup jobs can have unknown topology provenance; the UI does not represent
the current topology as the topology used for that historical capture.

## Apply a saved configuration to a running node

A saved configuration (Junos, EOS or IOS XR today) can be applied to the running lab in two ways,
both of which converge the running node to exactly the saved configuration without a
reboot or a containerlab redeploy:

- **From the saved versions (simplest).** A saved configuration is any repository folder
  that holds a `manifest.json` written by a manager save, whatever the folder is called and
  however deep it sits: `Final`, `Broken`, `working/latest`, `course/lab/reference/solution`,
  even the repository root. On the **Progress** tab every such folder offers **Apply to
  running lab…** — the lab's own *Latest*, *Checkpoints* and *Baseline*, the *Instructor and
  reference versions* kept beside the lab folder and, folded, the other labs' saves and
  everything else in the repository, each row naming its exact folder. **Browse the
  repository…** (or *Save location › Change folder…*) reaches any folder with the same
  button: a folder with its own `manifest.json` applies that folder, and a folder whose only
  saved state is its `latest/` child applies `…/latest` (the caption says which). When both
  exist they are two different saved configurations and nothing is substituted. Folders that
  arrived with **Update from the repository** count as soon as they are there. The lab does
  **not** have to save to that folder — you can keep saving wherever you save and still apply
  Base, working, Final or Broken straight from their folders, and the next **Save progress**
  goes back to your own `latest/`. The folder's name only decides that it is listed; the
  manifest and its files decide what can be applied: a device saved before its platform could
  be restored, a damaged or missing file, a platform the manager cannot restore or a node that
  is not in the running lab is listed in the review with that reason and is not touched, and a
  manifest that cannot be read stops the review before any device is contacted.
- **The review is what gets applied.** The review names the repository commit the saved
  configuration was read from; replacing the configurations applies exactly that commit's
  files, so an **Update from the repository** between the review and the confirmation cannot
  swap in different bytes (a commit that is no longer in the branch history is refused, and
  the review is simply run again).
- **From a specific commit.** Open a version in **Full history…** and choose
  **Apply to running lab…** to apply that commit's snapshot.

```mermaid
flowchart TD
    A[Apply to running lab] --> B[Preflight: node running, reachable, platform, mapping]
    B --> C[Back up the current configuration first]
    C -->|backup failed| D[Do not change this node]
    C -->|backup ok| E[Load the candidate as a complete replacement, inside the device's own transaction]
    E --> F[Activate with a timed recovery: Junos commit confirmed, EOS commit timer, IOS XR commit replace confirmed]
    F --> G[Reconnect to prove management works, retried for the whole undo window]
    G -->|confirmed| H[Cancel the timer; EOS also saves it to startup; IOS XR confirms on the session that armed it]
    G -->|cannot confirm in time| I[Read the device back: applied, undone or uncertain]
    H --> J[Capture again and compare to the saved state]
```

- **Complete replacement, not a merge.** Junos `show configuration | display set` output
  can only be *added* with `load set`, so it cannot remove a statement a student added
  that is not in the saved version. Every Junos backup therefore also captures a
  hierarchical restore-grade candidate (`show configuration`) and records it in the
  snapshot manifest; the restore loads it with `load override terminal`, so a stale
  statement is removed, a changed statement is reset and a deleted desired statement is
  put back. EOS and IOS XR backups likewise capture the running-configuration as the
  restore candidate (`.eoscfg`, `.xrcfg`); because an EOS configuration session starts as a
  copy of the running configuration, the restore first empties it (`rollback clean-config`)
  before loading the candidate, while IOS XR's own `commit replace confirmed` replaces the
  whole configuration natively, in the same command that arms the timed recovery.
- **Backed up first.** The manager captures a fresh backup of every target node before it
  changes anything and references that backup's job id in the restore result. If the
  pre-restore backup fails for a node, that node is not modified.
- **Timed, confirmed activation.** The candidate is activated inside the device's own
  transaction with its own timed recovery (Junos `commit confirmed <minutes>`; EOS
  `commit timer HH:MM:SS`; IOS XR `commit replace confirmed minutes <N>`, which replaces the
  whole configuration and arms the timer in one native command). The manager then reconnects
  over SSH — retried for the whole undo window, not just once — to prove the node is still
  reachable, and only then confirms the change (Junos `commit`; EOS `configure session
  <name> commit`, followed by `write memory` since EOS does not save a confirmed change to
  its startup configuration by itself). On IOS XR only the CLI session that armed the change
  can confirm it, so the manager keeps that session open instead of closing it, proves with
  the fresh reconnect that management survived, and only then sends the confirming `commit`
  on the kept session; IOS XR persists a confirmed commit immediately, with no EOS-style
  separate save step. If the manager cannot confirm in time it never assumes the device
  rolled back: it reads the node back and reports whether the previous configuration is
  active (undone) or that it could not tell (uncertain) — the same check a manager restart
  during a restore also runs. The undo window defaults to five minutes and is adjustable
  under *Advanced options* of the review.
- **Root-authentication.** The `juniper_cjunosevolved` lab image boots without a
  `root-authentication` statement and rejects any later commit that still lacks it. When
  the saved configuration has no root-authentication, the restore synthesises one from the
  saved configuration's own superuser login password so the node stays reachable and can
  commit; this is the only statement the restore may add beyond the saved state.
- **Verified.** After confirming, the manager captures the node again, normalises it the
  same way a backup is normalised and compares it to the saved desired state, so the
  result shows that the stale statements are gone and the desired statements are present.
- **Supported platforms.** Live restore covers Junos (`juniper_cjunosevolved`,
  `juniper_vjunosswitch`), Arista EOS (`arista_ceos`) and Cisco IOS XR (`cisco_xrv9k`). A
  device on any other platform, or one this manager does not recognise, has its saved nodes
  listed in the review with the reason, not silently left out.
- **IOS XR banner limit.** A saved configuration that defines a `banner` is refused before
  the device is touched: pasting a banner's delimited body back in safely is not supported
  yet. Remove the banner from the desired saved state, or restore a version saved before it
  was added.
- **Management addresses travel with the saved state.** The candidate is the node's whole
  configuration, including its management interface address. When containerlab assigns
  management addresses dynamically, a redeploy can hand a node a different address; applying a
  state saved before that redeploy then moves the node off its address, the manager cannot
  reconnect, and the device undoes the change on its own — the manager then reads it back
  and reports that the previous configuration is active. Pin `mgmt-ipv4` on the nodes of
  any topology whose saved states will be applied after a redeploy.
- **Legacy snapshots.** A saved version made before a node's platform could be restored
  (before 1.28.0 for Junos, before 1.30.27 for EOS) has no restore artifact for that node:
  it is listed in the review as not applicable, with that reason, and its saved
  configuration text is never relabelled as a restore candidate. The rest of the saved
  version — the download, and any node whose platform was already restore-capable — is
  unaffected.

Captures retain their real format: Junos display-set output and IOS-XR/EOS running
configuration text are not universally interchangeable startup files, and each platform's
capture stays its own canonical human-readable and comparison form.

## Upgrade and validation

Upgrade the manager with the installer, retaining its persistent data; the
launcher refreshes the Git helper when a registry already exists. To refresh only
that helper, use `sudo bash "$HOME/projects/clab-manager/deploy/setup-git.sh"
--refresh` from the same source. This preserves registration IDs and revisions. Existing VM
passwords, labs, device profiles and backup files are retained. No remote repository is created,
and no user repository is pushed merely by installing the helper.

Registering unchanged settings preserves the ID, revision and original anchor
even when ordinary saves advanced HEAD. Changed settings create a new revision.
Use `--refresh` for routine code upgrades. Before changing
a registration, resolve pending saves and reconnect the lab afterward so it uses
the new revision. A registration binds the selected branch and push destination;
changing either outside the app requires deliberate registration and reconnection.

Before adopting the workflow on a real lab, verify a first save and unchanged save
against a disposable repository, then a locally saved commit and manual push retry.
Check baseline replacement, a named checkpoint and ZIP retrieval. Review the
release's [validation record](../clab-backup-ui/VALIDATION.md) for the exact automated
and platform-specific coverage. Linux owner switching, the external credential
helper, the selected Git service and real network devices need validation in the
deployment environment; a local source delivery does not establish those results.

The earlier [architecture proposal](archive/GIT-LAB-PROGRESS-PROPOSAL.md) records the broader
save-and-resume design. This guide describes the delivered save/export workflow;
the proposal's future restore and optional convenience stages remain separate work.
