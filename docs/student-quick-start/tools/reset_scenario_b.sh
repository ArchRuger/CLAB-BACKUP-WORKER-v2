#!/usr/bin/env bash
# Return the development VM to the documented starting state of Scenario B (authoring and QA use only).
#
#   bash docs/student-quick-start/tools/reset_scenario_b.sh [<repo-name>] [<github-account>]
#
# Leaves: no my-first-lab in the manager's My labs, no my-first-lab containers, no `my-first-lab` folder in the
# lab root (a copy made by an earlier replay is moved to ../projects-aside-qs/), no clone of the repository in the
# lab root, and the private repository (default ArchRuger/campaign2-my-network-labs) without the `my-first-lab`
# folder an earlier replay saved there (one ordinary Git commit in the manager's checkout; history is kept,
# nothing is forced). The VM Git registry is not touched. Create the repository once, by hand:
#   gh repo create <account>/<repo> --private --add-readme
set -euo pipefail
repo=${1:-campaign2-my-network-labs}
account=${2:-ArchRuger}
manager=http://127.0.0.1:8081
root=/srv/containerlab-node-manager/projects
dismiss_waiting_saves() {
  # a save that still waits for its Upload blocks "Remove from this manager": Keep snapshot only (the page's own button)
  for job in $(curl -s "$manager/api/state" | python3 -c 'import sys,json; d=json.load(sys.stdin); ids={l["id"] for l in d["labs"] if l["name"]=="my-first-lab"}; print(" ".join(j["id"] for j in d.get("git_jobs",[]) if j.get("lab_id") in ids and j.get("status") in ("review_pending","push_pending","export_pending","committed")))'); do
    curl -s -X POST -H 'Content-Type: application/json' -d '{"acknowledge":true}' "$manager/api/git/jobs/$job/dismiss" >/dev/null && echo "kept the waiting save $job on the VM only (Keep snapshot only)"
  done
}
dismiss_waiting_saves
for lab_id in $(curl -s "$manager/api/state" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(" ".join(l["id"] for l in d["labs"] if l["name"]=="my-first-lab"))'); do
  curl -s -X DELETE -H 'Content-Type: application/json' -d '{"name":"my-first-lab","prevent_reimport":false}' "$manager/api/labs/$lab_id" >/dev/null && echo "removed my-first-lab ($lab_id) from the manager"
done
for topology in "$root/my-first-lab/my-first-lab.clab.yml" "$root/$repo/my-first-lab/latest/my-first-lab.clab.yml"; do
  if [[ -f "$topology" ]] && docker ps -a --format '{{.Names}}' | grep -q '^clab-my-first-lab-'; then
    sudo containerlab destroy -t "$topology" --cleanup >/dev/null 2>&1 && echo "destroyed the my-first-lab containers"
  fi
done
sudo mkdir -p "$root/../projects-aside-qs"
if [[ -d "$root/my-first-lab" ]]; then
  sudo rm -rf "$root/../projects-aside-qs/my-first-lab.original"
  sudo mv "$root/my-first-lab" "$root/../projects-aside-qs/my-first-lab.original" && echo "moved the old my-first-lab folder aside"
fi
sudo rm -rf "$root/$repo"
checkout="$HOME/labs/$repo"
if [[ -d "$checkout/.git" ]]; then
  (cd "$checkout"
   git fetch -q origin
   if [[ -n "$(git ls-files my-first-lab | head -1)" ]]; then
     git rm -r -q my-first-lab
     git commit -q -m "Reset for the next replay: remove my-first-lab"
     git push -q origin HEAD
     echo "removed my-first-lab from the repository"
   fi)
fi
echo "repository: https://github.com/$account/$repo.git"
gh api "repos/$account/$repo/git/trees/main?recursive=1" -q '.tree[] | select(.type=="blob") | .path' | sed 's/^/  /'
curl -s "$manager/api/state" | python3 -c 'import sys,json; d=json.load(sys.stdin); print("labs in the manager:", [l["name"] for l in d["labs"]])'
