# INSTALLER-TUI-B1 pickup

| Field | Value |
|---|---|
| Task | INSTALLER-TUI-B1 — Slate Ops installer TUI (Worker B, dev2) |
| Coordination | https://github.com/ArchRuger/CLAB-BACKUP-WORKER-v2/issues/64 |
| Branch | `worker-b/installer-tui-slate-ops` |
| Base | `e7ffbc108d7c995f3487902acdbb4448c87bc674` (`main`) |
| HEAD | see `git log -1` on the branch (updated at every checkpoint below) |

## State

Working: shared plan in `install-manager.py` (plain behaviour unchanged, every existing test claim kept);
`--tui`/`--plain`/`--setup-tui`; private hash-verified venv bootstrap; installer lock (plain and TUI);
dashboard with read-only probes; settings, review, run (phases, output, follow, stop after step,
recovery), result and help screens; terminal handoff for sudo, the first-setup launcher and Git.

## Checkpoints

1. Baseline and shared core + painted shell (this commit series).

## Open defects / limitations

- During a terminal handoff (sudo prompt, first-setup launcher, Git setup) the child owns the real
  terminal: an SSH drop stops it exactly as in the plain installer. Only piped phases (own process
  group) finish after a hang-up.
- No resume after reconnect: a rerun inspects the actual system state and repeats what is needed.

## Next command

```bash
cd ~/projects/clab-manager/clab-backup-ui && python3 -m unittest discover -s tests -p 'test_install_*.py' -v
```
