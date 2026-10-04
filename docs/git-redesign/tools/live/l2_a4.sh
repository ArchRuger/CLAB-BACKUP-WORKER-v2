#!/bin/bash
# A4: github.com made unreachable by a temporary /etc/hosts line, always removed again (trap).
PY=/home/archtop/pw-venv/bin/python
cd "$(dirname "$0")/../../../.." || exit 1
MARK='# l2-a4-block'
before=$(sudo md5sum /etc/hosts | cut -d' ' -f1)
cleanup() { sudo sed -i "/${MARK}/d" /etc/hosts; echo "hosts restored: $( [ "$(sudo md5sum /etc/hosts | cut -d' ' -f1)" = "$before" ] && echo identical-to-before || echo DIFFERENT )"; }
trap cleanup EXIT INT TERM
echo "hosts md5 before: $before"
$PY -u docs/git-redesign/tools/live/l2_a4.py "$1" "$2" "$MARK"
