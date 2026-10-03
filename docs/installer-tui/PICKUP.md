# INSTALLER-TUI-B1 pickup

| Field | Value |
|---|---|
| Task | INSTALLER-TUI-B1 — Slate Ops installer TUI (Worker B, dev2) |
| Coordination | https://github.com/ArchRuger/CLAB-BACKUP-WORKER-v2/issues/64 |
| Pull request | https://github.com/ArchRuger/CLAB-BACKUP-WORKER-v2/pull/65 (draft; Worker A integrates) |
| Branch | `worker-b/installer-tui-slate-ops` |
| Base | `e7ffbc108d7c995f3487902acdbb4448c87bc674` (`main`) |
| HEAD | see `git log -1` on the branch (updated at every checkpoint below) |

## State

Working: shared plan in `install-manager.py` (plain behaviour unchanged, every existing test claim kept);
`--tui`/`--plain`/`--setup-tui`; private hash-verified venv bootstrap; installer lock (plain and TUI);
dashboard with read-only probes; settings, review, run (phases, output, follow, stop after step,
recovery), result and help screens; terminal handoff for sudo, the first-setup launcher and Git.

## Checkpoints

1. `5ec3207` — baseline, shared plan in `install-manager.py`, stdlib core, painted shell, 273 stdlib tests.
2. `66d2d64` — live dev2 install/update/health, process-safety review fixes, 70 headless tests, 36 PTY checks.
3. `f337fa6` — real dpkg-lock and sudo-expiry validation, usability review fixes, gap tests (core 165, app 110), scrubbed snapshots, parity refresh, handoff.

## Evidence

- [VALIDATION.md](VALIDATION.md) — every suite and live run, by evidence type.
- [evidence/pty-check.txt](evidence/pty-check.txt) — real-terminal fixture checks.
- [snapshots/](snapshots/) — fixture screenshots (invented account, host, paths and status).
- [HANDOFF.md](HANDOFF.md) — CI lines, documentation proposals, helper proposal, release actions for A.

## dev2 state left behind

- Manager installed from this checkout (source as of 1.30.58) with the capture stack; clab-discovery has a
  dev2-only password (kept outside the repository). Git setup not completed (no GitHub account here).
- Sentinel lab `dev2-sentinel` (one alpine node) still deployed for update checks:
  `sudo containerlab destroy -t ~/scratch/sentinel/sentinel.clab.yml` removes it.
- Disposable account `tuiprobe` (password sudo) with its own fixture checkout and TUI venv.
- Fixture checkouts: `~/scratch/clab-fixture`, `~/scratch/clab-pty-fixture` (fake helpers).

## Open defects / limitations

- During a terminal handoff (sudo prompt, first-setup launcher, Git setup) the child owns the real
  terminal: an SSH drop stops it exactly as in the plain installer. Only piped phases (own process
  group) finish after a hang-up.
- No resume after reconnect: a rerun inspects the actual system state and repeats what is needed.

## Next command

```bash
cd ~/projects/clab-manager/clab-backup-ui && python3 -m unittest discover -s tests -p 'test_install_*.py' -v
```
