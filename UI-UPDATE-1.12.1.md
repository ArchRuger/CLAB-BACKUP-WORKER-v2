# UI refinement — 1.12.1

**Deploy New Lab** replaces the sidebar's VM projects shortcut. It opens in the
same tab, showing a large **Lab Topologies** button and an Operation history
button. Nothing opens automatically. **Back to lab manager** returns to your
saved workspace in the same tab. Node SSH still opens separate terminal tabs.

The topology browser shows folders and `.clab.yaml` / `.clab.yml` files only.
Annotations, inventories and generated JSON remain available to automatic import;
they are simply hidden from topology selection. The helper filters before its
500-entry limit so unrelated files do not crowd out valid topologies.

Select a topology, then **Deploy lab**. Its confirmation states what will happen;
the exact Containerlab command is in expandable details. **Save to manager** is
the separate option for saving a workspace without deployment.

The saved lab's deployment status panel now includes **Start lab** and **Destroy
lab**. Start deploys an absent topology or starts existing stopped devices. Quick
actions require a known deployment state, connection and source path, and are
disabled while work is active. Destroy still uses confirmation and removes the
deployment; **Remove lab** only removes the saved manager workspace.

## Build and launch on your Ubuntu VM

This delivery contains source, not a published Docker Hub image. Extract it so
`deploy/` and `clab-backup-ui/` are directly in `~/projects/v1.12.1/`.
Keep `/srv/containerlab-node-manager/data` and your existing SSH key. If your
source-build installation customized `clab-backup-ui/.env`, carry those settings
to the new folder first.

For an existing **source-build installation**, run:

```bash
cd "$HOME/projects/v1.12.1"
sudo bash deploy/start-manager.sh --enable-operations --lab-root /etc/containerlab
sudo docker compose -f clab-backup-ui/compose.yml exec backup-ui \
  python -c 'from app import __version__; print(__version__)'
```

This updates/verifies helpers, retains installed keys, builds without cache and
recreates the manager. Confirm version **1.12.1**, then refresh the browser.

For an existing **Docker Hub / image-based Compose installation**, keep that
Compose workflow and your listening settings, but use a locally built image:

```bash
cd "$HOME/projects/v1.12.1"
# Adjust the previous folder if your installation files are elsewhere.
cp "$HOME/projects/v1.12.0/deploy/image.env" deploy/image.env
sudo bash deploy/setup-discovery.sh --update-helper
sudo bash deploy/setup-operations.sh --lab-root /etc/containerlab
sudo /usr/local/sbin/clab-manager-inspect | python3 deploy/verify-helper.py 1.12.1
printf '%s\n' '{"mode":"capabilities"}' | sudo /usr/local/sbin/clab-manager-operate \
  | python3 deploy/verify-operations.py 1.12.1
sudo docker build --pull --no-cache -t clab-backup:1.12.1 ./clab-backup-ui
```

Stop if either helper verification or the build fails. In `deploy/image.env`,
change only `MANAGER_IMAGE` to `clab-backup:1.12.1`, retaining `UI_BIND` and
`UI_PORT`. Then:

```bash
sudo docker compose --env-file deploy/image.env -f deploy/compose.image.yml \
  up -d --no-build --pull never --force-recreate
sudo docker compose --env-file deploy/image.env -f deploy/compose.image.yml \
  exec backup-ui python -c 'from app import __version__; print(__version__)'
```

These changes do not require new keys or a data reset. The supplied Hub tag
`archtop/clab-backup:1.12.0` remains the older image until you publish another tag.

## Validation

Focused regression checks cover filtering mixed folders before the entry cap,
selecting deploy versus start, disabling unsafe quick actions and preventing an
automatic browser dialog. The UI was checked against an isolated local fixture:
same-tab navigation, explicit topology selection, hidden inventory/annotation
files, deployment confirmation and cancellation. No commands ran against a real
training VM during verification. Linux Docker build and device behavior still
need checking on the deployment VM.
