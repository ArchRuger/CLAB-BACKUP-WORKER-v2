"""Consistency checks for the repository's Claude Code configuration under `.claude/`.

Standard library only: this module runs in the first CI group with the system `python3`, before any
virtual environment exists, so there is no PyYAML. It checks the agent, skill and rule frontmatter
against the documented field sets and against each other, the roster against the agent files,
`settings.json`, the vendored skills against their lockfile, the Bash guard hook and the workflow files.

It only reads the checkout. The guard hook is imported with bytecode writing switched off and run
as a subprocess with `PYTHONDONTWRITEBYTECODE=1`, so nothing is written under the repository.
"""
import fnmatch
import functools
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import unittest
import warnings

ROOT = Path(__file__).resolve().parents[2]
CLAUDE = ROOT / '.claude'

AGENT_FIELDS = {
    'name', 'description', 'tools', 'disallowedTools', 'model', 'permissionMode', 'maxTurns',
    'autoCompactWindow', 'skills', 'mcpServers', 'hooks', 'memory', 'background', 'omitClaudeMd',
    'effort', 'isolation', 'color', 'initialPrompt', 'experimental',
}
SKILL_FIELDS = {
    'name', 'description', 'when_to_use', 'argument-hint', 'arguments', 'disable-model-invocation',
    'user-invocable', 'allowed-tools', 'disallowed-tools', 'model', 'effort', 'context', 'agent',
    'background', 'hooks', 'paths', 'shell', 'metadata', 'license', 'compatibility',
}
RULE_FIELDS = {'paths'}
EFFORTS = {'low', 'medium', 'high', 'xhigh', 'max'}
COLORS = {'red', 'blue', 'green', 'yellow', 'purple', 'orange', 'pink', 'cyan'}
MEMORY = {'user', 'project', 'local'}
BOOLEANS = {'true', 'false', 'yes', 'no', 'on', 'off', '1', '0'}
TRUE_VALUES = {'true', 'yes', 'on', '1'}
BOOLEAN_FIELDS = ('disable-model-invocation', 'user-invocable', 'background')

READ_ONLY_AGENTS = {'risk-reviewer', 'clab-ui-reviewer', 'clab-ui-scout'}
READ_ONLY_FORBIDDEN_TOOLS = ('Edit', 'Write', 'NotebookEdit', 'Bash', 'Agent')
ALSO_NO_AGENT = {'mechanical-editor', 'docs-auditor'}
MODEL_LABELS = {'Fable 5.1': 'FABLE', 'Opus 5.5': 'OPUS', 'Sonnet 5.5': 'SONNET', 'Haiku 5.5': 'HAIKU'}
ROUTING_RULES_WITHOUT_FRONTMATTER = ('fable-opus-routing.md', 'clab-ui-routing.md', '00-clab-two-worker-routing.md')
WORKFLOWS = {'clab-design-review', 'clab-review-changes', 'clab-slice-verify'}


class FrontmatterError(Exception):
    pass


# ---------------------------------------------------------------------------------------------------------
# The YAML subset used in this repository
# ---------------------------------------------------------------------------------------------------------

KEY_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_-]*):(?:[ \t]+(.*?))?[ \t]*$')
NESTED_KEY_RE = re.compile(r'^[ \t]+([A-Za-z_][A-Za-z0-9_-]*):(?:[ \t]+(.*?))?[ \t]*$')
ITEM_RE = re.compile(r'^[ \t]*-[ \t]+(.*?)[ \t]*$')


def parse_scalar(raw, where, strict=True):
    """One scalar: "double", 'single' or plain. Anything else is syntax this repository does not use."""
    text = raw.strip()
    if text.startswith('"'):
        if len(text) < 2 or not text.endswith('"'):
            raise FrontmatterError(f'{where}: unterminated or trailing text after a double-quoted scalar: {raw!r}')
        try:
            return json.loads(text)
        except ValueError as error:
            raise FrontmatterError(f'{where}: double-quoted scalar is not valid JSON-style escaping ({error}): {raw!r}')
    if text.startswith("'"):
        if len(text) < 2 or not text.endswith("'"):
            raise FrontmatterError(f'{where}: unterminated or trailing text after a single-quoted scalar: {raw!r}')
        return text[1:-1].replace("''", "'")
    if text and text[0] in '[{|>&*!@`%':
        raise FrontmatterError(f'{where}: flow collections, block scalars and anchors are not supported: {raw!r}')
    if strict and (': ' in text or ' #' in text or text.endswith(':')):
        raise FrontmatterError(f'{where}: an unquoted scalar must not contain ": " or " #" (quote it): {raw!r}')
    return text


