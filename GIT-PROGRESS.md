# Save lab progress to Git — 1.15.1

Connect a lab to an existing repository on its VM once, then use **Save progress**
to capture its selected devices, save the complete capture in that repository,
commit changed configurations and push. Ben keeps his existing Git login and
commit identity. The manager never asks for his Git token.

This is a local source release. Build the 1.15.1 image and install its matching VM
helpers; a previously published image does not acquire these features automatically.
See [Fresh VM setup](FRESH-VM-GUIDE.md) and [VM connection](VM-CONNECTION.md).

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
    H --> J[Push]
    I --> J
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

Start with [GIT-SETUP.md](GIT-SETUP.md). From the release source on the Ubuntu VM,
run this as the existing ordinary account, without sudo:

```bash
bash deploy/setup-git.sh
```

The guided flow prepares the checkout, owner-scoped HTTPS login and commit
identity, then registers the current branch after noninteractive validation.
No additional Linux account is needed on a standalone VM. Linux and GitHub
usernames do not need to match. Existing working installations should upgrade
with `start-manager.sh` or `setup-git.sh --refresh` and retain their current owner.

In the lab, choose **More → Git repository**, select the registered checkout and
devices, review the destination and save the connection. **Save progress** then
captures, commits and pushes automatically. A separate Commit button is not needed.

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
node identity and configuration format. Repeated saves update `latest/`; Git
history preserves earlier contents. Capture timestamps alone do not create an
extra commit when the configurations and meaningful metadata are unchanged.

**Set baseline** changes `baseline/` explicitly. Replacing an existing baseline
requires review. **Save checkpoint** creates a named milestone; choose a new name
for another milestone. The helpers reject unsafe paths, overlapping registered
destinations and unsupported repository layouts rather than guessing a location.

## Everyday buttons

| Action | Result |
|---|---|
| **Save progress** | Capture the configured device selection, export `latest`, commit changes and push; a review preference pauses before push. |
| **Save locally** | Capture and commit without pushing. |
| **Save checkpoint…** | Capture a named milestone in `checkpoints/<name>`. |
| **Set baseline…** | Select a complete recorded capture for `baseline`; explicitly review replacement. |
| **View changes / History** | Inspect saved versions and compare configurations. |
| **Push saved progress** | Publish the existing saved commit without recapturing devices. |
| **Update from remote** | Update an eligible clean checkout using a fast-forward; no merge/rebase conflict resolution. |
| **Load version…** | Inspect or download a baseline, checkpoint or historical version as a ZIP. |
| **Git repository settings** | Choose a registered repository and explicit device selection. |

Git commands are constructed by the helper from fixed operations. The UI accepts
repository IDs and reviewed choices, not arbitrary command lines. Commits include
the exact exported paths. A dirty checkout, unexpected staged work, changed branch
or remote, hooks/filters that alter exported files, or conflicting history can
require attention.
There is no force push, automatic stash, destructive reset or broad `git add .`.

Ordinary backup schedules still create manager backups. They do not automatically
publish configurations to Ben's remote repository. Saving progress is an explicit
action, and existing **Backup history** downloads remain available.

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
| Host registration | `/etc/clab-manager/git.json`; retain the root-owned registration when backing up the VM. |
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
    B -- Complete snapshot --> D[Fix checkout; Retry export]
    B -- Local commit --> E[Fix login/network/remote; Push saved progress]
    B -- Interrupted response --> F[Reconcile recorded job with host journal]
    C --> G[Keep previous latest until capture completes]
    D --> H[Reuse recorded capture]
    E --> I[Reuse recorded commit]
    F --> H
```

| Message or condition | Next step |
|---|---|
| A selected device failed | Inspect **Backup history**, repair access and start a new save. Successful files remain local; the repository's complete latest is retained. |
| Complete snapshot; repository needs attention | Resolve the reported checkout problem as Ben, then **Retry export** from that job. |
| Commit exists; push failed or review is required | Review the recorded commit and use **Push saved progress**. No new capture is needed. |
| Remote advanced / push rejected | Inspect the repository as Ben. Resolve divergence outside the app; never force push merely to clear the status. |
| Unexpected branch, URL, owner or repository identity | Restore the registered destination or deliberately register/reconnect the intended checkout after resolving pending work. |
| Helper unavailable or older than the manager | Run `sudo bash deploy/setup-git.sh --refresh` from the 1.15.1 source and refresh repository status. |
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

**Load version** retrieves files. Select `baseline`, a checkpoint or a previous
commit, review its manifest and download the configuration ZIP. It does not switch
the repository branch, rewrite the original lab YAML, redeploy the lab or apply
commands to running routers.

Captures retain their real format: Junos display-set output and IOS-XR/EOS running
configuration text are not universally interchangeable startup files. Device apply
and one-click restore remain unavailable until each NOS adapter has been validated
with recovery capture, management-access checks and partial-failure handling.
Older backup jobs can have unknown topology provenance; the UI must not represent
the current topology as the topology used for that historical capture.

## Upgrade and validation

Upgrade the manager from the 1.15.1 source, retaining its persistent data.
`deploy/start-manager.sh` refreshes the Git helper when a registry already exists.
To refresh only that helper, use `sudo bash deploy/setup-git.sh --refresh` from
the same source. This preserves registration IDs and revisions. Existing VM
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
release's [validation record](clab-backup-ui/VALIDATION.md) for the exact automated
and platform-specific coverage. Linux owner switching, the external credential
helper, the selected Git service and real network devices need validation in the
deployment environment; a local source delivery does not establish those results.

The earlier [architecture proposal](GIT-LAB-PROGRESS-PROPOSAL.md) records the broader
save-and-resume design. This guide describes the delivered save/export workflow;
the proposal's future restore and optional convenience stages remain separate work.
