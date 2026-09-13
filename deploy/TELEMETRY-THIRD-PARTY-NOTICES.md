# Third-party components of the telemetry feature

The manager's telemetry collector and the optional dashboards use the following
components. None of them is modified; the images are pulled by digest and the Python
packages are installed from PyPI during the image build.

| Component | Use | Licence |
|---|---|---|
| [pygnmi](https://github.com/akarneliuk/pygnmi) | gNMI client in the manager (dial-in subscriptions) | BSD-3-Clause |
| [grpcio](https://github.com/grpc/grpc) | gRPC transport for pygnmi | Apache-2.0 |
| [protobuf](https://github.com/protocolbuffers/protobuf) | gNMI message encoding | BSD-3-Clause |
| [dictdiffer](https://github.com/inveniosoftware/dictdiffer) | pygnmi dependency | MIT |
| [Prometheus](https://prometheus.io) (`prom/prometheus`) | Scrapes the manager's `/api/telemetry/metrics` every 10 s, two-hour retention on tmpfs | Apache-2.0 |
| [Grafana OSS](https://grafana.com/oss/grafana/) (`grafana/grafana-oss`) | Serves the provisioned dashboards in a separate browser tab | AGPL-3.0 |
| [Flow panel](https://github.com/andymchugh/andrewbmchugh-flow-panel) (`andrewbmchugh-flow-panel` 1.20.1, community-signed) | Renders the generated lab maps (SVG plus panel configuration) in Grafana; installed once by `setup-telemetry.sh` from the Grafana plugin catalog into `TELEMETRY_CONFIG_DIR/plugins` | Apache-2.0 |

Grafana and Prometheus run as separate containers from `deploy/compose.telemetry.yml`
with host networking, no Docker socket, dropped capabilities and tmpfs-backed data.
The dashboards under `deploy/telemetry/grafana/dashboards/` are original to this
repository (MIT, like the rest of the project).
