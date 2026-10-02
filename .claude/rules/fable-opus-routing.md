<!-- fable-opus-routing-v1 -->
# Model routing policy (Fable directs, Opus 5.5 selectively)

Fable 5.1 (`claude-fable-5-1`) directs. Haiku handles bounded scouting (`clab-ui-scout`) and decided
mechanical work (`mechanical-editor`). Sonnet handles the majority of implementation, debugging,
documentation, testing and QA (`clab-ui-builder`, `clab-ui-qa`, `docs-auditor`). Fable may assign **any
authorized task** to Opus 5.5 (`claude-opus-5-5`) when it judges Opus the best fit, including coding,
architecture, difficult debugging, research, writing, UI design, tests or review. No failed cheaper
attempt or new user approval is required. Use Opus selectively where its reasoning is likely to
materially improve the result; do not route trivial edits or routine checks to Opus by habit.

Keep the default subagent model Sonnet (`CLAUDE_CODE_SUBAGENT_MODEL=sonnet`) and forced overriding off
(`CLAUDE_CODE_SUBAGENT_MODEL_FORCE=0`). Select the exact model per invocation when supported (the Agent
tool's `model` parameter), or use the pinned definitions: `clab-opus-specialist` (general),
`clab-ui-reviewer` and `risk-reviewer` (read-only review) all carry `model: claude-opus-5-5`. When only
aliases are supported, verify that `opus` resolves to `claude-opus-5-5` (`ANTHROPIC_DEFAULT_OPUS_MODEL`).
Verify actual runtime routing from task/transcript metadata; never infer it from an agent's
self-description. Changing a role's model never removes its tool or behaviour restrictions:
`risk-reviewer` and `clab-ui-reviewer` stay read-only.

This policy supersedes the sentence in `clab-ui-routing.md` that forbade overriding a definition's model:
an override to Opus 5.5 for a task-specific reason is allowed and is disclosed in the delegation note.
