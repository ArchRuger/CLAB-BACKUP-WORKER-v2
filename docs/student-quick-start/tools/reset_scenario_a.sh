#!/usr/bin/env bash
# Return the development VM to the documented starting state of Scenario A (authoring and QA use only).
#
#   bash docs/student-quick-start/tools/reset_scenario_a.sh [<student-repo-name>] [<github-account>]
#
# Leaves: link-basics removed from the manager's My labs, no link-basics containers, the instructor package
# staged under /srv/containerlab-node-manager/projects/link-basics/ (two files, no generated folder), and the
# student's private repository (default ArchRuger/campaign2-netlab-course-student, made from the public template
# pruger-dev/netlab-course) without the `link-basics/work` folder that an earlier replay saved there (removed
# with one ordinary Git commit in the manager's checkout; history is kept, nothing is forced).
# The VM Git registry is NOT touched (it belongs to the installation): a repository the manager registered
# stays registered, so a replay finds it already known. Creating the repository is done once, by hand:
#   gh repo create <account>/<repo> --private --template pruger-dev/netlab-course
# Needs: the manager on http://127.0.0.1:8081, passwordless sudo, gh logged in as the account.
set -euo pipefail
student=${1:-campaign2-netlab-course-student}
account=${2:-ArchRuger}
manager=http://127.0.0.1:8081
here=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
stage=/srv/containerlab-node-manager/projects/link-basics
topology=$stage/link-basics.clab.yml
dismiss_waiting_saves() {
  # a save that still waits for its Upload blocks "Remove from this manager": Keep snapshot only (the page's own button)
  for job in $(curl -s "$manager/api/state" | python3 -c 'import sys,json; d=json.load(sys.stdin); ids={l["id"] for l in d["labs"] if l["name"]=="link-basics"}; print(" ".join(j["id"] for j in d.get("git_jobs",[]) if j.get("lab_id") in ids and j.get("status") in ("review_pending","push_pending","export_pending","committed")))'); do
    curl -s -X POST -H 'Content-Type: application/json' -d '{"acknowledge":true}' "$manager/api/git/jobs/$job/dismiss" >/dev/null && echo "kept the waiting save $job on the VM only (Keep snapshot only)"
  done
}
lab_id=$(curl -s "$manager/api/state" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(next((l["id"] for l in d["labs"] if l["name"]=="link-basics"), ""))')
if [[ -n "$lab_id" ]]; then
  dismiss_waiting_saves
  pending=$(curl -s "$manager/api/state" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(sum(1 for j in d.get("git_jobs",[]) if j.get("lab_id")=="'"$lab_id"'" and j.get("status") in ("queued","capturing","exporting","pushing","review_pending","committed","push_pending","export_pending")))')
  [[ "$pending" == 0 ]] || { echo "link-basics has $pending pending save(s); upload or dismiss them first." >&2; exit 1; }
  curl -s -X DELETE -H 'Content-Type: application/json' -d '{"name":"link-basics","prevent_reimport":false}' "$manager/api/labs/$lab_id" >/dev/null && echo "removed link-basics from the manager"
fi
if docker ps -a --format '{{.Names}}' | grep -q '^clab-link-basics-'; then
  sudo containerlab destroy -t "$topology" --cleanup >/dev/null 2>&1 && echo "destroyed the link-basics containers"
fi
sudo rm -rf "$stage/clab-link-basics"
install -d -m 2775 -g clab_admins "$stage"
cp "$here/examples/link-basics/link-basics.clab.yml" "$here/examples/link-basics/link-basics.clab.yml.annotations.json" "$stage/"
checkout="$HOME/labs/$student"
if [[ -d "$checkout/.git" ]]; then
  (cd "$checkout"
   git fetch -q origin
   if git ls-files --error-unmatch link-basics/work >/dev/null 2>&1 || [[ -n "$(git ls-files link-basics/work | head -1)" ]]; then
     git rm -r -q link-basics/work
     git commit -q -m "Reset for the next replay: remove link-basics/work"
     git push -q origin HEAD
     echo "removed link-basics/work from the student repository"
   fi)
fi
echo "student repository: https://github.com/$account/$student.git"
gh api "repos/$account/$student/git/trees/main?recursive=1" -q '.tree[] | select(.type=="blob") | .path' | sed 's/^/  /'
curl -s "$manager/api/state" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("labs in the manager:", [l["name"] for l in d["labs"]])'
