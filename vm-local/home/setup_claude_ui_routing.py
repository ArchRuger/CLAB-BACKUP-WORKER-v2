#!/usr/bin/env python3
"""Configure Claude Code routing for the Containerlab Node Manager project.

Run on the VM, outside Claude Code, from your repository root:
    claude update
    python3 /path/to/setup_claude_ui_routing.py --apply

Without --apply, print the proposed file changes without writing them.
The main session is pinned to Fable 5.1; unassigned subagents default to Sonnet.
Optional: --include-fable adds a separate escalation subagent; it does not grant access.

Requires Python 3.9+, Git, and Claude Code 2.1.257+ for installation.
Existing settings, plugins, permission rules, and unrelated agents are preserved.
Changed files are backed up under this checkout's Git directory. No commits,
pushes, package installations, account changes, or model requests are performed.

Official references checked 2026-09-20:
https://code.claude.com/docs/en/sub-agents
https://code.claude.com/docs/en/model-config
https://code.claude.com/docs/en/settings
https://code.claude.com/docs/en/memory
"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys


MIN_VERSION = (2, 1, 257)
LEAD_MODEL = "claude-fable-5-1"
MARKER = "<!-- clab-ui-routing-setup-v1 -->"
ROUTING_ENV = {
    "CLAUDE_CODE_SUBAGENT_MODEL": "sonnet",
    "CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "0",
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "0",
}

COMMON = """Work only on the lead's assigned task and file scope. Follow applicable
project instructions. Preserve existing functionality, data, and security boundaries.
Do not spawn other agents, change release markers, commit, push, or deploy.
Return concise findings with file/symbol evidence, checks actually performed,
limitations, and the next action. Report a routing failure; do not claim a model
identity from your own generated text. The lead verifies execution metadata.
"""

AGENTS = {
    "clab-ui-scout": (
        "haiku",
        "Read, Glob, Grep",
        "Find UI files, selectors, handlers, tests, and exact references. Use for bounded read-only inventory, not design decisions.",
        """Locate the requested files and existing behavior. Use focused searches.
Return a compact map of paths, symbols, tests, and dependencies. Never decide
that a feature or asset is safe to delete merely because a search found no match.
Escalate ambiguous behavior to the lead. Do not edit files.
""",
    ),
    "clab-ui-builder": (
        "sonnet",
        "Read, Glob, Grep, Edit, Write, Bash",
        "Implement bounded UI changes, CSS, interaction behavior, documentation, and related regression tests.",
        """Implement the assigned acceptance criteria in the assigned paths only.
Reuse the existing UI architecture and preserve every unrelated workflow.
Check responsive layout, keyboard interaction, focus, loading, empty, error,
and disabled states where relevant. Run focused tests using disposable data.
Build generated assets through the prescribed source pipeline. Do not hand-edit
bundles or drop existing behavioral assertions. Send architectural ambiguity
to the lead before widening scope. Summarize the diff and test evidence.
""",
    ),
    "clab-ui-reviewer": (
        "opus",
        "Read, Glob, Grep",
        "Resolve ambiguous UX or architecture decisions and review risky UI changes, lost functionality, and compatibility boundaries.",
        """Review only the supplied decision or change. Trace affected workflows,
state transitions, accessibility, backend boundaries, and existing constraints.
For straightforward cosmetic work, tell the lead Sonnet can handle it.
For consequential decisions, recommend the smallest adequate approach and
specific acceptance checks. Read screenshots supplied by the lead if relevant.
Do not restart the whole audit, edit files, or invent browser validation.
""",
    ),
    "clab-ui-qa": (
        "sonnet",
        "Read, Glob, Grep, Bash",
        "Independently verify UI changes with existing tests and fixture/browser workflows; report regressions with evidence.",
        """Check the assigned acceptance criteria independently of the author.
Run the project's existing tests and browser scripts when available. Use
disposable fixtures, never production labs or live data. Capture evidence in
the assigned temporary/evidence location. Do not edit source, configuration,
or tests, even through Bash; request repairs from the lead. Distinguish code
inspection, unit tests, browser checks, and live checks. If browser tooling
is unavailable, record that gap rather than declaring visual success.
""",
    ),
}

FABLE_AGENT = (
    "fable",
    "Read, Glob, Grep",
    "Escalation only for a named difficult UI or architecture problem that remains unresolved after an Opus review.",
    """Address the exact unresolved question using the supplied evidence and prior