def parse_frontmatter(text, where, strict=True):
    """Return (dict, None) for a file with frontmatter, (None, None) for one without.

    Values are str, list[str] (a `- item` list) or dict[str, str] (one level of nested `key: value`, which
    only `metadata` uses). A file that uses anything else raises FrontmatterError.
    """
    lines = text.replace('\r\n', '\n').split('\n')
    if not lines or lines[0].rstrip() != '---':
        return None, None
    end = None
    for index in range(1, len(lines)):
        if lines[index].rstrip() == '---':
            end = index
            break
    if end is None:
        raise FrontmatterError(f'{where}: frontmatter opened with --- but never closed')
    result = {}
    pending = None  # key whose value (list or nested mapping) follows
    for number, line in enumerate(lines[1:end], start=2):
        location = f'{where}:{number}'
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        if not line[0].isspace() and not line.startswith('- '):
            match = KEY_RE.match(line)
            if not match:
                raise FrontmatterError(f'{location}: not a `key: value` line: {line!r}')
            key, value = match.group(1), match.group(2)
            if key in result:
                raise FrontmatterError(f'{location}: duplicate key {key!r}')
            if value is None or value == '':
                result[key] = ''
                pending = key
            else:
                result[key] = parse_scalar(value, location, strict)
                pending = None
            continue
        if pending is None:
            raise FrontmatterError(f'{location}: indented line without a key to belong to: {line!r}')
        item = ITEM_RE.match(line)
        nested = NESTED_KEY_RE.match(line)
        if item and not nested or (item and line.lstrip().startswith('- ')):
            if isinstance(result[pending], dict):
                raise FrontmatterError(f'{location}: list item inside a nested mapping: {line!r}')
            if result[pending] == '':
                result[pending] = []
            result[pending].append(parse_scalar(item.group(1), location, strict))
        elif nested:
            if pending != 'metadata':
                raise FrontmatterError(f'{location}: nested mapping is only supported for `metadata`: {line!r}')
            if isinstance(result[pending], list):
                raise FrontmatterError(f'{location}: mapping key inside a list: {line!r}')
            if result[pending] == '':
                result[pending] = {}
            result[pending][nested.group(1)] = parse_scalar(nested.group(2) or '', location, strict)
        else:
            raise FrontmatterError(f'{location}: unsupported frontmatter syntax: {line!r}')
    return result, None


def as_list(value):
    """A frontmatter value that may be a list or a comma-separated string, as a list of strings."""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [part.strip() for part in value.split(',') if part.strip()]
    raise AssertionError(f'cannot read {value!r} as a list')


# ---------------------------------------------------------------------------------------------------------
# Loading the tree (read once)
# ---------------------------------------------------------------------------------------------------------

def read(path):
    return Path(path).read_text(encoding='utf-8')


@functools.lru_cache(maxsize=None)
def settings():
    return json.loads(read(CLAUDE / 'settings.json'))


def model_id(label):
    return settings()['env'][f'ANTHROPIC_DEFAULT_{label}_MODEL']


@functools.lru_cache(maxsize=None)
def agents():
    """name (file stem) -> (path, frontmatter or None, error or None)."""
    found = {}
    for path in sorted((CLAUDE / 'agents').glob('*.md')):
        try:
            front, _ = parse_frontmatter(read(path), path.relative_to(ROOT).as_posix())
            found[path.stem] = (path, front, None)
        except FrontmatterError as error:
            found[path.stem] = (path, None, str(error))
    return found


def agent_front(name):
    path, front, error = agents()[name]
    if error:
        raise AssertionError(error)
    if front is None:
        raise AssertionError(f'{path.relative_to(ROOT)} has no frontmatter')
    return front


def is_vendored(directory):
    return not directory.name.startswith('clab-')


@functools.lru_cache(maxsize=None)
def skills():
    """directory name -> (path, frontmatter or None, error or None) for every `.claude/skills/*/SKILL.md`."""
    found = {}
    for path in sorted((CLAUDE / 'skills').glob('*/SKILL.md')):
        directory = path.parent
        try:
            front, _ = parse_frontmatter(read(path), path.relative_to(ROOT).as_posix(), strict=not is_vendored(directory))
            found[directory.name] = (path, front, None)
        except FrontmatterError as error:
            found[directory.name] = (path, None, str(error))
    return found


def skill_front(name):
    path, front, error = skills()[name]
    if error:
        raise AssertionError(error)
    if front is None:
        raise AssertionError(f'{path.relative_to(ROOT)} has no frontmatter')
    return front


