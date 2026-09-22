#!/usr/bin/env bash
# Return the development VM to the documented starting state of Scenario B (authoring and QA use only).
#
#   bash docs/student-quick-start/tools/reset_scenario_b.sh <student-repo-name>
#
# Leaves: no my-first-lab in the manager, no my-first-lab containers, no my-first-lab folder and no clone of the
# student's repository under the trusted lab root (earlier ones are moved to projects-archive-2026-09-22/), and no
# ~/labs/<student-repo-name> checkout. The GitHub repository itself is NOT created or deleted here: the student creates
# it in step B5 (gh cannot delete repositories with this login, so use a name that does not exist yet).
set -euo pipefail
student=${1:?student repository name, e.g. my-network-labs}
manager=http://127.0.0.1:8081
root=/srv/containerlab-node-manager/projects
archive=/srv/containerlab-node-manager/projects-archive-2026-09-22
lab_id=$(curl -s "$manager/api/state" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(next((l["id"] for l in d["labs"] if l["name"]=="my-first-lab"), ""))')
if [[ -n "$lab_id" ]]; then
  pending=$(curl -s "$manager/api/state" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(sum(1 for j in d.get("git_jobs",[]) if j.get("lab_id")==sys.argv[1] and j.get("status") in ("queued","capturing","exporting","pushing","review_pending","committed")))' "$lab_id")
  [[ "$pending" == 0 ]] || { echo "my-first-lab has $pending pending save(s); finish or dismiss them first." >&2; exit 1; }
  curl -s -X DELETE -H 'Content-Type: application/json' -d '{"name":"my-first-lab","prevent_reimport":false}' "$manager/api/labs/$lab_id" >/dev/null && echo "removed my-first-lab from the manager"
fi
if docker ps -a --format '{{.Names}}' | grep -q '^clab-my-first-lab-'; then
  for t in "$root"/my-first-lab/my-first-lab.clab.yml "$root"/*/my-first-lab/my-first-lab.clab.yml; do
    [[ -f "$t" ]] && sudo containerlab destroy -t "$t" --cleanup >/dev/null 2>&1 && echo "destroyed the my-first-lab containers ($t)" && break
  done
  docker ps -a --format '{{.Names}}' | { grep '^clab-my-first-lab-' || true; } | xargs -r docker rm -f >/dev/null
fi
sudo install -d -o root -g clab_admins -m 2775 "$archive"
stamp=$(date +%Y%m%d-%H%M%S)
for d in "$root"/my-first-lab "$root"/"$student" "$root"/my-network-labs*; do
  [[ -d "$d" ]] && sudo mv "$d" "$archive/$(basename "$d").$stamp" && echo "moved $d to the archive"
done
rm -rf "$HOME/labs/$student"
# A renamed repository still answers under its old name (GitHub redirect), so compare the name it reports.
if [[ "$(gh api "repos/pruger-dev/$student" -q .name 2>/dev/null || true)" == "$student" ]]; then
  echo "NOTE: github.com/pruger-dev/$student already exists; step B5 will find it existing"
else
  echo "github.com/pruger-dev/$student does not exist yet (step B5 creates it)"
fi
curl -s "$manager/api/state" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("labs in the manager:", [l["name"] for l in d["labs"]])'
ls "$root"
