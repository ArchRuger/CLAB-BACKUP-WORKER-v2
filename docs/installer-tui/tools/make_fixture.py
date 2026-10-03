"""FIXTURE ONLY: build a disposable copy of this checkout whose mutating helpers are fakes.

    python3 docs/installer-tui/tools/make_fixture.py /home/me/scratch/clab-fixture

The copy keeps the real installer (install.sh, install-manager.py, installer_tui/, the
read-only checks) and replaces only the helpers that would change the VM with small
scripts driven by <copy>/fixture-control.json, for example

    {"prereqs": ["lock", "ok"], "launch": ["sleep:20"], "capture": ["flood:200000", "ok"],
     "engineer": ["fail"], "git": ["prompt"]}

Each list is consumed one entry per attempt (the last entry repeats): ok, fail,
lock (prints the dpkg lock signature, exit 100), auth (prints sudo's password-required
line), sleep:N (N seconds of progress lines), flood:N (N lines as fast as possible),
prompt (reads stdin; with no terminal it fails). The fakes run under the real sudo, in
the real terminal or pipe the installer gives them, so terminal handoff, process groups,
the installer lock and recovery are exercised for real while nothing is installed.
Evidence produced with it is fixture evidence and must be labelled so.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
FAKES = {
    'prereqs': 'deploy/install-prerequisites.sh',
    'launch': 'deploy/start-manager.sh',
    'capture': 'deploy/setup-capture.sh',
    'engineer': 'deploy/setup-engineer-access.sh',
    'git': 'deploy/setup-git.sh',
}
FAKE = r'''#!/usr/bin/env bash
# FIXTURE helper standing in for {path} (step "{key}"). Changes nothing on the VM.
set -u
here=$(cd -- "$(dirname -- "${{BASH_SOURCE[0]}}")/.." && pwd)
state="$here/fixture-state"; mkdir -p "$state" 2>/dev/null; chmod 0777 "$state" 2>/dev/null || true
count_file="$state/{key}.count"; n=$(cat "$count_file" 2>/dev/null || echo 0); n=$((n + 1)); echo "$n" > "$count_file"
action=$(/usr/bin/python3 -c 'import json,sys; c=json.load(open(sys.argv[1])).get(sys.argv[2], ["ok"]); i=int(sys.argv[3])-1; print(c[min(i, len(c)-1)])' "$here/fixture-control.json" {key} "$n" 2>/dev/null || echo ok)
echo "[fixture {key}] attempt $n: $action (args: $*)"
case "$action" in
  ok) echo "[fixture {key}] done"; exit 0;;
  fail) echo "[fixture {key}] simulated failure: the download was interrupted" >&2; exit 3;;
  lock) echo "E: Could not get lock /var/lib/dpkg/lock-frontend. It is held by process 2230 (unattended-upgr)"; exit 100;;
  auth) echo "sudo: a password is required" >&2; exit 1;;
  sleep:*) s=${{action#sleep:}}; for ((i=1; i<=s; i++)); do echo "[fixture {key}] working $i/$s"; sleep 1; done; exit 0;;
  flood:*) c=${{action#flood:}}; /usr/bin/python3 -c 'import sys
for i in range(int(sys.argv[1])): print(f"[fixture flood] line {{i}} \x1b[31mred\x1b[0m [bold]markup[/bold] \x1b]0;title\x07")' "$c"; exit 0;;
  prompt) read -r -p "[fixture {key}] type y and Enter to succeed: " answer || {{ echo; echo "[fixture {key}] no terminal input"; exit 2; }}
          [[ $answer == y ]] && {{ echo "[fixture {key}] confirmed"; exit 0; }}; echo "[fixture {key}] cancelled"; exit 2;;
  *) echo "[fixture {key}] unknown action $action"; exit 64;;
esac
'''


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    target = Path(sys.argv[1]).expanduser().resolve()
    if ROOT in target.parents or target == ROOT:
        sys.exit('Choose a folder outside the checkout.')
    if target.exists():
        shutil.rmtree(target)
    files = subprocess.run(['git', 'ls-files', '-co', '--exclude-standard'], cwd=ROOT, check=True,
                           stdout=subprocess.PIPE, text=True).stdout.splitlines()
    for name in files:
        source = ROOT / name
        if not source.is_file() or name.startswith('.claude/'):
            continue
        destination = target / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    for key, path in FAKES.items():
        (target / path).write_text(FAKE.format(key=key, path=path))
        os.chmod(target / path, 0o755)
    (target / 'fixture-control.json').write_text(json.dumps({key: ['ok'] for key in FAKES}, indent=1) + '\n')
    state = target / 'fixture-state'
    state.mkdir(exist_ok=True)
    os.chmod(state, 0o777)
    (target / 'FIXTURE-CHECKOUT.txt').write_text('Disposable fixture copy with fake helpers; see docs/installer-tui/tools/make_fixture.py.\n')
    print(target)


if __name__ == '__main__':
    main()
