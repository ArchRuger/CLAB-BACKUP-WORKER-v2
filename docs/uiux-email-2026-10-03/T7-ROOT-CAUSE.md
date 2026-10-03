# Task 7 — cJunosEvolved keeps the placeholder hostname `HOSTNAME`

## Symptom

First CLI session on topology node `ptx1` (kind `juniper_cjunosevolved`, image
`n24l/cjunosevolved:26.2R1.7-EVO`, saved by the Lab builder with only `kind` and `image`) shows
`admin@HOSTNAME>`; the vJunos-switch, XRv9k and cEOS nodes in the same lab show their topology names.

## Root cause

1. **Containerlab passes no hostname to this kind.** In containerlab 0.79.0 (the version on dev1)
   `nodes/cjunosevolved/cjunosevolved.go` only binds `<labdir>/<node>/config:/config`; it sets no
   launch arguments, no environment and has no built-in startup template. Without a `startup-config`
   the `/config` directory stays empty (observed on dev1: empty `clab-t7repro/ptx1/config`). By
   contrast vJunos-switch and XRv9k receive `--hostname <node>` as launch arguments (vrnetlab), and
   cEOS gets `hostname {{ .ShortName }}` from containerlab's built-in template.
2. **Juniper's entrypoint fills in the host name only on its auto-config path.** The image's
   `/entrypoint.sh` (vanilla Juniper; the n24l image is an unchanged re-push) builds the boot
   configuration from `/home/evo/juniper.conf`, which starts with `host-name HOSTNAME;`. Its default
   branch (no `CPTX_AUTO_CONFIG`, no `/config/startup-config.cfg`) replaces only the management
   address token `FXP0ADDR`. Only the `CPTX_AUTO_CONFIG` branch also replaces `HOSTNAME` with the
   container's `$HOSTNAME`, which Docker sets from the containerlab node name (or the node's
   `hostname:` field). The rest of the configuration (management, SSH, the `admin` user) is the same
   on both paths. It runs on first boot only (the metadata disk is built once per container).

The manager is not involved: `publish`/`revise` write only the topology and annotations files, and
no manager module sets device host names. The network-design path protects `host-name`
(`design_provision.py` `JUNOS_PROTECTED_LEAF`) and is not used for this.

## Fix

New cJunosEvolved nodes created from the Lab builder's built-in template carry

```yaml
env:
  CPTX_AUTO_CONFIG: "1"
```

(`BUILDER_TEMPLATES` in `app/static/lab-builder-page.js`; a stored built-in template that still holds
the previous default gains it once, only when it has no `env` or `startup-config` of its own). The
setting is visible in the topology YAML and the save review, can be removed by the student, and is
never added to existing nodes, imported YAML, saved labs or a node with a `startup-config` (the
entrypoint checks `CPTX_AUTO_CONFIG` before a startup configuration, so the two must not be combined).
Nothing is applied on readiness polls, discovery, terminal opening or restart.

## Live evidence (dev1, 2026-10-03)

Deployed directly with containerlab 0.79.0, image `n24l/cjunosevolved:26.2R1.7-EVO`, read back
over SSH with the containerlab default Junos login (`show configuration system host-name`):

| Lab / node | YAML | Read back |
|---|---|---|
| `t7repro` / `ptx1` | `kind` + `image` only (as saved before the fix) | `admin@HOSTNAME>` · `host-name HOSTNAME;` |
| `t7fix` / `ptx2` | + `env: CPTX_AUTO_CONFIG: "1"` | `admin@ptx2>` · `host-name ptx2;` |
