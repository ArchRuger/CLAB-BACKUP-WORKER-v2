#!/usr/bin/env bash
# Pass 6: runs one chain of the charter's step-3 fixture tools sequentially, logging UTC times and exit codes.
# Usage: run_fixture_chain.sh A|B   (A: design_ui, poll_retry, stress race+bulk; B: coverage_run, design_probes)
set -u
ROOT=/home/clabllm/projects/clab-manager-1.30.42
P=$ROOT/docs/netlab-ui-qa/acceptance/pass-6
PY=$ROOT/clab-backup-ui/.venv/bin/python
export PATH="$ROOT/clab-backup-ui/.venv/bin:$PATH"
cd "$ROOT"
run() { local name=$1; shift; local s; s=$(date -u +%FT%TZ); "$@" > "$P/$name.log" 2>&1; local rc=$?; echo "$name start=$s end=$(date -u +%FT%TZ) exit=$rc" >> "$P/fixture-times.txt"; }
case "$1" in
A)
  SH=$(mktemp -d); run check_design_ui $PY docs/netlab-integration/tools/check_design_ui.py --port 8170 --shots "$SH" --report "$P/check_design_ui-report.md"
  run check_design_poll_retry $PY docs/netlab-ui-qa/tools/check_design_poll_retry.py --port 8171 --out "$P"
  run stress_race $PY docs/netlab-ui-qa/tools/stress_design.py race --port 8172
  run stress_bulk $PY docs/netlab-ui-qa/tools/stress_design.py bulk --port 8172
  mkdir -p "$P/stress"; cp docs/netlab-ui-qa/evidence/stress/*-results.json "$P/stress/" 2>/dev/null
  git checkout -- docs/netlab-ui-qa/evidence/stress; git status --short docs/netlab-ui-qa/evidence/stress > "$P/stress-restore-status.txt"; git clean -n docs/netlab-ui-qa/evidence/stress >> "$P/stress-restore-status.txt"
  ;;
B)
  if ! git diff --quiet -- docs/netlab-ui-qa/coverage.json docs/netlab-ui-qa/COVERAGE.md; then echo "coverage files already modified by someone else: refusing to run coverage_run" >> "$P/fixture-times.txt"; exit 2; fi
  D=$(mktemp -d); run coverage_run $PY docs/netlab-ui-qa/tools/coverage_run.py --port 8173 --data "$D"
  cp docs/netlab-ui-qa/evidence/coverage/results.json "$P/coverage-results.json"
  git diff --stat docs/netlab-ui-qa/coverage.json docs/netlab-ui-qa/COVERAGE.md > "$P/coverage-diffstat.txt"
  git show HEAD:docs/netlab-ui-qa/coverage.json > "$P/committed-coverage.json"
  git checkout -- docs/netlab-ui-qa/evidence/coverage docs/netlab-ui-qa/coverage.json docs/netlab-ui-qa/COVERAGE.md
  git status --short docs/netlab-ui-qa/evidence/coverage docs/netlab-ui-qa/coverage.json docs/netlab-ui-qa/COVERAGE.md > "$P/coverage-restore-status.txt"; git clean -n docs/netlab-ui-qa/evidence/coverage >> "$P/coverage-restore-status.txt"
  D2=$(mktemp -d); run design_probes $PY docs/netlab-ui-qa/tools/probes/design_probes.py --port 8174 --data "$D2"
  git checkout -- docs/netlab-ui-qa/evidence/probes; git status --short docs/netlab-ui-qa/evidence/probes > "$P/probes-restore-status.txt"; git clean -n docs/netlab-ui-qa/evidence/probes >> "$P/probes-restore-status.txt"
  ;;
esac
echo "chain $1 done $(date -u +%FT%TZ)" >> "$P/fixture-times.txt"
