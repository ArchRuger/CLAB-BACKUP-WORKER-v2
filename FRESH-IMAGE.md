# Fresh image and worker upgrade — 1.6.1

Use the corrected **CLAB-BACKUP-WORKER-v2 1.6.1 source ZIP** or a checkout containing
these fixes. The changes were prepared locally against v2 commit `06b8624`; they
have not been pushed to GitHub. Cloning the unchanged remote does not include them.

These commands run on your Linux Docker/containerlab host. They have not been run
against your lab. Your supplied YAML uses worker `Backup-Worker`, image
`clab-backup:1.6.0`, and port `10.150.2.212:8081:8080/tcp`.

## 1. Build from the corrected source

From the extracted repository root, containing `clab-backup-ui/`:

```bash
docker build --pull --no-cache -t clab-backup:1.6.1 ./clab-backup-ui
docker run --rm --entrypoint python clab-backup:1.6.1 \
  -c "from app import __version__; print(__version__)"
```

Expected output: `1.6.1`. The final `./clab-backup-ui` is the required build context.
If already inside that directory beside `Dockerfile`, use `.` instead.
`--no-cache` rebuilds the layers; `--pull` checks for a fresh base image.
Building requires access to the base image, Debian/Python packages, and Ansible
collections, or equivalent internal mirrors. See [Docker build guidance](https://docs.docker.com/build/building/best-practices/).

## 2. Preserve the existing worker data before replacing it

**The supplied lab YAML has no `/data` mount.** Without a mount, removing the old
worker removes its saved inventory, credentials, encryption key, and backup history.
Check the actual running container, since it may differ from the uploaded YAML:

```bash
worker=clab-BGP_TheoryToPractice-Backup-Worker
docker inspect --format '{{json .Mounts}}' "$worker"
```

Take a consistent copy before changing the worker. Choose a persistent directory
on the host, outside any generated `clab-*` directory. Stop only this worker;
routers remain running. The copy includes the encryption key and must be kept private.

```bash
docker stop "$worker"
backup_dir=$(mktemp -d "$HOME/node-manager-data.XXXXXX")
sudo docker cp -a "$worker:/data/." "$backup_dir/"
sudo test -s "$backup_dir/state.key" && sudo test -s "$backup_dir/state.enc"
echo "Saved data directory: $backup_dir"
```

If either copy or validation fails, **stop here**, restart the existing worker with
`docker start "$worker"`, and resolve the copy before recreating anything.
[Docker cp supports stopped containers](https://docs.docker.com/reference/cli/docker/container/cp/).

If `/data` already has a persistent mount, retain that exact mount in the worker
configuration; the copy above is a recovery snapshot. If it has no mount, use the
saved directory as the persistent data directory:

```bash
sudo chown -R 10001:10001 "$backup_dir"
sudo chmod 700 "$backup_dir"
```

In `BGP_TheoryToPractice.clab.yaml`, update only the `Backup-Worker` entry. Replace
the example absolute path with the exact directory printed above. Preserve any
other existing worker settings and other mounts:

```yaml
    Backup-Worker:
      kind: linux
      image: clab-backup:1.6.1
      binds:
        - /home/YOUR_USER/node-manager-data.ACTUAL_SUFFIX:/data
      ports:
        - 10.150.2.212:8081:8080/tcp
```

The container runs as UID 10001 and must be able to access the mounted directory.
If a host security policy restricts bind mounts, use your established persistent
volume procedure with the same saved contents instead.

## 3. Recreate only the worker

From the directory containing the lab YAML:

```bash
sudo containerlab deploy -t BGP_TheoryToPractice.clab.yaml \
  --reconfigure --node-filter Backup-Worker
docker exec "$worker" python -c "from app import __version__; print(__version__)"
docker inspect --format '{{.Config.Image}} {{.Image}}' "$worker"
```

Keep both `--reconfigure` and `--node-filter Backup-Worker`: this selects the worker
for recreation. Do not run an unfiltered lab redeploy for this application upgrade.
See [containerlab deploy and node filtering](https://containerlab.dev/cmd/deploy/).
If your installed containerlab does not support these flags, check its `deploy --help`
before continuing. A Docker restart alone keeps the existing container's old image.

The running version must print `1.6.1`; the image reference must be
`clab-backup:1.6.1`. Open `http://10.150.2.212:8081`, refresh with Ctrl+F5, and confirm
**Containerlab Node Manager · v1.6.1** in the footer. Your screenshot showed v1.5.0,
which predates the right-click menu.

## 4. Reimport the drawing and check actions

1. Confirm your saved lab, credentials, and backup history remain available.
2. Choose **Topology → Import topology** and upload the original
   `BGP_TheoryToPractice.clab.yaml.annotations.json` plus the matching
   `BGP_TheoryToPractice.clab.yaml` (or `topology-data.json`).
3. Expect **13 map nodes · 16 links · 0 unmatched**. Reimport updates the drawing
   without replacing inventory, credentials, schedules, or backup history.
4. Right-click directly on a node icon or name. The menu offers **SSH**,
   **Back up configuration**, and **Node details**. SSH opens a new browser tab.
   Actions are enabled according to that node's saved credentials and backup support.
5. Test one real SSH connection and one backup on the lab. Local release checks used
   a simulated SSH server; they did not access your devices.

## Compose installations instead

If the worker is managed by Compose rather than as a containerlab node, preserve
the existing project name and `/data` volume. From `clab-backup-ui/` in the same
Compose project:

```bash
docker compose build --pull --no-cache backup-ui
docker compose up -d --no-build --force-recreate backup-ui
docker compose exec backup-ui python -c "from app import __version__; print(__version__)"
```

Do not use `down -v`; it deletes volumes. Verify the resolved volume with
`docker compose config` before switching source directories or project names.