attempts. Do not redo routine exploration or implement unrelated changes.
Return an actionable decision, remaining uncertainty, and a minimal validation
plan. This role is optional and must not be used for ordinary UI edits.
""",
)


def agent_text(name, spec):
    model, tools, description, body = spec
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {json.dumps(description)}\n"
        f"model: {model}\n"
        f"tools: {tools}\n"
        "---\n\n"
        f"{MARKER}\n\n{body}\n{COMMON}"
    )


def rules_text(include_fable):
    escalation = (
        "- clab-ui-escalation / fable: one named problem still unresolved after Opus.\n"
        if include_fable else ""
    )
    return f"""{MARKER}
# UI task routing

For UI work, use Fable 5.1 ({LEAD_MODEL}) as the lead and these named subagent types:
- clab-ui-scout / haiku: bounded file, selector, reference, and test inventory.
- clab-ui-builder / sonnet: implementation, routine debugging, docs, and tests.
- clab-ui-reviewer / opus: ambiguous design, architectural risk, and consequential review.
- clab-ui-qa / sonnet: independent behavioral and browser verification.
{escalation}
Invoke these definitions by their exact names. Keep each definition's model;
do not override it without a task-specific reason and disclose substitutions.
Use scripts for deterministic checks. Do not use premium models for inventory.
Agent definitions select execution defaults; semantic routing remains a lead
responsibility, not an automatic classifier or a guarantee of account access.
Keep the fallback for unassigned subagents on Sonnet, not the lead's model.

Before delegation, state task, agent, requested model, scope, and acceptance
check. Verify the effective model in tool/task metadata when exposed; otherwise
report it as unverified. Reuse targeted evidence rather than sending every worker
the full history. Keep two or three independent workers active when useful;
use disjoint file ownership or worktrees and avoid recursive delegation.

