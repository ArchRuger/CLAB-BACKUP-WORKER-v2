# Course states: Start, Broken and Final

A guide for the person who builds a course. It shows how to turn one working lab into
the **lab states** a student can load onto their own devices (a *Start*, a *Broken* and a
*Final*), what the repository looks like afterwards, and what has to be true on the
student's side for a state to fit. It uses the words of the page: **Save**, **Upload**,
**Save as a lab state…**, **Load**, **Lab states** and **Undo this load**. The names the
manager depends on, and the recommended layout of a course repository, are in
[Naming and structure for lab courses](NAMING.md); how saving and loading work in daily use
is in [Save and load](GIT-PROGRESS.md).

## What a lab state is

A lab state is a complete save of a lab, kept in a folder of its own in the repository, that
no lab saves into any more. It holds the same things as every save: the topology file, the
map and the configuration of every included device, together with the files the manager needs
to put each configuration back on a running device. Because it is an ordinary saved folder,
every lab that uses the repository can see it: it is listed under **Lab states** in **Load**
and in **All versions**, and a student loads it with three clicks.

Nothing about a lab state is special on the repository's side. **Save as a lab state…** writes the
lab's current state into a folder you choose, as one commit on the lab VM, without changing the
folder where the lab normally saves.

## Make Start, Broken and Final

Do this on your own VM, with the course lab running and its devices in the configuration the
state should hold. A state is what the devices run **now**: the manager reads them when you save.

1. Bring the lab to the state you want to record: for *Start*, the configuration a student begins
   with; for *Broken*, the same lab with the fault introduced; for *Final*, the finished,
   working configuration.
2. In the lab header, click the **save chip** (for example *Saved 21 min ago*). The chip panel
   opens.
3. At the bottom of the panel, click **Save as a lab state…**. The drawer *Save as a lab state*
   opens. (The same button is in **All versions**, under **Lab states**.)
4. Under **Name**, click one of the one-click names **start**, **broken** or **final**, or type
   your own. The name is also the name of the folder.
5. Look at **Folder**. It starts as `<the lab's folder>/<name>`: if the lab normally saves into
   `BGP`, the state `start` goes to `BGP/start`. You can pick another folder in the tree, type a
   path, or make a folder with **New folder…**; the line under the field says what the manager
   will do with it. If the lab has no save location yet, the folder starts as
   `<a folder named after the lab>/<name>`.
6. Click **Save state**. The drawer closes with the message *State start saved in BGP/start.* and
   the chip reads *Saving…* while the manager reads the devices and writes the state.
7. The state is on the lab VM only. The chip now reads *1 save to upload*. Click the chip, then
   **Upload**: nothing reaches the online repository without that click, and students cannot get
   the state before it does.

Repeat steps 1 to 7 for the other states. You can do all three in one sitting: bring the lab to
*Broken*, save it as a lab state, then fix it and save *Final*.

**If a state of that name already exists** in the folder, the drawer asks one question with
buttons: *"start" already exists here.* **Replace it** saves the new state over it (the older
contents stay in the Git history) and **Use another name** takes you back to the name field.
Where the folder is the very folder another lab saves into, the manager suggests a folder beside
it instead and says so.

Saving a lab state does not change where your own lab saves, does not change your lab's
**Saves to:** line and does not count as "your latest save": **Save** continues as before.

## What the repository looks like afterwards

For a course repository `Course-Labs` and a lab named `BGP` that saves into the folder `BGP`:

```text
Course-Labs/
  BGP/
    latest/                    your own saves of the lab (what Save writes)
      manifest.json
    start/
      latest/                  the state "start"
        manifest.json
        <device>.cfg           one configuration per included device
        <lab>.clab.yml         the topology
        <lab>.clab.yml.annotations.json   the map
    broken/
      latest/                  the state "broken", same layout
    final/
      latest/                  the state "final", same layout
```

The file names are generated from the device names and the configuration format, and the lab's
own folder is only an example; a course can keep its states anywhere in the repository. What
makes a folder a saved state is the `manifest.json` that the manager wrote into it. The recommended
course layout and naming are in [NAMING.md](NAMING.md).

## How students get the states

Students use the course repository, or a copy of it (a fork or a clone of their own), registered on
their VM through [Git setup](GIT-SETUP.md). The states reach a student's VM when its checkout is up
to date with the online repository:

