---
name: lab-builder-quality-pass
description: "Lab builder QA pass of 2026-09-20 (branch claude/lab-builder-quality-pass, 1.30.1, pushed as PR #40 on 2026-09-20): where the register and evidence are, what stayed open, and the testing traps it uncovered"
metadata:
  type: project
---

On 2026-09-20 a review-and-fix pass over the visual lab builder ran on branch `claude/lab-builder-quality-pass` (from main 5e9aa86). It prepared **1.30.1** (markers via `set-release.py`, history sections written); the user then said "push it and open the PR", and it is pull request **#40** (the user merges; nothing is tagged). The register with every finding, cause and evidence path is `docs/lab-builder/QA-FINDINGS.md`; scripts, screenshots and reviewer experiments are in `~/research/lab-builder/qa/` (persistent).

**Why:** a later session will be asked to continue, push or extend this; the traps below cost real time.

**How to apply:**
- Always run one live browser pass through the LAN address (`http://192.168.132.132:8081`), not only `127.0.0.1`: a plain-HTTP origin is not a secure context (`crypto.subtle` undefined). The builder's second save was broken that way since 1.30.0 and no localhost test could see it.
- `/static/lab-builder/assets/main.js?v=<release>` is cached `immutable` and has no content hash: a change to `lab-builder/src/main.tsx` only reaches real browsers with a new release number (Playwright contexts start with an empty cache and hide this).
- Upgrade the dev manager with `sudo bash deploy/start-manager.sh` (helpers must equal the manager's VERSION), not only `docker compose up --build`. Use `--manager-only` when a capture session container (`clab-capture-...`) that is not yours is running: a full run restarts the capture service and deletes sessions. The capture session service on the VM was still a 1.29.1 image on 2026-09-20 for that reason.
- Reviewer subagents briefed as attackers on the root helper (`host_operations.py` symlink/TOCTOU analysis) were stopped by the model's safety filter; that review is still open (S-1 in the register). Do not rephrase around it; tell the user.
- cJunosEvolved may hang on first boot on this host (>40 min, no soft lockups); one *Redeploy* through the manager brought it up. vJunos-switch needs ~14 min. Builder interface patterns for cEOS, cJunosEvolved and vJunos-switch were proven by LLDP on a builder-made lab; XRv9k has no image here.
- The fixture manager now marks a lab it deployed as running, which starts the automatic login test: scripts must retry a preview that is refused with "Wait for the lab backup or login job".

See [[visual-lab-builder]], [[fixture-manager-browser-validation]], [[dev2-host-environment]], [[user-pr-workflow]].