The lead integrates results and owns shared files, release markers, commits,
pushes, and pickup notes. Follow the active task's authorization and existing
patch-checkpoint workflow. These rules do not themselves authorize Git writes.
Preserve existing functionality and use disposable fixtures. Escalate ambiguity
before expanding scope. An implementer must not be the only verifier of its work.
"""


def load_json(path):
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return data


def merged_settings(existing, include_fable):
    updated = json.loads(json.dumps(existing))
    updated["model"] = LEAD_MODEL
    allowed = updated.get("availableModels", [])
    if not isinstance(allowed, list) or not all(isinstance(x, str) for x in allowed):
        raise ValueError("availableModels must be a list of model strings")
    requested = ["haiku", "sonnet", "opus", "fable"]
    updated["availableModels"] = list(dict.fromkeys(allowed + requested))
    env = updated.setdefault("env", {})
    if not isinstance(env, dict):
        raise ValueError("env must be a JSON object")
    env.update(ROUTING_ENV)
    return updated


def run_git(root, *args):
    result = subprocess.run(
        ["git", "-C", str(root), *args], text=True, capture_output=True, check=True
    )
    return result.stdout.strip()


def claude_version():
    if not shutil.which("claude"):
        raise ValueError("Claude Code is not on PATH. Install it on the VM first.")
    result = subprocess.run(
        ["claude", "--version"], text=True, capture_output=True, check=True, timeout=20
    )
    match = re.search(r"\b(\d+)\.(\d+)\.(\d+)\b", result.stdout)
    if not match:
        raise ValueError("Could not determine Claude Code version; run claude --version.")
    version = tuple(map(int, match.groups()))
    if version < MIN_VERSION:
        raise ValueError("Run claude update first. This setup requires Claude Code 2.1.257+.")
    return ".".join(map(str, version))


def report_other_settings(root):
    # Inspect only routing-related values; do not dump settings or credentials.
    config_root = Path(os.environ.get("CLAUDE_CONFIG_DIR", str(Path.home() / ".claude")))
    paths = [config_root / "settings.json", root / ".claude/settings.local.json"]
    for path in paths:
        if not path.exists():
            continue
        try:
            data = load_json(path)
        except (ValueError, OSError):
            print(f"CHECK: {path} could not be parsed; inspect it with claude doctor.")
            continue
        keys = [key for key in ("model", "availableModels", "effortLevel") if key in data]
        env = data.get("env", {})
        if isinstance(env, dict):
            keys.extend("env." + key for key in ROUTING_ENV if key in env)
        permissions = data.get("permissions", {})
        if isinstance(permissions, dict):
            denied = permissions.get("deny", [])
            if isinstance(denied, list) and any(
                isinstance(x, str) and (x == "*" or x.startswith(("Agent", "Task")))
                for x in denied
            ):
                keys.append("permissions.deny (Agent/Task rule)")
        if keys:
            print(f"CHECK: {path} also configures {', '.join(keys)}.")
    for key in ("ANTHROPIC_MODEL", *ROUTING_ENV):
        if key in os.environ:
            print(f"CHECK: shell variable {key} is set.")
    print("Confirm /status, /model, and /tasks on the VM; managed policy can take precedence.")


def install(root, include_fable, apply):
    settings = root / ".claude/settings.json"
    agents = dict(AGENTS)
    if include_fable:
        agents["clab-ui-escalation"] = FABLE_AGENT
    # Keep the optional route on later re-runs if this setup already installed it.
    previous_escalation = root / ".claude/agents/clab-ui-escalation.md"
    if previous_escalation.is_file() and MARKER in previous_escalation.read_text(encoding="utf-8"):
        include_fable = True
        agents["clab-ui-escalation"] = FABLE_AGENT
    updated = merged_settings(load_json(settings), include_fable)
    files = {settings: json.dumps(updated, indent=2, ensure_ascii=False) + "\n"}
    for name, spec in agents.items():
        files[root / ".claude/agents" / f"{name}.md"] = agent_text(name, spec)
    files[root / ".claude/rules/clab-ui-routing.md"] = rules_text(include_fable)

    # Detect name/path collisions before changing any file.
    for path in files:
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root and root in p.parents):
            raise ValueError(f"This installer does not replace symlinked configuration: {path}")
        if path.exists() and not path.is_file():
            raise ValueError(f"Expected a regular file: {path}")
        if path != settings and path.exists() and MARKER not in path.read_text(encoding="utf-8"):
            raise ValueError(f"An existing custom definition occupies {path}; merge it manually.")
    agent_dir = root / ".claude/agents"
    if agent_dir.exists():
        for path in agent_dir.rglob("*.md"):
            if path in files:
                continue
            contents = path.read_text(encoding="utf-8")
            names = re.findall(r"^name:\s*[\"']?([a-z0-9-]+)[\"']?\s*$", contents, re.M)
            if any(name in agents for name in names):
                raise ValueError(f"An agent with the same name already exists in {path}; merge manually.")

    changed = {p: text for p, text in files.items() if not p.exists() or p.read_text(encoding="utf-8") != text}
    print("Agent routing:")
    print(f"  lead -> {LEAD_MODEL}")
    for name, spec in agents.items():
        print(f"  {name} -> {spec[0]}")
    print("Requested model choices: " + ", ".join(updated["availableModels"]))
    print("Existing plugin, permission, and unrelated settings are preserved.")
    for path in changed:
        print(("WRITE: " if apply else "WOULD WRITE: ") + str(path.relative_to(root)))
    if not apply:
        print("Preview only. Use --apply to install these files.")
        return
    if not changed:
        print("Already configured; no files changed.")
        return

    git_dir = Path(run_git(root, "rev-parse", "--absolute-git-dir"))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = git_dir / "claude-ui-routing-backups" / stamp
    backup.mkdir(parents=True)
    manifest = {"root": str(root), "previously_present": [], "created": []}
    for path in changed:
        relative = path.relative_to(root)
        if path.exists():
            target = backup / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            manifest["previously_present"].append(str(relative))
        else:
            manifest["created"].append(str(relative))
    (backup / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for path, contents in changed.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(contents)
    print(f"Backup: {backup}")
    print(f"Restart Claude Code from the repository root with: claude --model {LEAD_MODEL}")
    print("No Git commit, push, release bump, or deployment was performed.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="checkout directory; defaults to cwd")
    parser.add_argument("--apply", action="store_true", help="write the configuration (otherwise preview only)")
    parser.add_argument("--include-fable", action="store_true", help="add optional Fable escalation route")
    args = parser.parse_args()
    try:
        root = Path(run_git(args.repo, "rev-parse", "--show-toplevel")).resolve()
        if not (root / "clab-backup-ui").is_dir():
            raise ValueError("This does not look like the Containerlab Node Manager checkout.")
        if args.apply:
            print("Claude Code version: " + claude_version())
        install(root, args.include_fable, args.apply)
        report_other_settings(root)
        print("Use git diff and git status to review the new project configuration.")
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"Setup did not complete: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
