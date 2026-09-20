# Grafana lab map

A weathermap of every lab in Grafana, in the style of
[srl-labs/srl-telemetry-lab](https://github.com/srl-labs/srl-telemetry-lab): the topology
drawn as a diagram, links coloured and animated by traffic, port dots red or green with
the operational state, a status dot per node, and the rate written on every link end.
The difference from the srl lab: nothing is drawn by hand. The manager generates the
diagram and the panel configuration from the drawing its own map already uses and keeps
one dashboard per lab up to date. This page says what you get, what a new lab needs, and
what is left for you to craft.

## What it looks like

The Grafana folder **Lab maps** holds one dashboard per lab, `Lab map · <lab name>`, with
a single **Flow panel**:

| On the map | Driven by | Meaning |
|---|---|---|
| Link half, from a node to the middle of the link | the receive rate of the far end (`clab_interface_receive_bits_per_second`) | Grey below 10 kbit/s, green, yellow from 500 kbit/s, orange from 1 Mbit/s, red from 5 Mbit/s. Dashes move away from the node as soon as it sends more than 2 kbit/s, faster with more traffic (2.5 s per cycle at 10 kbit/s, 0.3 s at 5 Mbit/s). |
| `↑ 111.2 kb/s` next to a link end | the same series | What that node sends on that port, measured where it arrives. |
| Port dot at the node edge | `clab_interface_oper_up` | Green up, red down, grey while no telemetry arrived. |
| Node status dot (top right of the icon) | `clab_telemetry_node_state_code` | Green streaming, orange stale, blue waiting or connecting, red failed, grey off or unsupported. |
| Interface labels, node labels, groups and notes | the drawing | Exactly what the manager's map shows. |

Why the far end's receive counter: cEOS in a container reports no transmit octets on
its data ports, and every NOS counts what arrives; the far end's `in` is the truthful
"what I sent" for any kind. The dashboard also links to the three fixed dashboards (*Lab
overview*, *Interfaces*, *BGP neighbours*) filtered to the lab.

## Nothing to set up

The map needs the Flow panel plugin (`andrewbmchugh-flow-panel` 1.20.1, Apache-2.0,
community-signed). The Grafana stack is part of every installation, and its setup
installs the plugin once, pinned, with the pinned Grafana image's own CLI into
`TELEMETRY_CONFIG_DIR/plugins` and mounts that folder read-only, so later restarts need
no internet. It also creates the folder the manager writes the maps into
(`TELEMETRY_MAPS_DIR`, default `/srv/containerlab-node-manager/data/telemetry/dashboards`,
owned by the manager's user) and mounts it read-only into Grafana. To reinstall or
repair the stack from any directory:

```bash
sudo bash "$HOME/projects/clab-manager/deploy/setup-telemetry.sh"
```

Its final lines tell you whether Prometheus, Grafana and the Flow panel are ready;
`bash "$HOME/projects/clab-manager/deploy/check-install.sh"` repeats that check
(*Grafana telemetry dashboards* warns when the plugin is missing or the folder is not
writable). Access to grafana.com is needed during the plugin installation only; the
manager and the lab need none.

## What a new lab gets by itself

For a lab you deploy or import through the manager with a drawing (the topology YAML
plus, optionally, its `.annotations.json` from the VS Code extension) and automatic
telemetry on (the default for labs created since 1.23.0), the sequence is:

1. The manager renders the SVG and the panel configuration from the drawing within
   five seconds of the lab being saved and writes `clab-map-<lab id>.json` into the maps
   folder. Nothing on a device is touched for the map; the telemetry feature itself
   provisions gNMI as described in [TELEMETRY.md](TELEMETRY.md).
2. Grafana picks the file up within 30 seconds: the dashboard appears in the **Lab
   maps** folder as `Lab map · <name>`.
3. The **Telemetry** card on the lab's **Tools** tab reads **Open lab map ↗** and opens it; Grafana runs
   only while someone reads it, so the button first starts it on the VM when it is
   stopped (a few seconds) and then shows the map. Node and link colours follow the
   nodes as they reach *Streaming*; rates appear after the first two counter samples
   (about 20 seconds).
4. Rename the lab, redraw it (*Edit map*, or re-import the annotations) or add nodes,
   and the map follows on the next pass. Remove the lab from the manager and its map
   disappears from Grafana within 30 seconds.

What the map needs from the lab, and what happens when it is missing:

| Requirement | Without it |
|---|---|
| A drawing (imported topology; positions come from the annotations file or the manager's default grid) | No map for that lab; the button reads **Open network dashboard ↗** and opens the lab overview instead. Import the topology once. |
| Drawing node names that match the inventory (containerlab node names, short names or `clab-<lab>-<node>`) | Unmatched nodes and their links are drawn static grey, without dots or rates. The manager's own map marks them *Not in this lab* too. |
| A supported kind on the node (cEOS, XRv9k, cJunosEvolved) with telemetry streaming | The node dot stays grey, its ports and links grey and still. |
| Interface names in the drawing in containerlab form (`eth1`) or the NOS form (`Ethernet1`, `Gi0/0/0/0`, `et-0/0/0`) | The manager maps them per kind; an unknown form is used verbatim and simply matches nothing, so that link stays grey. |
| The Flow panel loaded in Grafana | The dashboard exists but the panel says the plugin is missing. Rerun the setup. |

## What you still craft per lab

For the map itself: nothing. The things you may want to shape are the same inputs the
manager's own map uses, so they are done once and serve both views:

- **Layout and looks.** Positions, icons (router, switch, server), icon colours, label
  positions, groups and text notes come from the drawing. Edit them in the manager
  (*Edit map*) or maintain the containerlab `.annotations.json` next to the topology
  and re-import; the Grafana map is regenerated from the result.
- **Names.** The node label on the map is the drawing label; the series names behind
  the scenes use the inventory short name (`ceos1`) and the NOS interface name
  (`Ethernet1`), which is also what the *Interfaces* dashboard and the metrics endpoint
  use.
- **Nothing in Grafana.** The dashboards are provisioned read-only; edits made in the
  Grafana UI are not saved, which is what keeps the generated file authoritative.

The colour thresholds and the animation speeds are the same for every lab
(`TRAFFIC_LEVELS` and `FLOW` in `clab-backup-ui/app/telemetry_map.py`); they are tuned
for virtual labs where a ping flood is tens of kilobits per second, not for a
production core.

## Making your own variant

If you want a map beyond what the generator draws (a rack view, a different symbol
set, extra text), start from the generated files rather than from a blank page:

- `http://VM_IP:8081/api/labs/<lab id>/telemetry/map.svg` is the SVG (plain SVG, opens
  in draw.io, Inkscape or a text editor);
- `.../telemetry/map.yml` is the Flow panel configuration (JSON, which the panel reads
  as YAML) binding cell ids such as `link:ceos1:eth1` to series such as
  `ceos2:Ethernet1:in`;
- `.../telemetry/map.json` is the whole dashboard.

Keep the element ids (`cell-link:<node>:<interface>`, `cell-rate:…`, `cell-port:…`,
`cell-node:<node>`) on whatever shapes you draw, keep the dash animation on the link
paths, and paste your SVG and configuration into a copy of the dashboard as the Grafana
`admin` (the password is `TELEMETRY_GRAFANA_ADMIN_PASSWORD` in `clab-backup-ui/.env`).
That is the srl-telemetry-lab workflow (`clab-io-draw`, draw.io *Export as SVG*, a
YAML per lab) applied to the manager's metrics; the Flow panel's reference for cell
options is in its repository (`yaml_defs/panelConfig.yaml`). Such a copy is yours to
maintain; the generated dashboard keeps following the lab.

## Troubleshooting

| Symptom | Check |
|---|---|
| No *Lab maps* folder in Grafana | `bash "$HOME/projects/clab-manager/deploy/check-install.sh"` → *Grafana telemetry dashboards*. The telemetry setup must have run from this release's source (it adds the two mounts); the installer and the launcher run it. |
| The map dashboard is missing for one lab | `/api/labs/<id>/telemetry` → `grafana.map_uid` is empty when the lab has no drawing. `/api/telemetry/health` → `maps.error` names a folder problem. |
| Panel shows a plugin error or an empty frame | The Flow panel is not loaded: rerun the setup command above with access to grafana.com and look at `sudo docker compose --env-file "$HOME/projects/clab-manager/clab-backup-ui/.env" -f "$HOME/projects/clab-manager/deploy/compose.telemetry.yml" logs --tail=40 grafana`. |
| Links stay grey while the Interfaces dashboard shows rates | The interface name in the drawing does not resolve to the NOS name (see the table above), or the node is unmatched. |
| Rates are 0 on one direction only | A cEOS container reports zero transmit counters; the far end's receive rate is what the map shows, so both ends carry the traffic they receive. |

The generated files carry names, positions and colours only: no addresses, logins or
device configuration. The dashboards are readable by anyone who reaches Grafana's port,
like the rest of the stack.
