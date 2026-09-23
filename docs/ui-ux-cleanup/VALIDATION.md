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
| `clab-ui-scout` | Haiku | `model: haiku` | `claude-haiku-4-5-20251001` in six scout transcripts | pass |
| `clab-ui-builder` (default) | Sonnet | `model: sonnet` | `claude-sonnet-5` in every builder transcript (A1, A2–A6, A4–A5, B1/B2/B4, B5/B7, B6, D1, D2, E1–E4, B3, helper fix, C1–C3) | pass |
| `clab-ui-builder` with `model: opus` override | Opus 5.5 | per-invocation `opus` | `claude-opus-5-5` (A7 bootstrap builder, 93 turns); the next builder without an override ran `claude-sonnet-5` | pass |
| `clab-ui-qa` | Sonnet | `model: sonnet` | `claude-sonnet-5` (browser QA 1.30.36; live QA 1.30.37 a/b) | pass |
| `clab-ui-reviewer` (design investigation) | Opus 5.5 | `model: opus` at session start (pinned to `claude-opus-5-5` in the file since) | `claude-opus-5-5` (E7 design) | pass |
| `risk-reviewer` | Opus 5.5 | `model: claude-opus-5-5` | `claude-opus-5-5` (chunk 1 review, restore + helper review, helper re-review) | pass |
| `clab-opus-specialist` | Opus 5.5 | `model: claude-opus-5-5` (new definition; unavailable to the session that created it until the definition was reloaded, then used) | `claude-opus-5-5` (E5–E7 implementation, C4 adapter and page phases) | pass |

Evidence: the `"model"` fields of the subagent transcripts under the session's task directory (counted with
`grep -o '"model":"[^"]*"' <task>.output | sort | uniq -c`); no route was inferred from an agent's self-description.
Active CLI: Claude Code 2.1.280 (native install, the minimum for Opus 5.5; `claude update` reported it current).
