#!/usr/bin/env bash
# Return the development VM to the documented starting state of Scenario A (authoring and QA use only).
#
#   bash docs/student-quick-start/tools/reset_scenario_a.sh <student-repo-name>
#
# Leaves: My labs without link-basics, no link-basics containers, the instructor package unchanged under
# /srv/containerlab-node-manager/projects/link-basics/, the VM Git registry empty (a backup is kept next to it),
# and a fresh private copy github.com/pruger-dev/<student-repo-name> made from the pruger-dev/netlab-course
# template (or the existing one, if it already exists), with no ~/labs/<student-repo-name> checkout left behind.
# Needs: the manager on http://127.0.0.1:8081, passwordless sudo, gh logged in as pruger-dev.
set -euo pipefail
student=${1:?student repository name, e.g. netlab-course-student}
manager=http://127.0.0.1:8081
topology=/srv/containerlab-node-manager/projects/link-basics/link-basics.clab.yml
lab_id=$(curl -s "$manager/api/state" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(next((l["id"] for l in d["labs"] if l["name"]=="link-basics"), ""))')
if [[ -n "$lab_id" ]]; then
  pending=$(curl -s "$manager/api/state" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(sum(1 for j in d.get("git_jobs",[]) if j.get("status") in ("queued","capturing","exporting","pushing","review_pending","committed")))')
  [[ "$pending" == 0 ]] || { echo "link-basics has $pending pending save(s); finish or dismiss them under Progress > Recent saves first." >&2; exit 1; }
  curl -s -X DELETE -H 'Content-Type: application/json' -d '{"name":"link-basics","prevent_reimport":false}' "$manager/api/labs/$lab_id" >/dev/null && echo "removed link-basics from the manager"
fi
if docker ps -a --format '{{.Names}}' | grep -q '^clab-link-basics-'; then
  sudo containerlab destroy -t "$topology" --cleanup >/dev/null 2>&1 && echo "destroyed the link-basics containers"
fi
sudo rm -rf /srv/containerlab-node-manager/projects/link-basics/clab-link-basics
if [[ "$(sudo cat /etc/clab-manager/git.json)" != '{"repositories": []}' ]]; then
  sudo cp -p /etc/clab-manager/git.json "/etc/clab-manager/git.json.reset-$(date +%Y%m%d-%H%M%S)"
  echo '{"repositories": []}' | sudo tee /etc/clab-manager/git.json >/dev/null; sudo chmod 600 /etc/clab-manager/git.json
  echo "emptied the VM Git registry (backup kept in /etc/clab-manager/)"
fi
rm -rf "$HOME/labs/$student"
if ! gh repo view "pruger-dev/$student" >/dev/null 2>&1; then
  gh repo create "pruger-dev/$student" --private --template pruger-dev/netlab-course --description "A student's own copy of netlab-course" >/dev/null
  echo "created github.com/pruger-dev/$student from the template"
  sleep 8
fi
echo "student repository: https://github.com/pruger-dev/$student.git"
gh api "repos/pruger-dev/$student/git/trees/main?recursive=1" -q '.tree[] | select(.type=="blob") | .path' | sed 's/^/  /'
curl -s "$manager/api/state" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("labs in the manager:", [l["name"] for l in d["labs"]])'
