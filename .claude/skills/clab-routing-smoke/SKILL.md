---
name: clab-routing-smoke
description: "Verify that the project agents really run on their assigned models and tools before a campaign: four small paid delegations and a /tasks check. Run by a person, not chosen by the model."
disable-model-invocation: true
argument-hint: "[what to note in the summary]"
---

# Routing smoke

This checks the setup, not the application. Change no product file, deploy nothing, commit nothing.

1. Confirm the session: `/status` shows the intended model and settings sources; `/sandbox` shows the
   intended state; `/hooks` lists the project's Bash guard from `.claude/settings.json`.
2. Delegate four small independent tasks by these exact agent names, with no model override, each
   with a clear question and the file to read: `clab-ui-scout` names the path of the release marker;
   `clab-backend-engineer` names the test command from CLAUDE.md without running it; `risk-reviewer`
   names one privilege invariant with its file; `clab-fable-specialist` says who bumps the release and
   writes the CI test lists. No product edit, deployment or Git write in any of them.
3. While they run, open `/tasks`: each row names the model the subagent runs on and its effort. Expect
   one Haiku, one Sonnet, one Opus and one Fable route. A subagent saying its own name or model in its
   answer is not evidence; no runtime metadata means routing is unverified, however good the answer.
4. Confirm the workers could use the Skill tool and their preloaded skills, the language servers
   resolve on `PATH`, and the read-only reviewers had no edit or shell tool.
5. Report: verified items, requested and observed routing per agent, what was not verifiable, and
   blockers. Then run the configuration tests from `clab-backup-ui/`:
   `python3 -m unittest discover -s tests -p test_claude_config.py -v` and
   `node --test tests/test_claude_workflows.js`.

$ARGUMENTS
