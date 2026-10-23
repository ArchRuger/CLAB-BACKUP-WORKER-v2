# Third-party skills vendored under `.claude/skills/`

Ten skills under `.claude/skills/` are copies of other authors' work, kept in the repository so that every clone
has the same skill set as the development VMs. `external-skills.lock.json` beside this file records the source
repository, the path inside it, the commit and a content hash of each copy; the configuration test
(`clab-backup-ui/tests/test_claude_config.py`) recomputes the hash and fails when a vendored copy was edited in
place. The `clab-*` skills are this project's own.

| Skill | Author | Source path | Commit | Licence | Use here |
|---|---|---|---|---|---|
| `webapp-testing` | Anthropic | `skills/webapp-testing` | `dbd4588f9e10` | Apache-2.0 (LICENSE.txt in the folder) | Browser automation against the existing fixture harness (clab-ui-qa). |
| `systematic-debugging` | Superpowers | `skills/systematic-debugging` | `2ce8aa15d05b` | MIT (_upstream_licenses/LICENSE) | Root cause before a patch: SSH, background job and UI failures. |
| `verification-before-completion` | Superpowers | `skills/verification-before-completion` | `2ce8aa15d05b` | MIT (_upstream_licenses/LICENSE) | Evidence before any claim of done, fixed or passing. |
| `test-driven-development` | Superpowers | `skills/test-driven-development` | `2ce8aa15d05b` | MIT (_upstream_licenses/LICENSE) | A reproducer and a regression check first; never delete production code to follow its generic example. |
| `writing-plans` | Superpowers | `skills/writing-plans` | `2ce8aa15d05b` | MIT (_upstream_licenses/LICENSE) | Scope and acceptance criteria for a multi-step task; the lead owns assignments. |
| `requesting-code-review` | Superpowers | `skills/requesting-code-review` | `2ce8aa15d05b` | MIT (_upstream_licenses/LICENSE) | Prepare a reviewable diff; the review itself goes to the project reviewers, not to its generic reviewer. |
| `receiving-code-review` | Superpowers | `skills/receiving-code-review` | `2ce8aa15d05b` | MIT (_upstream_licenses/LICENSE) | Verify review feedback before applying it. |
| `frontend-design` | Anthropic | `skills/frontend-design` | `dbd4588f9e10` | Apache-2.0 (LICENSE.txt in the folder) | Improve an assigned component inside the binding design contract. |
| `web-design-guidelines` | Vercel | `skills/web-design-guidelines` | `063bee94c3f4` | MIT (stated in the source repository README; no licence file ships with the skill) | Accessibility, focus, forms and interaction review. |
| `vercel-react-best-practices` | Vercel | `skills/react-best-practices` | `063bee94c3f4` | MIT (stated in the source repository README; no licence file ships with the skill) | The embedded editor adapter only; never a migration of the vanilla manager UI. |

Source repositories: Anthropic `https://github.com/anthropics/skills`, Superpowers `https://github.com/obra/superpowers`,
Vercel `https://github.com/vercel-labs/agent-skills`. The licence notices travel with each copy (`LICENSE.txt` or
`_upstream_licenses/LICENSE`); Vercel's repository states "MIT" in its README and ships no licence file, so that
statement is recorded here instead. These copies keep their authors' licences; they are not covered by this
repository's `LICENSE`.

## Rules

- **Never edit a vendored skill in place.** A local change breaks the hash and silently forks the upstream. Put
  project guidance in a `clab-*` skill, a rule or an agent definition instead; the agent definitions already say
  where an imported skill's generic advice (its own reviewer, its own commit policy, a framework migration) is
  overridden by this repository's rules.
- **Refresh deliberately, with Git alone.** Clone the source repository at the commit you want into a scratch
  directory (`git clone --depth 1 <url> <scratch> && git -C <scratch> checkout <commit>`), diff its skill folder
  against the vendored copy, read every change, then copy the folder here, copy the repository's root `LICENSE`
  (or `LICENSE.md`, `LICENSE.txt`, `NOTICE`) into the folder's `_upstream_licenses/` when the folder has no licence
  of its own, and write the new `commit` and `sha256` into the lockfile. The hash is the one `tree_hash()` in
  `clab-backup-ui/tests/test_claude_config.py` computes (sorted paths, each file's relative path, executable bit
  and bytes); the test reports the expected value when it differs. Commit the folder and the lockfile together,
  saying what changed. A refresh is reviewed third-party code, not a routine update.
- **Keep the licence files.** A copy without its notice is not redistributable.