@functools.lru_cache(maxsize=None)
def rules():
    """file name -> (path, text, frontmatter or None, error or None)."""
    found = {}
    for path in sorted((CLAUDE / 'rules').glob('*.md')):
        text = read(path)
        try:
            front, _ = parse_frontmatter(text, path.relative_to(ROOT).as_posix())
            found[path.name] = (path, text, front, None)
        except FrontmatterError as error:
            found[path.name] = (path, text, None, str(error))
    return found


@functools.lru_cache(maxsize=None)
def tracked_files():
    """Repository files as POSIX paths: Git's tracked (and not ignored untracked) files, else a walk."""
    if shutil.which('git'):
        try:
            done = subprocess.run(
                ['git', '-C', str(ROOT), 'ls-files', '-z', '--cached', '--others', '--exclude-standard'],
                capture_output=True, timeout=60)
            if done.returncode == 0 and done.stdout:
                return tuple(sorted(name for name in done.stdout.decode('utf-8', 'surrogateescape').split('\0') if name))
        except (OSError, subprocess.SubprocessError):
            pass
    found = []
    for directory, names, files in os.walk(ROOT):
        names[:] = [name for name in names if name not in ('.git', '.venv', 'node_modules', '__pycache__')]
        for name in files:
            found.append((Path(directory) / name).relative_to(ROOT).as_posix())
    return tuple(sorted(found))


def glob_regex(pattern):
    """A glob with `**` semantics: `**/` is zero or more directories, `*` and `?` stay inside a segment."""
    out = []
    index = 0
    while index < len(pattern):
        if pattern.startswith('**/', index):
            out.append('(?:.*/)?')
            index += 3
        elif pattern.startswith('**', index):
            out.append('.*')
            index += 2
        elif pattern[index] == '*':
            out.append('[^/]*')
            index += 1
        elif pattern[index] == '?':
            out.append('[^/]')
            index += 1
        else:
            out.append(re.escape(pattern[index]))
            index += 1
    return re.compile('^' + ''.join(out) + '$')


def tree_hash(directory):
    """The content hash recorded in `.claude/external-skills.lock.json` (algorithm fixed by the lockfile)."""
    digest = hashlib.sha256()
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise AssertionError(f'{path.relative_to(ROOT)} is a symbolic link')
        if path.is_file():
            relative = path.relative_to(directory).as_posix().encode()
            content = path.read_bytes()
            digest.update(len(relative).to_bytes(8, 'big'))
            digest.update(relative)
            digest.update((path.stat().st_mode & 0o111).to_bytes(2, 'big'))
            digest.update(len(content).to_bytes(8, 'big'))
            digest.update(content)
    return digest.hexdigest()


def table_rows(text, header_start):
    """The cell lists of the Markdown table whose header row starts with `header_start`."""
    rows = []
    inside = False
    for line in text.split('\n'):
        if not inside:
            if line.startswith(header_start):
                inside = True
            continue
        if not line.startswith('|'):
            break
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if all(set(cell) <= set('-: ') for cell in cells):
            continue
        rows.append(cells)
    return rows


def backticked(cell):
    return re.findall(r'`([^`]+)`', cell)


# ---------------------------------------------------------------------------------------------------------
# Agents (checks 1 to 5)
# ---------------------------------------------------------------------------------------------------------

