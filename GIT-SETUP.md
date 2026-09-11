# Git setup — start here

Use your **existing Ubuntu VM account**. On a standalone VM, you do not need an
additional Linux user. The VM username and GitHub username can be different.

## First setup

1. Install/start the manager using [FRESH-VM-GUIDE.md](FRESH-VM-GUIDE.md), configure
   its VM password, and confirm that a manual device backup works.
2. On GitHub, create the repository that will hold your configurations. Choose
   the intended visibility and **Add a README** so it has an initial commit.
   Copy **Code → HTTPS**, for example `https://github.com/OWNER/REPOSITORY.git`.
   A browser address ending in `/tree/main` is not a clone URL.
   Your GitHub account needs write access.
3. In the VM terminal, as your ordinary account, enter the release source
   directory and run this command **without sudo**:

   ```bash
   bash deploy/setup-git.sh
   ```

The wizard shows the Linux account it will use, then:

- Installs missing Git/GitHub CLI packages through sudo, if you choose to do so.
- Offers to clone a repository into `~/labs/REPOSITORY`, or reuse an existing checkout.
- Reuses a GitHub login or opens GitHub's browser authorization flow for that account.
- Configures the Git credential helper and asks for missing commit author name/email.
- Checks GitHub repository write permission, then asks to register the displayed checkout.
- Registers its current branch after checking ownership, identity, clean managed
  files, remote synchronization and a **push dry run**. Setup does not create or push commits.

