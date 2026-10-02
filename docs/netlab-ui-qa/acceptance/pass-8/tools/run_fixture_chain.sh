#!/usr/bin/env bash
# Pass 8 fixture chains. Chain A: check_design_ui (8190), poll retry (8191), stress race + bulk (8192).
# Chain B: coverage_run (8193), design_probes (8194). Each tool gets a fresh mktemp -d data dir.
# Tracked evidence folders the tools rewrite are copied into PASS_DIR and restored with git checkout.
set -u
W=/home/clabllm/projects/clab-manager-1.30.42
P=$W/docs/netlab-ui-qa/acceptance/pass-8
PY=$W/clab-backup-ui/.venv/bin/python
export PATH="$W/clab-backup-ui/.venv/bin:$PATH"
cd "$W"
ts() { date -u +%FT%TZ; }
case "$1" in
A)
  S=$(mktemp -d); echo "check_design_ui start $(ts) shots=$S" >> $P/chain-A.times
  $PY docs/netlab-integration/tools/check_design_ui.py --port 8190 --shots "$S" --report $P/check_design_ui-report.md > $P/check_design_ui.log 2>&1
  echo "check_design_ui exit $? end $(ts)" >> $P/chain-A.times
  echo "poll_retry start $(ts)" >> $P/chain-A.times
  $PY docs/netlab-ui-qa/tools/check_design_poll_retry.py --port 8191 --out $P > $P/check_design_poll_retry.log 2>&1
  echo "poll_retry exit $? end $(ts)" >> $P/chain-A.times
  mkdir -p $P/stress
  for m in race bulk; do
    echo "stress $m start $(ts)" >> $P/chain-A.times
    $PY docs/netlab-ui-qa/tools/stress_design.py $m --port 8192 > $P/stress_$m.log 2>&1
    echo "stress $m exit $? end $(ts)" >> $P/chain-A.times
    cp docs/netlab-ui-qa/evidence/stress/$m-results.json $P/stress/ 2>>$P/chain-A.times
  done
  git checkout -- docs/netlab-ui-qa/evidence/stress
  { echo "$(ts) after git checkout -- docs/netlab-ui-qa/evidence/stress"; git status --short docs/netlab-ui-qa/evidence/stress; echo "(end of status)"; } > $P/stress-restore-status.txt
  ;;
B)
  if [ -n "$(git status --short docs/netlab-ui-qa/coverage.json docs/netlab-ui-qa/COVERAGE.md)" ]; then
    echo "coverage.json or COVERAGE.md already modified by the lead: coverage_run NOT RUN $(ts)" >> $P/chain-B.times
  else
    D=$(mktemp -d); echo "coverage start $(ts) data=$D" >> $P/chain-B.times
    $PY docs/netlab-ui-qa/tools/coverage_run.py --port 8193 --data "$D" > $P/coverage_run.log 2>&1
    echo "coverage exit $? end $(ts)" >> $P/chain-B.times
    cp docs/netlab-ui-qa/evidence/coverage/results.json $P/coverage-results.json
    git diff --stat -- docs/netlab-ui-qa/coverage.json docs/netlab-ui-qa/COVERAGE.md > $P/coverage-diffstat.txt
    git checkout -- docs/netlab-ui-qa/evidence/coverage docs/netlab-ui-qa/coverage.json docs/netlab-ui-qa/COVERAGE.md
    { echo "$(ts) after git checkout"; git status --short docs/netlab-ui-qa/evidence/coverage docs/netlab-ui-qa/coverage.json docs/netlab-ui-qa/COVERAGE.md; echo "(end of status)"; } > $P/coverage-restore-status.txt
  fi
  D=$(mktemp -d); echo "probes start $(ts) data=$D" >> $P/chain-B.times
  $PY docs/netlab-ui-qa/tools/probes/design_probes.py --port 8194 --data "$D" > $P/design_probes.log 2>&1
  echo "probes exit $? end $(ts)" >> $P/chain-B.times
  git checkout -- docs/netlab-ui-qa/evidence/probes
  { echo "$(ts) after git checkout -- docs/netlab-ui-qa/evidence/probes"; git status --short docs/netlab-ui-qa/evidence/probes; echo "(end of status)"; } > $P/probes-restore-status.txt
  ;;
esac
