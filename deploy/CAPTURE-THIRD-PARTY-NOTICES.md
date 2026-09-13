# Optional capture deployment attribution

`compose.capture.yml` adapts the service configuration from
[Siemens Edgeshark](https://github.com/siemens/edgeshark/blob/main/deployments/wget/docker-compose-localhost.yaml).
Changes include image digest pins, an isolated Compose project, local service DNS,
configurable localhost port binding, and removal of debug logging and icon data.
The upstream license follows. Upstream container images retain their own licenses
and notices; they are pulled separately, not bundled in this source checkout.

Browser sessions use the pinned [SR Labs Wireshark container](https://github.com/srl-labs/wireshark-vnc-docker),
which includes [Wireshark](https://www.wireshark.org/),
[Siemens cshargextcap](https://github.com/siemens/cshargextcap) and
[noVNC](https://github.com/novnc/noVNC) on the
[jlesage GUI base image](https://github.com/jlesage/docker-baseimage-gui).
The manager loads noVNC modules from that image at runtime with their upstream
notices intact. The session service and viewer here are original integration
code, not a copy of the VS Code extension. Consult the upstream projects and
image contents for their component licenses before redistributing images.

MIT License

Copyright (c) Siemens AG 2023

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the “Software”), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
