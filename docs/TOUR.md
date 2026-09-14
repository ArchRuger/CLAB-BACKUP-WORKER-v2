# Tour

Screenshots taken on the development VM: Ubuntu 24.04, containerlab 0.79, two
Arista cEOS nodes wired `eth1` to `eth1`. Every image is the real UI as a browser on
a workstation sees it, captured with a scripted headless browser; nothing is mocked.
The lab header has since gained a **Grafana ↗** button that opens the lab's live
dashboards and map ([TELEMETRY.md](TELEMETRY.md)); the rest is as shown.

![Lab overview](images/00-hero.png)

## From a topology file to a working lab

**Nothing to import by hand.** With no lab saved, the workspace asks for the VM
connection once and then leads with deployment. Labs already running on the VM
appear here with a one-click Import.

![Landing page](images/10-landing.png)

**Pick a topology on the VM.** The browser lists the trusted lab folders; expand
one and choose a `.clab.yaml`.

![Topology browser](images/11-topology-browser.png)

**Read it, then deploy it.** The file is shown read-only. *Deploy lab* saves the
workspace first, so the lab is in the sidebar before containerlab starts.

![Topology editor](images/12-topology-editor.png)

**Every host command is reviewed before it runs.** The exact containerlab command,
the affected containers and the warnings are shown; nothing runs until you confirm.

![Deploy review](images/13-deploy-review.png)

**Watch it run, see it succeed.** Output streams in; the banner turns green with the
exit code when containerlab is done.

![Deploy running](images/14-deploy-running.png)

![Deploy succeeded](images/15-deploy-succeeded.png)

**A running container is not a usable device.** cEOS, Junos and XRv9k keep booting
for a minute or more after the container starts. The manager logs in to each node
and asks for `show version` until the network OS answers, and says so in the
deployment bar.

![NOS booting](images/16-nos-booting.png)

**Ready means ready.** When every node answers, SSH opens on each one and the login
test runs by itself. No credential profile was created for this lab: the nodes use
containerlab's documented default login until you assign one. The whole sequence,
from clicking *Deploy lab* to *NOS ready*, took 65 seconds here.

![NOS ready](images/17-nos-ready.png)

![Nodes after deployment](images/18-nodes-after-deploy.png)

![Automatic login test](images/19-automatic-login-test.png)

## Working on the lab

**One map, every action.** Right-click a node for packet capture, an SSH terminal,
a configuration backup or its details. Click a link to capture either end.

![Node menu](images/02-node-menu.png)

**SSH in a browser tab**, with the node's own CLI and the credentials the manager
already holds.

![SSH terminal](images/05-ssh-terminal.png)

**Configurations that outlive the lab.** Back up on demand or on a schedule; every
device configuration is kept with history, downloadable one by one or as an
archive.

![Backup history](images/04-backup-history.png)

**Save progress to Git.** With a repository registered on the VM, one button
captures the configurations, commits and pushes with your own login; the bar shows
where the lab is saved.

![Lab overview with a registered repository](images/01-lab-overview.png)

**Every node at a glance.** Address, platform, which login is in use, the last SSH
check and the last backup, with the actions next to each row.

![Nodes](images/03-nodes.png)

## Packets from the browser

**Only the ports that matter.** Opening capture from a node lists the interfaces the
topology wires to it; the other Linux interfaces and the advanced target selector
stay folded away.

![Capture dialog](images/06-capture-dialog.png)

**Wireshark on the VM, in your browser.** The session runs in an isolated container
next to the lab and streams to the tab; nothing is installed on the workstation.
Here a ping between the two nodes crosses the captured link.

![Wireshark in the browser](images/07-wireshark-in-browser.png)

## Picking up a lab that already runs

**Deployed outside the manager?** Discovery sees it within 30 seconds; the landing
page offers it, and Import reads the lab files from the VM after you confirm.

![Landing page with a running lab](images/08-landing-running-lab.png)

![Import from VM](images/09-import-from-vm.png)