**On a VM without a browser:** copy the one-time code, press Enter when prompted,
and open the displayed URL in your workstation browser. A message about a missing
browser on the VM is expected. Keep the terminal open until authorization completes;
do not press Ctrl+C. This is [GitHub CLI's login flow](https://cli.github.com/manual/gh_auth_login).

**Checkout directory** means the local repository on the VM, for example
`/home/archtop/labs/my-bgp-lab`. The wizard clones into that directory; subsequent
saves write `latest/`, `baseline/` or checkpoints inside it. It is separate from
the manager's application source directory under `~/projects/`.

Finally, open your lab in the manager → **More → Git repository**, select the
checkout and devices, review the destination, and save the connection settings.
Click **Save progress**. It captures, exports, commits and pushes automatically;
there is no separate Commit button. Confirm the save reports **Pushed** and the
repository contains `latest/` with configurations and `manifest.json`.

```mermaid
flowchart TD
    A[Existing VM account] --> B[Run guided setup]
    B --> C[GitHub login in workstation browser]
    C --> D[Clone or reuse checkout]
    D --> E[Commit identity and access checks]
    E --> F[Register current branch]
    F --> G[Select repository and devices in manager]
    G --> H[Save progress: capture, commit, push]
    H --> I{Push verified?}
    I -- Yes --> J[Progress saved to Git]
    I -- No --> K[Keep snapshot and retry the same save]
```

## Already working? Upgrade without setting it up again

Keep your current Linux owner, checkout and login, including a separate account
you have already configured. From the new source, use the normal launcher:

```bash
sudo bash deploy/start-manager.sh
```

The launcher refreshes an installed Git helper and retains registrations,
passwords and manager data. For a helper-only refresh:

```bash
sudo bash deploy/setup-git.sh --refresh
```

Do not clone again or create another Linux account just to upgrade. Guided setup
can be rerun after interruption: if cloning completed, select **existing** and the
same checkout. If it stopped during package installation/login before cloning,
select **clone** again. It
keeps existing author settings and files. Re-registering unchanged settings keeps
the registration ID/revision; changed owner, branch, destination or prefix needs
pending saves resolved and the lab reconnected.

## Package installation recovery

If `sudo apt-get update` fails with `file:/cdrom ... Release` or `cdrom:`, Ubuntu
still has an installation-media source enabled. Locate the entry:

```bash
sudo grep -nHE 'file:/+cdrom|cdrom:' /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources
```

A missing-file message for an unused format is harmless. Open the matching file
with `sudo nano /actual/path/from/output`, and disable only its installation-media
entry. For `sources.list` or a `.list` file, put `#` before the matching `deb` line.
For a `.sources` file, add `Enabled: no` to the media-only stanza (or change its
existing `Enabled` value). If that stanza lists both media and network URIs,
remove only the media URI instead. Keep Ubuntu network mirrors, security updates
and Docker entries enabled. These are the supported
[APT source formats](https://manpages.ubuntu.com/manpages/noble/man5/sources.list.5.html).
Save in nano with **Ctrl+O**, **Enter**, then **Ctrl+X**.

Run these in order; continue only after each command succeeds:

```bash
sudo apt-get update
sudo apt-get install -y git gh
bash deploy/setup-git.sh
```

Run the wizard as your ordinary VM account, without sudo. If it stopped before
cloning, choose **clone**, enter the repository HTTPS URL without `/tree/main`,
and accept its repository-named checkout directory. No manager rebuild is needed
for this VM package-source repair. Other APT errors (network, sudo, unavailable
package or signature failures) require resolving the specific message; do not
bypass repository signature checks. Setup does not edit system package sources.

## Which account/password goes where?

| Item | Purpose | Where it persists |
|---|---|---|
| Existing Linux account, e.g. `archtop` | Owns checkout and runs Git | VM account database and that user's home |
| GitHub account | Authorizes HTTPS access to the remote repository | Owner's configured Git credential helper |
| Commit name/email | Records authorship; does not log in to GitHub | Repository `.git/config` when the wizard supplies it |
| `clab-discovery` password | Connects the manager to the VM's restricted gateway | VM hash in `/etc/shadow`; manager copy encrypted in its persistent data |

GitHub does not accept a website password for HTTPS Git push. The wizard uses
GitHub CLI and [configures its credential helper](https://cli.github.com/manual/gh_auth_setup-git).
The manager never collects GitHub tokens. GitHub CLI uses a system credential
store when available; on a headless VM it may report storing credentials in the
owner's configuration file. Keep that home directory private and on persistent
storage. Shell-only tokens or credentials under another user's home will not be
available to unattended manager saves.

## Fix a failed save

Open the **original failed save** from progress history. Its snapshot is already
preserved. Repair the stated problem, then use its **Retry export and push** or
**Push saved progress** button. Retry uses the existing snapshot/commit.

| Symptom | Action |
|---|---|
| Linux owner does not exist | Use your actual VM account. `--owner` is not a GitHub username. |
| Missing checkout / `.git` | Use the wizard's Clone option. `mkdir` creates a folder, not a repository. |
| Permission denied | Check who owns the checkout. Clone as its intended owner; do not use `sudo git clone` or recursively change ownership of an existing project. |
| `gh` missing / owner not in sudoers | Your VM administrator installs `gh`. Authenticate as the repository owner. The owner does not need sudo membership to use Git or the manager. |
| Invalid username/token or interactive password prompt | Run the commands below **as the registered Linux owner**, then retry the original save. |
| Missing commit identity | Inside the checkout, set `git config --local user.name "Your Name"` and `git config --local user.email "your-email"`. Retry the original save. |
| Already staged changes after a failed manager export | Retry the original failed save after fixing its error. Do not start another save or manually commit its staged files. Resolve unrelated staged work separately. |
| You already committed the manager files manually | As the owner, publish that manual commit with normal Git. Check it reached the remote. In the manager dismiss the old export using **Keep snapshot only**, then start a new save. The manager does not automatically push unrelated/manual history. |
| Local and remote branch differ | Inspect `git status -sb` and resolve synchronization as the owner. Setup does not reset, merge, stash or force-push your work. |
| Push rejected despite successful setup | Check branch protection/rules, current write permission and credential expiry. A dry run checks transport/access but cannot guarantee a later changed commit passes every server rule. |

Authentication repair, as the **repository owner**, without sudo:

```bash
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git --hostname github.com
```

If already logged into the wrong GitHub account, use `gh auth switch --hostname
github.com` to select an existing login or run login again to add the intended account.
Do not paste credentials into the remote URL or manager UI.

## Advanced: separate owner, other HTTPS host, or managed prefix

The wizard supports GitHub with `origin`. For another HTTPS provider, complete
that provider's persistent credential-helper setup as the repository owner first;
the wizard can clone/register after you confirm it is configured.

For an existing checkout, the VM administrator can register directly:

```bash
# Defaults to the ordinary account invoking sudo:
sudo bash deploy/setup-git.sh --repo "$HOME/labs/my-lab"

# An existing separate owner does not need to be in sudoers:
sudo bash deploy/setup-git.sh --owner patrick --repo /home/patrick/labs/patricks-bgp-lab
```

For a separate owner, prepare its checkout/login/identity under that account, then
return to the administrator for registration. Optional `--remote NAME`,
`--label "Display name"` and `--prefix labs/bgp` select an existing remote,
display label and managed subfolder. Prefixes must not overlap. A normal checkout
with an existing published commit is required; linked worktrees, submodules,
bare repositories and symbolic-link paths are unsupported.

Back up the complete checkout including `.git`, the owner's credential recovery
method, `/etc/clab-manager/git.json` and manager data separately. The manager data
backup does not include the repository or the owner's Git login. Detailed save,
review and recovery behavior is in [GIT-PROGRESS.md](GIT-PROGRESS.md).
