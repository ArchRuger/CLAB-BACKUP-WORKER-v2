#!/bin/bash
# L1 step 10: make github.com unreachable for the upload with a temporary /etc/hosts line, always removed again (trap).
PY=/home/archtop/projects/clab-manager/clab-backup-ui/.venv/bin/python
cd "$(dirname "$0")/../../../.." || exit 1
MARK='# l1-s10-block'
before=$(sudo md5sum /etc/hosts | cut -d' ' -f1)
cleanup() { sudo sed -i "/${MARK}/d" /etc/hosts; echo "hosts restored: $( [ "$(sudo md5sum /etc/hosts | cut -d' ' -f1)" = "$before" ] && echo identical-to-before || echo DIFFERENT )"; }
trap cleanup EXIT INT TERM
echo "hosts md5 before: $before"
$PY -u docs/git-redesign/tools/live/l1_s10.py "$MARK" "$@"