class AgentDefinitions(unittest.TestCase):
    def test_there_are_fifteen_agents(self):
        self.assertEqual(len(agents()), 15, sorted(agents()))

    def test_frontmatter_parses_and_uses_documented_fields_only(self):
        for name, (path, front, error) in agents().items():
            with self.subTest(agent=name):
                self.assertIsNone(error)
                self.assertIsNotNone(front, f'{path.relative_to(ROOT)} has no frontmatter')
                self.assertEqual(front.get('name'), name, 'name must equal the file stem')
                self.assertTrue(str(front.get('description', '')).strip(), 'description must not be empty')
                unknown = set(front) - AGENT_FIELDS
                self.assertFalse(unknown, f'fields the documentation does not list: {sorted(unknown)}')

    def test_model_effort_color_turns_and_memory_values(self):
        ids = {model_id(label) for label in ('FABLE', 'OPUS', 'SONNET', 'HAIKU')}
        self.assertEqual(len(ids), 4, 'the four ANTHROPIC_DEFAULT_*_MODEL ids must be distinct')
        for name in agents():
            front = agent_front(name)
            with self.subTest(agent=name):
                self.assertIn(front.get('model'), ids, 'model must be one of the four exact ids in settings.json env')
                self.assertIn(front.get('effort'), EFFORTS)
                self.assertIn(front.get('color'), COLORS)
                if 'maxTurns' in front:
                    self.assertRegex(str(front['maxTurns']), r'^[1-9][0-9]*$', 'maxTurns must be a positive integer')
                if 'memory' in front:
                    self.assertIn(front['memory'], MEMORY)

    def test_skills_start_with_the_worker_contract_and_exist(self):
        for name in agents():
            front = agent_front(name)
            with self.subTest(agent=name):
                listed = as_list(front.get('skills', []))
                self.assertTrue(listed, 'skills must be listed')
                self.assertEqual(listed[0], 'clab-worker-contract', 'clab-worker-contract must come first')
                self.assertEqual(len(listed), len(set(listed)), f'duplicate skill in {listed}')
                for skill in listed:
                    self.assertTrue((CLAUDE / 'skills' / skill / 'SKILL.md').is_file(), f'skill {skill!r} does not exist')
                    value = str(skill_front(skill).get('disable-model-invocation', 'false')).lower()
                    self.assertNotIn(value, TRUE_VALUES, f'{skill} sets disable-model-invocation and cannot be preloaded')

    def test_read_only_agents_are_exactly_the_reviewers_and_the_scout(self):
        for name in agents():
            front = agent_front(name)
            with self.subTest(agent=name):
                if name in READ_ONLY_AGENTS:
                    self.assertIn('tools', front, 'a read-only agent needs a tools allowlist')
                    tools = as_list(front['tools'])
                    self.assertTrue(tools)
                    for tool in tools:
                        self.assertFalse(tool.startswith('mcp__'), f'{tool} is an MCP tool')
                        for forbidden in READ_ONLY_FORBIDDEN_TOOLS:
                            self.assertFalse(tool == forbidden or tool.startswith(forbidden + '('),
                                             f'read-only agent lists {tool}')
                    self.assertNotIn('memory', front, 'a read-only agent keeps no memory directory')
                else:
                    self.assertIn('mcp__*', as_list(front.get('disallowedTools', '')), 'disallowedTools must contain mcp__*')
                    if name in ALSO_NO_AGENT:
                        self.assertIn('Agent', as_list(front['disallowedTools']), 'disallowedTools must contain Agent')
                    if 'tools' in front:
                        tools = as_list(front['tools'])
                        self.assertIn('Write', tools)
                        self.assertIn('Edit', tools)

    def test_haiku_agents_are_bounded_by_max_turns(self):
        haiku = model_id('HAIKU')
        chosen = [name for name in agents() if agent_front(name).get('model') == haiku]
        self.assertEqual(sorted(chosen), ['clab-ui-scout', 'mechanical-editor'])
        for name in chosen:
            with self.subTest(agent=name):
                self.assertIn('maxTurns', agent_front(name))


# ---------------------------------------------------------------------------------------------------------
# Skills (checks 6 to 8)
# ---------------------------------------------------------------------------------------------------------

class SkillDefinitions(unittest.TestCase):
    def test_frontmatter_names_fields_and_booleans(self):
        mismatches = []
        for name, (path, front, error) in skills().items():
            with self.subTest(skill=name):
                self.assertIsNone(error)
                self.assertIsNotNone(front, f'{path.relative_to(ROOT)} has no frontmatter')
                if front.get('name') != name:
                    if name.startswith('clab-'):
                        self.fail(f'name {front.get("name")!r} must equal the directory name {name!r}')
                    mismatches.append(f'{name}: name field is {front.get("name")!r}')
                unknown = set(front) - SKILL_FIELDS
                self.assertFalse(unknown, f'fields the documentation does not list: {sorted(unknown)}')
                self.assertTrue(str(front.get('description', '')).strip(), 'description must not be empty')
                for field in BOOLEAN_FIELDS:
                    if field in front:
                        self.assertIn(str(front[field]).lower(), BOOLEANS, f'{field} must be a boolean')
        for line in mismatches:
            warnings.warn(f'vendored skill name differs from its directory: {line}')

    def test_there_are_project_skills_and_vendored_skills(self):
        names = list(skills())
        self.assertTrue([name for name in names if name.startswith('clab-')])
        self.assertTrue([name for name in names if not name.startswith('clab-')])

    def test_smoke_skill_is_manual_and_worker_contract_is_hidden(self):
        self.assertEqual(str(skill_front('clab-routing-smoke').get('disable-model-invocation')).lower(), 'true')
        self.assertEqual(str(skill_front('clab-worker-contract').get('user-invocable')).lower(), 'false')

    def test_path_globs_match_a_repository_file(self):
        files = tracked_files()
        self.assertGreater(len(files), 100, 'could not list the repository files')
        sources = []
        for name in skills():
            front = skill_front(name)
            if 'paths' in front:
                sources.append((f'.claude/skills/{name}/SKILL.md', as_list(front['paths'])))
        for filename, (path, _text, front, error) in rules().items():
            self.assertIsNone(error)
            if front and 'paths' in front:
                sources.append((path.relative_to(ROOT).as_posix(), as_list(front['paths'])))
        self.assertTrue(sources)
        for source, globs in sources:
            for pattern in globs:
                with self.subTest(source=source, glob=pattern):
                    regex = glob_regex(pattern)
                    self.assertTrue(any(regex.match(path) for path in files), f'{pattern} matches no repository file')


