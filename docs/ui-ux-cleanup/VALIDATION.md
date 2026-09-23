# UI/UX cleanup: validation record

Only what was actually run is recorded. Each entry names the kind of evidence: static (grep, lint),
unit (Python/node tests), fixture/browser (fixture manager + Playwright), CI, or live (the deployed
manager and lab nodes on the development VM). Raw logs stay outside Git.

## Chunk 0: baseline, cleanup, routing (2026-09-23)

### Disk (live, `df -h /`)

| Point | Used | Available |
|---|---|---|
| before | 51G | 18G |
| after `docker builder prune -af` (6.5 GB) | 47G | 22G |
| after removing 14 superseded `clab-backup:*` images | 42G | 27G |
| after `apt-get clean` | 41G | 28G |

Kept: every node image (`n24l/*`), `network-multitool`, the capture and telemetry images, the running
`clab-backup:1.30.35`, all volumes, `/srv` (data, archives, projects), checkouts, `~/.cache/ms-playwright`.
The manager answered `200` on `/` after the cleanup.

### Routing (observed from subagent transcript metadata)

| Route | Expected | Configured | Observed | Result |
|---|---|---|---|---|
| Main director | claude-fable-5-1 | `.claude/settings.json` model | session runs as Fable 5.1 (`/model` kept `Fable 5.1`; `CLAUDE_CODE_EXECPATH` 2.1.280) | pass |
| `clab-ui-scout` | Haiku | `model: haiku` | `claude-haiku-4-5-20251001` in three scout transcripts | pass |
