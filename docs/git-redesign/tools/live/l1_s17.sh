#!/bin/bash
# L1 step 17: the course scaffold tool against the new backend, on lab git-redesign-b. Output and exit statuses are recorded as they happen.
PY=/home/archtop/projects/clab-manager/clab-backup-ui/.venv/bin/python
cd "$(dirname "$0")/../../../.." || exit 1
S=deploy/scaffold-lab.py
run() { echo "\$ $*"; script -qec "$*" /dev/null < "$INPUT" | tr -d '\r'; echo "exit status ${PIPESTATUS[0]}"; }
state() { $PY -u docs/git-redesign/tools/live/l1_s17_state.py "$1"; }
state "before"
echo; echo "### init l1-scaffold"; INPUT=/dev/null; run python3 $S --lab git-redesign-b init l1-scaffold
state "after init"
echo; echo "### device change, then snapshot start answering no"
$PY -u -c "import sys; sys.path.insert(0,'docs/git-redesign/tools/live'); from l1lib import *; print(set_description('b-ceos1','l1-s17-start'))"
printf 'n\n' > /tmp/l1_no; INPUT=/tmp/l1_no; run python3 $S --lab git-redesign-b snapshot l1-scaffold start
state "after snapshot start (answered no)"
echo; echo "### device change, then snapshot solution --yes"
$PY -u -c "import sys; sys.path.insert(0,'docs/git-redesign/tools/live'); from l1lib import *; print(set_description('b-ceos1','l1-s17-solution'))"
INPUT=/dev/null; run python3 $S --lab git-redesign-b snapshot l1-scaffold solution --yes
state "after snapshot solution --yes"
echo finished
