#!/usr/bin/env bash
# The browser regression that must keep passing under sign-on (sign-on REVIEW R15, BUILD.md S11).
#
#     docs/sign-on/tools/run_regression.sh <port>
#
# Starts docs/redesign/tools/fixture_manager.py on <port> with a fresh FIXTURE_DATA (mktemp -d), waits for it, runs
#   docs/redesign/tools/verify_after.py          (three viewports, every screen and dialog)
#   docs/lab-builder/tools/student_workflow.py   (the lab builder, deploy and save as a student does it)
# against it, stops the fixture and removes its data. The fixture signs every request in as its admin (the default), so
# neither check knows about sign-on: that they still pass IS the check. Exit status 0 only when both pass.
#
# Python with Playwright: $CLAB_PYTHON, else clab-backup-ui/.venv/bin/python of this checkout, else of the main checkout
# this worktree belongs to. Chromium comes from PLAYWRIGHT_BROWSERS_PATH (never 'playwright install' here).
set -u

port="${1:-}"
case "$port" in
    ''|*[!0-9]*) echo "usage: $0 <port>" >&2; exit 2 ;;
esac

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../../.." && pwd)"

python="${CLAB_PYTHON:-}"
if [ -z "$python" ]; then
    python="$root/clab-backup-ui/.venv/bin/python"
    if [ ! -x "$python" ]; then
        common="$(git -C "$root" rev-parse --git-common-dir 2>/dev/null || true)"
        if [ -n "$common" ]; then
            main="$(cd "$root" && cd "$common/.." && pwd)"
            [ -x "$main/clab-backup-ui/.venv/bin/python" ] && python="$main/clab-backup-ui/.venv/bin/python"
        fi
    fi
fi
if [ ! -x "$python" ]; then
    echo "run_regression: no Python with the application's packages. Create clab-backup-ui/.venv or set CLAB_PYTHON." >&2
    exit 2
fi

data="$(mktemp -d)"
work="$(mktemp -d)"
log="$work/fixture.log"
pid=""

cleanup() {
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null
        for _ in 1 2 3 4 5 6 7 8 9 10; do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
        kill -9 "$pid" 2>/dev/null
    fi
    rm -rf "$data" "$work"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

FIXTURE_DATA="$data" "$python" "$root/docs/redesign/tools/fixture_manager.py" --port "$port" >"$log" 2>&1 &
pid=$!

base="http://127.0.0.1:$port"
ready=0
for _ in $(seq 1 240); do
    if ! kill -0 "$pid" 2>/dev/null; then break; fi
    if "$python" - "$base" <<'PY' 2>/dev/null
import sys, urllib.request
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
sys.exit(0 if opener.open(sys.argv[1] + '/api/health', timeout=2).status == 200 else 1)
PY
    then ready=1; break; fi
    sleep 0.5
done
if [ "$ready" != 1 ]; then
    echo "run_regression: the fixture did not come up on $base. Its log (credential lines left out):" >&2
    grep -vi 'password' "$log" | tail -40 >&2
    exit 1
fi
echo "run_regression: fixture up on $base (fresh data, signed in as its admin)"

mkdir -p "$work/shots" "$work/student"
status=0

echo "== verify_after.py"
CLAB_BASE="$base" CLAB_SHOTS="$work/shots" "$python" "$root/docs/redesign/tools/verify_after.py"
verify=$?
echo "== student_workflow.py"
"$python" "$root/docs/lab-builder/tools/student_workflow.py" --base "$base" --out "$work/student"
student=$?

[ "$verify" -eq 0 ] || status=1
[ "$student" -eq 0 ] || status=1
echo "run_regression: verify_after exit $verify, student_workflow exit $student"
if [ "$status" -ne 0 ]; then
    echo "run_regression: FAILED" >&2
    exit 1
fi
echo "run_regression: both checks passed"
exit 0
