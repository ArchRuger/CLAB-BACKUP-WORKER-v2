# Network telemetry (retired)

Automatic network telemetry (gNMI collection, the manager's own device provisioning of the gNMI
service, the in-memory session store and the Prometheus metrics endpoint `/api/telemetry/metrics`)
and the Grafana dashboards with the generated lab maps are removed from the manager, as of 1.30.39.
The Tools › Telemetry card, *Telemetry settings…*, `/static/grafana.html`, and the health check's
"Network telemetry" and "Grafana telemetry dashboards" rows are gone with it. Browser Wireshark,
readiness, terminals, backups, *Save progress* and *Apply to running lab* are unaffected.

Upgrading an installation that had the stack runs `deploy/retire-telemetry.sh --no-recreate`
before the manager is rebuilt (`start-manager.sh`, and therefore `install.sh`, calls it
automatically). It finds only the containers and the two tmpfs-backed volumes labelled with the
old Compose project `clab-manager-telemetry`, stops and removes them, removes the pinned images
when nothing else uses them, moves the feature's files (`/srv/containerlab-node-manager/telemetry`
and the generated lab-map dashboards under `/srv/containerlab-node-manager/data/telemetry`) into a
timestamped `telemetry-retired-<UTC stamp>/` archive the operator may delete (`--purge` deletes
instead), and removes every `TELEMETRY_*` line from `clab-backup-ui/.env`. It is idempotent and
does nothing on a VM that never had the stack. The health check's new "Retired telemetry stack"
row PASSes once no labelled container or volume, no `TELEMETRY_*` key and neither feature folder
remains.

Where the retired feature had added configuration lines to a device (Arista cEOS, Cisco XRv9k,
Juniper cJunosEvolved), the manager keeps that record: the lab shows the notice "Configuration
lines added by the retired telemetry feature are still on: `<device names>`." with a **Review and
remove…** button opening **Retired telemetry configuration** (also under Lab actions ▾ › Advanced
options › **Retired telemetry configuration…** while the record exists). **Remove from devices**
deletes exactly the recorded lines on the running device, inside the device's own configuration
session, and reads it back, reporting `removed`, `absent`, `failed` or `skipped` per device. It never
removes a line the manager did not add; it removes a whole service (`management api gnmi`, `grpc`,
`extension-service request-response grpc`) only when the record shows the manager created it and
it holds nothing else; a service that now also carries settings the manager did not add is left
untouched and reported `failed`; a lab redeployed after the lines were recorded boots from its own
files, so its record is cleared without touching the device. An entry the manager can never act on
(device gone from the lab, unsupported or changed kind, redeployed lab) or an unreadable record can be
dropped with **Forget** in the same dialog. Removing the lab from the manager or *Start fresh* drops the
record with the lab. A downgrade to a release before 1.30.39 would show the record in its lab view:
restore the pre-upgrade data copy first if a downgrade is needed.

The original design — collection, provisioning, the session store, the Prometheus exposition and
the generated lab maps — is recorded in [docs/CHANGELOG.md](CHANGELOG.md) (since 1.23.0, as of 1.26.0)
and the per-release handoff notes in `agent instructions.md`.