# ---------------------------------------------------------------------------------------------------------
# Rules (checks 9 to 12)
# ---------------------------------------------------------------------------------------------------------

class RuleFiles(unittest.TestCase):
    def test_frontmatter_has_only_paths(self):
        for filename, (path, _text, front, error) in rules().items():
            with self.subTest(rule=filename):
                self.assertIsNone(error)
                if filename.startswith('routing-'):
                    self.assertIsNotNone(front, 'a path-scoped rule needs frontmatter')
                    self.assertIn('paths', front)
                    self.assertTrue(as_list(front['paths']))
                if filename in ROUTING_RULES_WITHOUT_FRONTMATTER:
                    self.assertIsNone(front, 'this rule must load unconditionally: no frontmatter')
                if front is not None:
                    self.assertFalse(set(front) - RULE_FIELDS, f'fields besides paths: {sorted(set(front) - RULE_FIELDS)}')

    def test_the_three_policy_rules_exist(self):
        for filename in ROUTING_RULES_WITHOUT_FRONTMATTER:
            self.assertIn(filename, rules())

    def test_roster_lists_exactly_the_agents_with_their_models_and_write_access(self):
        _path, text, _front, _error = rules()['clab-ui-routing.md']
        rows = [cells for cells in table_rows(text, '| Agent ') if len(cells) >= 4]
        listed = {}
        for cells in rows:
            names = backticked(cells[0])
            self.assertEqual(len(names), 1, f'roster row without one agent name: {cells}')
            self.assertNotIn(names[0], listed, f'{names[0]} listed twice')
            listed[names[0]] = cells
        self.assertEqual(sorted(listed), sorted(agents()))
        for name, cells in listed.items():
            with self.subTest(agent=name):
                self.assertIn(cells[1], MODEL_LABELS, f'unknown model label {cells[1]!r}')
                self.assertEqual(model_id(MODEL_LABELS[cells[1]]), agent_front(name).get('model'),
                                 f'roster says {cells[1]}')
                self.assertEqual(cells[2], 'no' if name in READ_ONLY_AGENTS else 'yes')

    def test_every_agent_is_named_in_claude_md_and_the_routing_policy(self):
        claude_md = read(ROOT / 'CLAUDE.md')
        policy = rules()['fable-opus-routing.md'][1] + rules()['clab-ui-routing.md'][1]
        for name in agents():
            with self.subTest(agent=name):
                self.assertIn(name, claude_md, 'CLAUDE.md must name the agent')
                self.assertIn(name, policy, 'the routing policy or the roster must name the agent')

    def test_path_scoped_table_names_existing_rules_and_agents(self):
        text = rules()['clab-ui-routing.md'][1]
        rows = [cells for cells in table_rows(text, '| Rule ') if len(cells) >= 4]
        self.assertTrue(rows, 'the path-scoped rule table is missing')
        found_rules = set()
        for cells in rows:
            with self.subTest(rule=cells[0]):
                names = backticked(cells[0])
                self.assertEqual(len(names), 1)
                self.assertIn(names[0], rules(), f'{names[0]} is not a file in .claude/rules')
                found_rules.add(names[0])
                for column in (2, 3):
                    for token in backticked(cells[column]):
                        if re.fullmatch(r'[a-z][a-z0-9-]*', token):
                            self.assertIn(token, agents(), f'{token!r} is not an agent')
        routing = {name for name in rules() if name.startswith('routing-')}
        self.assertEqual(found_rules, routing, 'every routing-*.md rule belongs in the table and the reverse')

    def test_test_files_named_in_rules_exist(self):
        tests = ROOT / 'clab-backup-ui' / 'tests'
        names = sorted(path.name for path in tests.iterdir())
        seen = 0
        for filename, (_path, text, _front, _error) in rules().items():
            for mention in sorted(set(re.findall(r'`(test_[A-Za-z0-9_*]+\.(?:py|js))`', text))):
                seen += 1
                with self.subTest(rule=filename, test=mention):
                    self.assertTrue(fnmatch.filter(names, mention), f'{mention} is not under clab-backup-ui/tests/')
        self.assertGreater(seen, 0, 'no test file mentions found: the pattern is wrong or the rules lost them')