1. Upload the states from your VM (step 7 above).
2. On the student's VM, **Update from the repository** downloads the newest files, for example
   the states you added. The chip panel offers it when it says *The online copy has changes this VM
   does not have.* and it is also in the lab's **Save settings**, under *Git details*. It is a
   fast-forward: it is offered only when nothing waits for upload, and it never changes running
   devices.
3. After that, the states are listed under **Lab states** in **Load**.

For a state to fit the student's lab, three things must be the same as on your lab.

- **The lab name.** The manager matches a saved device to a lab device by its **full node name**,
  and for the default containerlab prefix that name is `clab-<lab>-<node>`: the device `ce1` of
  the lab `bgp-core` is `clab-bgp-core-ce1`. The student's lab must have the same lab name as the
  lab the states were saved from, which means the same containerlab `name:` in the topology file
  (and the same node names). A student who deploys the course topology under another name gets the
  row *Not in this lab* for every device, and nothing is loaded. Give every student the exact
  topology file you saved the states from.
- **The platform.** A device is matched by node name and platform; a saved Arista device is never
  loaded onto a Juniper node of the same name.
- **The management addresses.** A saved configuration carries the device's management address, so
  a state only fits a lab whose devices have the addresses it was saved with. Pin them in the
  course topology with `mgmt-ipv4` on each node, so that every deployment, yours and every
  student's, gives each device the same management address. If the addresses differ, the device can
  lose contact after the load; every load arms the device's own timed recovery, which undoes the change
  when the manager cannot reach the device again, so nothing is left half done, but the state is not
  loaded.

## How a student loads a state

Three clicks, in a lab that is running:

1. **Load** in the lab header. The panel lists the lab's own saves and checkpoints under
   *Your saves* and the course's states under **Lab states**.
2. Click the state, for example *start*. The panel checks the devices and lists every device with
   what would change (*3 lines differ*, *Already matches*, or the reason a device cannot be
   loaded).
3. Click the red **Load**.

Each device replaces its whole running configuration inside its own transaction, after the manager
has backed it up automatically; nothing reboots, and a device that loses contact undoes the change
itself. Loading never changes the topology. When it is done the chip reads *Running start*.

**Undo this load.** The chip panel, shown by clicking the chip after a load, has **Undo this load**.
It is an ordinary load of the backup the manager took before the load: the same review, the same red
**Load**. It is offered for as long as that backup is kept; when it is not, the panel says why.

A student who wants to keep their own work as it is first clicks **Save**, or **Keep as a checkpoint**
on that save: **Load** replaces the running configuration, and a save of their own is the version they can
come back to by name.

## What can go wrong, and what to tell students

**A view-only state.** A state that was saved without the files needed to load it appears in the list
with the words *Saved without the files needed to load it* and *View only*. It has **View** instead of
a load button. It can be read and downloaded, never loaded. A state needs the restore files, and every
save made by a current manager for a platform it can restore (Arista EOS, Juniper cJunosEvolved and
vJunos-switch, Cisco IOS XR) has them. To avoid a view-only state, make the states with a current
manager, on a lab whose devices are of those platforms, and do not use a plan exported from
*Network design* as a state: a design export is view and download only.
A state saved by an older manager, or one made from devices whose platform cannot be restored, is the
usual cause; save it again with a current manager.

**A state that covers only some devices.** When the states list shows *2 of 4 devices*, the state can be
loaded onto two of the lab's four devices: the other two were not included when it was saved (check
**Save settings** on your lab: *Devices included in every save*), have no device of the same full name and
platform in the student's lab, or have a platform that cannot be restored. Loading it replaces the two covered devices and leaves the others exactly as they are;
the confirmation says so (*This state covers 2 of your 4 devices. The others are left as they are.*) and
lists the others as *Not in this state*. To make a state that covers every device, include every device
in **Save settings** before you save it.

**A state from a different topology.** If the topology the state was saved on is not the lab's current
topology (a different set of devices or links), the confirmation says *Saved on a different topology: n of
m devices match.* with **View its topology**. The devices whose full name and platform match can still be
loaded; the others are listed as *Not in this lab*. The manager never changes the lab's topology to fit a
state, so a student whose lab was changed after you saved the states has to restore the course topology
first.

**Start the lab first.** **Load** needs a running lab. For a stopped lab the panel says *Start the lab to
load a state*, with the button that starts it.
