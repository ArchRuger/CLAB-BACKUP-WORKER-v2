# Optional capture deployment attribution

`compose.capture.yml` adapts the service configuration from
[Siemens Edgeshark](https://github.com/siemens/edgeshark/blob/main/deployments/wget/docker-compose-localhost.yaml).
Changes include image digest pins, an isolated Compose project, local service DNS,
configurable localhost port binding, and removal of debug logging and icon data.
The upstream license follows. Upstream images and the separately installed desktop
plugin retain their own licenses and notices; they are not bundled in this source.

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