# ---------------------------------------------------------------------------------------------------------
# settings.json and .gitignore (checks 13 to 16)
# ---------------------------------------------------------------------------------------------------------

class SettingsFile(unittest.TestCase):
    def test_model_and_environment(self):
        data = settings()
        env = data['env']
        self.assertEqual(data['model'], model_id('FABLE'))
        self.assertEqual(env.get('CLAUDE_CODE_SUBAGENT_MODEL'), model_id('SONNET'))
        self.assertEqual(env.get('CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH'), '2')
        self.assertEqual(env.get('CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS'), '0')
        for label in ('FABLE', 'OPUS', 'SONNET', 'HAIKU'):
            self.assertIn(f'ANTHROPIC_DEFAULT_{label}_MODEL', env)
        self.assertNotIn('CLAUDE_CODE_SUBAGENT_MODEL_FORCE', env, 'forced overriding must stay off')
        self.assertNotIn('effortLevel', data, 'effort is set per agent, not globally')

    def test_plugins_and_denied_reads(self):
        data = settings()
        for plugin in ('pyright-lsp', 'typescript-lsp', 'pr-review-toolkit'):
            self.assertIs(data['enabledPlugins'].get(f'{plugin}@claude-plugins-official'), True, plugin)
        deny = data['permissions']['deny']
        self.assertIn('Read(//srv/containerlab-node-manager/data/state.key)', deny)
        self.assertIn('Read(//srv/containerlab-node-manager/data/state.enc)', deny)

    def test_guard_hook_registration(self):
        data = settings()
        entries = data['hooks']['PreToolUse']
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['matcher'], 'Bash')
        self.assertEqual(len(entries[0]['hooks']), 1)
        hook = entries[0]['hooks'][0]
        self.assertEqual(hook['type'], 'command')
        self.assertEqual(hook['command'], '${CLAUDE_PROJECT_DIR}/.claude/hooks/guard-bash.py')
        self.assertEqual(hook['args'], [])
        self.assertEqual(hook['onFailure'], 'block')
        script = CLAUDE / 'hooks' / 'guard-bash.py'
        self.assertTrue(script.is_file())
        self.assertTrue(os.access(script, os.X_OK), 'the hook must be executable (Git keeps the bit)')
        self.assertTrue(read(script).startswith('#!/usr/bin/env python3\n'))

    def test_worktrees_start_from_head(self):
        self.assertEqual(settings()['worktree']['baseRef'], 'head')

    def test_machine_local_files_are_ignored(self):
        lines = {line.strip() for line in read(ROOT / '.gitignore').split('\n')}
        for entry in ('.claude/settings.local.json', '.claude/worker.local.json', '.claude/worktrees/',
                      '.claude/agent-memory-local/'):
            self.assertIn(entry, lines)


# ---------------------------------------------------------------------------------------------------------
# Vendored skills (checks 17 to 19)
# ---------------------------------------------------------------------------------------------------------

class VendoredSkills(unittest.TestCase):
    @staticmethod
    def lock():
        return json.loads(read(CLAUDE / 'external-skills.lock.json'))['skills']

    def test_lockfile_matches_the_folders(self):
        entries = self.lock()
        self.assertTrue(entries)
        for entry in entries:
            name = entry['name']
            with self.subTest(skill=name):
                directory = CLAUDE / 'skills' / name
                self.assertTrue(directory.is_dir(), f'{name} is in the lockfile but not under .claude/skills')
                self.assertEqual(tree_hash(directory), entry['sha256'],
                                 f'{name} differs from the locked copy: a vendored skill is never edited in place')

    def test_every_vendored_skill_carries_its_licence(self):
        notes = read(CLAUDE / 'THIRD-PARTY-SKILLS.md').split('\n')
        for entry in self.lock():
            name = entry['name']
            with self.subTest(skill=name):
                directory = CLAUDE / 'skills' / name
                if (directory / 'LICENSE.txt').is_file() or (directory / '_upstream_licenses' / 'LICENSE').is_file():
                    continue
                rows = [line for line in notes if line.startswith('|') and f'`{name}`' in line]
                self.assertTrue(any('MIT' in row or 'Apache' in row for row in rows),
                                f'{name} has no licence file and no MIT or Apache row in THIRD-PARTY-SKILLS.md')

    def test_names_do_not_collide_and_the_set_equals_the_lockfile(self):
        locked = [entry['name'] for entry in self.lock()]
        self.assertEqual(len(locked), len(set(locked)))
        for name in locked:
            self.assertFalse(name.startswith('clab-'), f'{name} collides with the project skill namespace')
        folders = {path.name for path in (CLAUDE / 'skills').iterdir() if path.is_dir() and not path.name.startswith('clab-')}
        self.assertEqual(folders, set(locked))


# ---------------------------------------------------------------------------------------------------------
# The guard hook (checks 20 and 21)
# ---------------------------------------------------------------------------------------------------------

REFUSED = [
    'git push --force origin main', 'git push -f', 'git push origin +main', 'git push origin :old',
    'git push --tags', 'git push origin tag v1', 'sudo git push --force-with-lease', 'sudo -u archtop git push -f',
    'env -u FOO git push --force', 'timeout -k 5 30 git push --force', 'nice -n 10 git push -f',
    'git status\ngit push --force', 'git push \\\n  --force', 'git push --force\n', 'sudo rm -rf /srv/containerlab-node-manager',
    'rm -rf /srv/containerlab-node-manager/*', 'cd /srv/containerlab-node-manager/data && rm -rf ./*', 'rm -rf /srv',
    'docker image push x', 'docker compose push', 'docker build --push -t x .', 'docker buildx bake --push',
    'docker -H tcp://h:2375 push x', 'docker --context prod system prune', "bash -lc 'git push -f'", 'sh -ec "git push --force"',
    '/usr/bin/sudo git push -f', "/bin/bash -c 'git push -f'", 'git checkout -- .', 'git checkout -f', 'git restore .',
    'git switch --discard-changes main', 'git push --del origin b', 'git push --tag', 'git push --mirr', 'git push --force-with',
    'gh pr merge 70 --admin', 'find /srv/containerlab-node-manager/data -delete',
    'rsync -a --delete /tmp/x/ /srv/containerlab-node-manager/data/', 'dd if=/dev/zero of=/srv/containerlab-node-manager/data/state.enc',
    'rm /home/archtop/state.key', 'mv /srv/containerlab-node-manager/data /tmp/away', "eval 'git push --force'",
    "bash -c 'git push --force'", 'FOO=1 timeout 30 git push -fu origin b', 'git tag v1.2.3',
    'git reset --hard HEAD~1', 'cd clab-backup-ui && git reset --hard', 'git clean -fd', 'git stash drop',
    'docker push x', 'docker system prune -af', 'docker image prune -a', 'docker compose down -v',
    'gh release create v1', 'rm -rf /srv/containerlab-node-manager/data',
    'sudo rm /srv/containerlab-node-manager/data/state.key', 'npm test && git push --force',
]
ALLOWED = [
    'git push origin main', 'git push -u origin feature', 'git tag -l', 'git tag -d v1',
    'git -C /tmp/scratch reset --hard', 'cd /tmp/scratch && git reset --hard', 'git clean -n', 'git stash pop',
    'docker image prune', 'docker compose down', 'gh pr create', 'rm -rf ./data',
    "grep -rn 'git push --force' docs/", "sed -i 's/--force//' x", 'git push origin HEAD:refs/heads/x',
    'git log --oneline | head', 'git status',
    'git clean -fdxn', 'gh pr merge 70 --squash', "find /srv/containerlab-node-manager/data -name '*.zip'",
    'rsync -a /srv/containerlab-node-manager/data/ /tmp/backup/', 'find . -name state.key', 'rm /tmp/fixture-abc/state.key',
    'rm clab-backup-ui/scratch/state.key', 'git tag 2>/dev/null', 'git tag > tags.txt', "cat > f <<'EOF'\ngit push --force\nEOF",
    'bash -c "cd /tmp/x && git reset --hard"', 'git checkout -- clab-backup-ui/app/main.py', 'git restore clab-backup-ui/app/main.py',
    'git checkout feature', 'git switch main', 'docker ps', 'docker compose up -d', 'git worktree add /tmp/wt HEAD', 'git branch -D old',
    'sudo -u archtop ls', 'dd if=/srv/containerlab-node-manager/data/state.enc of=/tmp/copy', 'python3 -c "print(\'git push --force\')"',
    'git push origin main 2>&1 | tail -1',
]
HOOK = CLAUDE / 'hooks' / 'guard-bash.py'


def load_hook():
    spec = importlib.util.spec_from_file_location('claude_guard_bash', HOOK)
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # importing must not leave a __pycache__ under the repository
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


class GuardHook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = load_hook()

    def test_refuses_the_forbidden_commands(self):
        for command in REFUSED:
            with self.subTest(command=command):
                reason = self.guard.decide(command, str(ROOT), str(ROOT))
                self.assertTrue(reason, 'must be refused')

    def test_allows_the_ordinary_commands(self):
        for command in ALLOWED:
            with self.subTest(command=command):
                self.assertIsNone(self.guard.decide(command, str(ROOT), str(ROOT)))

    def run_hook(self, payload):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(ROOT), PYTHONDONTWRITEBYTECODE='1')
        return subprocess.run([str(HOOK)], input=json.dumps(payload), capture_output=True, text=True,
                              env=env, cwd=str(ROOT), timeout=30)

    def test_short_tag_push_and_scratch_repositories(self):
        """A tag pushed by its short name is recognised against the local tags; a scratch repository elsewhere may tag."""
        import tempfile
        with tempfile.TemporaryDirectory() as scratch:
            git = ['git', '-C', scratch, '-c', 'user.email=t@example.com', '-c', 'user.name=t']
            subprocess.run(git + ['init', '-q'], check=True)
            subprocess.run(git + ['commit', '-q', '--allow-empty', '-m', 'x'], check=True)
            subprocess.run(git + ['tag', 'v9.9.9'], check=True)
            self.assertIsNotNone(self.guard.decide('git push origin v9.9.9', scratch, str(ROOT)))
            self.assertIsNone(self.guard.decide('git tag v1', scratch, str(ROOT)), 'tag creation outside the checkout is allowed')
            self.assertIsNone(self.guard.decide('git push origin v9.9.9', str(ROOT), str(ROOT)), 'a branch named like a tag the checkout lacks')

    def test_preloaded_skills_carry_no_paths(self):
        """A skill with `paths` is not preloadable (observed in the debug log), so no agent may list one."""
        for name in agents():
            for skill in as_list(agent_front(name).get('skills')):
                self.assertNotIn('paths', skill_front(skill), f'{name} preloads {skill}, which has paths and would be skipped')

    def test_protocol_deny_decision(self):
        done = self.run_hook({'tool_name': 'Bash', 'tool_input': {'command': 'git push --force'}, 'cwd': str(ROOT)})
        self.assertEqual(done.returncode, 0, done.stderr)
        output = json.loads(done.stdout)['hookSpecificOutput']
        self.assertEqual(output['permissionDecision'], 'deny')
        self.assertTrue(output['permissionDecisionReason'].strip())

    def test_protocol_refuses_input_that_is_not_json(self):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=str(ROOT), PYTHONDONTWRITEBYTECODE='1')
        done = subprocess.run([sys.executable, str(HOOK)], input='not json', capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=30)
        self.assertEqual(done.returncode, 2)
        self.assertIn('not JSON', done.stderr)

    def test_protocol_silence_for_allowed_commands_and_other_tools(self):
        allowed = self.run_hook({'tool_name': 'Bash', 'tool_input': {'command': 'git status'}, 'cwd': str(ROOT)})
        self.assertEqual((allowed.returncode, allowed.stdout.strip()), (0, ''), allowed.stderr)
        other = self.run_hook({'tool_name': 'Read', 'tool_input': {'file_path': 'x'}, 'cwd': str(ROOT)})
        self.assertEqual((other.returncode, other.stdout.strip()), (0, ''), other.stderr)


# ---------------------------------------------------------------------------------------------------------
# Workflows (check 22)
# ---------------------------------------------------------------------------------------------------------

class WorkflowFiles(unittest.TestCase):
    def test_exactly_the_three_workflows_with_a_meta_block(self):
        files = sorted(path.name for path in (CLAUDE / 'workflows').glob('*.js'))
        self.assertEqual(files, sorted(f'{name}.js' for name in WORKFLOWS))
        for name in sorted(WORKFLOWS):
            with self.subTest(workflow=name):
                text = read(CLAUDE / 'workflows' / f'{name}.js')
                self.assertTrue(text.startswith('export const meta = {'))
                self.assertIn(f"name: '{name}'", text)


if __name__ == '__main__':
    unittest.main()
