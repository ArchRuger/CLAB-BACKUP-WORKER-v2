#!/usr/bin/env python3
"""PreToolUse guard for the Bash tool: refuses the few commands this repository's rules forbid outright.

Registered in `.claude/settings.json` under `hooks.PreToolUse` (matcher `Bash`), so it runs before every Bash
command of the session and of every subagent, in every permission mode, `bypassPermissions` included.

The repository rules (`CLAUDE.md` "Rules", `.claude/rules/fable-opus-routing.md` "Standing rules") say: never
force-push, tag, publish an image or deploy unless asked; no destructive reset or stash cleanup of the checkout;
never delete the manager's data, `state.key` or backups. This hook turns the "never unless asked" part into a
refusal the model cannot talk itself past. When the owner does ask, the owner runs the command in a shell of
their own, outside the Bash tool; this hook sees only Bash tool calls.

Not a security boundary. It reads the command text Claude wrote and recognises the usual spellings: compound
commands, newlines and continuations, heredocs (their bodies are not commands), wrappers such as `sudo -u x`,
`env`, `timeout`, `nice`, `xargs`, the shells' `-c` (also `-lc`, `-ec`), `eval`, `cd` between subcommands, git's
`-C`, abbreviated long options of `git push`, and a push of a tag by its short name (checked against the local
tags). A program reached another way is not caught; the product's own protections, the VM helper boundary and
GitHub's branch protection remain the real limits.

Usage: the hook reads the PreToolUse JSON on stdin and prints a deny decision or nothing. `--check "<command>"`
prints the decision for one command and exits 1 when it would be refused (used by the tests and by hand).
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys

SEPARATORS = {'&&', '||', ';', ';;', '|', '|&', '&', '(', ')'}
WRAPPERS = {'sudo', 'doas', 'env', 'timeout', 'nice', 'nohup', 'time', 'command', 'builtin', 'stdbuf', 'xargs'}
# Wrapper options that consume the next token, so `sudo -u user git push -f` still reaches `git`.
WRAPPER_VALUE_OPTIONS = {
    'sudo': {'-u', '-g', '-C', '-D', '-h', '-p', '-U', '-T', '-r', '-t'},
    'doas': {'-u', '-C'},
    'env': {'-u', '-C', '-S', '--unset', '--chdir', '--split-string'},
    'timeout': {'-k', '-s', '--kill-after', '--signal'},
    'nice': {'-n', '--adjustment'},
    'stdbuf': {'-i', '-o', '-e', '--input', '--output', '--error'},
    'xargs': {'-n', '-P', '-I', '-d', '-a', '-E', '-L', '-s', '--max-args', '--max-procs', '--replace', '--delimiter', '--arg-file'},
}
SHELLS = {'bash', 'sh', 'zsh', 'dash', 'ksh'}
GIT_OPTIONS_WITH_VALUE = {'-C', '-c', '--git-dir', '--work-tree', '--namespace', '--exec-path', '--config-env'}
PUSH_FORCE = ('force', 'force-with-lease', 'force-if-includes', 'mirror', 'prune')
PUSH_DELETE = ('delete',)
PUSH_TAGS = ('tags', 'follow-tags')
PUSH_VALUE_OPTIONS = {'-o', '--push-option', '--receive-pack', '--exec', '--repo'}
TAG_LISTING = {'-l', '--list', '-d', '--delete', '-v', '--verify', '-n', '--contains', '--no-contains', '--points-at',
               '--merged', '--no-merged', '--sort', '--format', '--column', '-i', '--ignore-case'}
DOCKER_GLOBAL_VALUE_OPTIONS = {'-H', '--host', '-c', '--context', '--config', '-l', '--log-level', '--tlscacert', '--tlscert', '--tlskey'}
DATA_ROOT = '/srv/containerlab-node-manager'
STATE_FILES = ('state.key', 'state.enc')
DATA_COMMANDS = {'rm', 'shred', 'truncate', 'unlink', 'mv', 'find', 'rsync', 'dd'}
REDIRECT = re.compile(r'^(\d*>>?&?\d*|&>>?|<<?<?&?\d*|\d*<)$')
HEREDOC = re.compile(r"<<-?\s*(?:'([^']+)'|\"([^\"]+)\"|(\w+))")
HOW_TO_PROCEED = ('The repository rules forbid this unless the owner asks. If the owner asked, the owner runs the command '
                  'in a shell of their own, outside the Bash tool; the owner, not an agent, may change '
                  '.claude/settings.json. Hook: .claude/hooks/guard-bash.py.')
MESSAGES = {
    'force': 'force-push (or a mirror/prune push) is never done by the agent',
    'delete': 'deleting a remote branch or tag is never done by the agent',
    'tags': 'publishing tags is never done by the agent',
    'tag-create': 'creating a tag in the checkout is never done by the agent (a tag identifies a release)',
    'reset': 'a destructive reset of the checkout is never done by the agent',
    'clean': 'git clean of the checkout is never done by the agent',
    'stash': 'dropping stashes of the checkout is never done by the agent',
    'discard': 'discarding every uncommitted change of the checkout is never done by the agent',
    'image': 'publishing an image is never done by the agent',
    'prune': 'a blanket docker prune can remove lab images and volumes that are not re-pullable',
    'volumes': 'removing volumes can remove lab and capture data',
    'release': 'publishing or changing a GitHub release is never done by the agent',
    'repo-delete': 'deleting a repository is never done by the agent',
    'admin-merge': 'bypassing branch protection is never done by the agent',
    'data': 'the manager data directory, state.key and state.enc are never deleted or moved to solve a problem',
}


# ----------------------------------------------------------------------------- text to simple commands

def without_heredocs(command: str) -> str:
    """Drop heredoc bodies: text fed to a command is not a command of its own."""
    out: list[str] = []
    terminator = None
    for line in command.split('\n'):
        if terminator is not None:
            if line.strip() == terminator:
                terminator = None
            continue
        out.append(line)
        match = HEREDOC.search(line)
        if match:
            terminator = match.group(1) or match.group(2) or match.group(3)
    return '\n'.join(out)


def normalise(command: str) -> str:
    """Heredoc bodies removed, continuations joined, newlines made explicit separators."""
    text = without_heredocs(command.replace('\r\n', '\n'))
    text = text.replace('\\\n', ' ')
    return text.replace('\n', ' ; ')


def tokenize(text: str) -> list[str]:
    """Shell tokens with operators as separate tokens; falls back to whitespace on unbalanced quotes."""
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ''
    try:
        raw = list(lexer)
    except ValueError:
        raw = text.split()
    out: list[str] = []
    for token in raw:
        if token == '':
            continue
        if token.strip('&|;()<>') == '':
            piece = ''
            for char in token:
                if piece and (piece + char) not in SEPARATORS and not REDIRECT.match(piece + char):
                    out.append(piece)
                    piece = ''
                piece += char
            if piece:
                out.append(piece)
        else:
            out.append(token)
    return out


def segments(command: str) -> list[list[str]]:
    """The simple commands of a command line, each as its token list, operators and redirections removed."""
    result: list[list[str]] = []
    current: list[str] = []
    tokens = tokenize(normalise(command))
    skip = False
    for index, token in enumerate(tokens):
        if skip:
            skip = False
            continue
        if token in SEPARATORS:
            if current:
                result.append(current)
            current = []
            continue
        if token.isdigit() and index + 1 < len(tokens) and tokens[index + 1].startswith(('<', '>')):
            continue  # the fd number of a redirection; the operator follows
        if REDIRECT.match(token) and token.startswith(('<', '>', '&')):
            skip = True  # the redirection's target (a file name or an fd) is not an argument
            continue
        current.append(token)
    if current:
        result.append(current)
    return result


def strip_wrappers(tokens: list[str]):
    """Return ('command', tokens) with leading assignments and wrappers removed, or ('shell', inner_text)."""
    tokens = list(tokens)
    while tokens:
        head = os.path.basename(tokens[0])
        if '=' in tokens[0] and not tokens[0].startswith('-') and tokens[0].split('=', 1)[0].replace('_', '').isalnum():
            tokens.pop(0)
            continue
        if head in WRAPPERS:
            tokens.pop(0)
            valued = WRAPPER_VALUE_OPTIONS.get(head, set())
            while tokens and tokens[0].startswith('-'):
                option = tokens.pop(0)
                if option in valued and tokens:
                    tokens.pop(0)
            if head == 'timeout' and tokens:
                tokens.pop(0)  # the duration
            continue
        if head in SHELLS:
            for index, token in enumerate(tokens[1:], start=1):
                if token.startswith('-') and not token.startswith('--') and 'c' in token[1:]:
                    return ('shell', tokens[index + 1] if index + 1 < len(tokens) else '')
                if not token.startswith('-'):
                    break
            return ('command', tokens)
        if head == 'eval':
            return ('shell', ' '.join(tokens[1:]))
        break
    return ('command', tokens)


# ----------------------------------------------------------------------------- the rules

def inside(path: str, root: str) -> bool:
    try:
        return os.path.commonpath([os.path.realpath(path), os.path.realpath(root)]) == os.path.realpath(root)
    except ValueError:
        return False


def names_local_tag(name: str, repo_dir: str) -> bool:
    """True when `name` is an existing tag of the repository at `repo_dir` (a tag pushed by its short name)."""
    if not name or name.startswith('-') or ('/' in name and not name.startswith('refs/')):
        return False
    try:
        result = subprocess.run(['git', '-C', repo_dir, 'tag', '--list', name], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0 and result.stdout.strip() != ''


def long_option(arg: str, names: tuple) -> bool:
    """True when `arg` is `--name`, `--name=value` or an unambiguous abbreviation (4+ characters) of one of names."""
    if not arg.startswith('--'):
        return False
    stem = arg[2:].split('=', 1)[0]
    if stem in names:
        return True
    return len(stem) >= 2 and len(arg) >= 4 and any(name.startswith(stem) for name in names)


def git_reason(args: list[str], cwd: str, project: str) -> str | None:
    target = cwd
    index = 0
    while index < len(args) and args[index].startswith('-'):
        option = args[index]
        if option in GIT_OPTIONS_WITH_VALUE and index + 1 < len(args):
            if option == '-C':
                target = os.path.join(target, os.path.expanduser(args[index + 1]))
            index += 2
            continue
        index += 1
    if index >= len(args):
        return None
    sub, rest = args[index], args[index + 1:]
    on_checkout = inside(target, project)
    if sub == 'push':
        skip_next = False
        for arg in rest:
            if skip_next:
                skip_next = False
                continue
            if arg in PUSH_VALUE_OPTIONS:
                skip_next = True
                continue
            if long_option(arg, PUSH_FORCE):
                return MESSAGES['force']
            if long_option(arg, PUSH_DELETE):
                return MESSAGES['delete']
            if long_option(arg, PUSH_TAGS):
                return MESSAGES['tags']
            if arg.startswith('-') and not arg.startswith('--'):
                flags = arg[1:]
                if 'f' in flags:
                    return MESSAGES['force']
                if 'd' in flags:
                    return MESSAGES['delete']
                continue
            if arg.startswith('--'):
                continue
            if arg.startswith('+'):
                return MESSAGES['force']
            if arg.startswith(':'):
                return MESSAGES['delete']
            if 'refs/tags/' in arg or arg == 'tag':
                return MESSAGES['tags']
            if names_local_tag(arg.split(':', 1)[0], target):
                return MESSAGES['tags']
        return None
    if not on_checkout:
        return None
    if sub == 'tag':
        if any(arg in TAG_LISTING or arg.startswith(('-n', '--sort=', '--format=', '--contains=', '--points-at=')) for arg in rest):
            return None
        if any(not arg.startswith('-') for arg in rest):
            return MESSAGES['tag-create']
        return None
    if sub == 'reset' and '--hard' in rest:
        return MESSAGES['reset']
    if sub == 'clean':
        forced = any(arg == '--force' or (arg.startswith('-') and not arg.startswith('--') and 'f' in arg[1:]) for arg in rest)
        dry = '--dry-run' in rest or any(arg.startswith('-') and not arg.startswith('--') and 'n' in arg[1:] for arg in rest)
        return None if not forced or dry else MESSAGES['clean']
    if sub == 'stash' and rest and rest[0] in ('drop', 'clear'):
        return MESSAGES['stash']
    whole_tree = {'.', ':/', '*', ':/.'}
    if sub in ('checkout', 'restore', 'switch'):
        positional = [arg for arg in rest if not arg.startswith('-') and arg != '--']
        if sub == 'checkout' and ('-f' in rest or '--force' in rest) and not positional:
            return MESSAGES['discard']
        if sub == 'switch' and '--discard-changes' in rest:
            return MESSAGES['discard']
        if sub in ('checkout', 'restore') and '--' in rest or sub == 'restore':
            if any(arg in whole_tree for arg in positional):
                return MESSAGES['discard']
    return None


def docker_reason(args: list[str]) -> str | None:
    words: list[str] = []
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg in DOCKER_GLOBAL_VALUE_OPTIONS and not words:
            skip = True
            continue
        if not arg.startswith('-'):
            words.append(arg)
    if not words:
        return None
    if words[0] == 'push' or words[:2] in (['image', 'push'], ['compose', 'push']):
        return MESSAGES['image']
    if '--push' in args and (words[0] == 'build' or (words[0] == 'buildx' and words[1:2] and words[1] in ('build', 'bake'))):
        return MESSAGES['image']
    if words[:2] == ['system', 'prune']:
        return MESSAGES['prune']
    if words[:2] == ['volume', 'prune']:
        return MESSAGES['volumes']
    if words[:2] == ['image', 'prune'] and ('-a' in args or '--all' in args):
        return 'pruning all images can remove proprietary NOS images that are not re-pullable'
    if words[0] == 'compose' and 'down' in words and ('-v' in args or '--volumes' in args):
        return 'docker compose down with volumes removes persistent data; the project scripts do this deliberately'
    return None


def gh_reason(args: list[str]) -> str | None:
    words = [arg for arg in args if not arg.startswith('-')]
    if words[:1] == ['release'] and words[1:2] and words[1] in ('create', 'upload', 'edit', 'delete'):
        return MESSAGES['release']
    if words[:2] == ['repo', 'delete']:
        return MESSAGES['repo-delete']
    if words[:2] == ['pr', 'merge'] and '--admin' in args:
        return MESSAGES['admin-merge']
    return None


def touches_data(arg: str, cwd: str, project: str) -> bool:
    expanded = os.path.expanduser(arg)
    if expanded.startswith('-') or expanded in ('.', '..'):
        return False
    absolute = os.path.normpath(os.path.join(cwd, expanded))
    # a glob keeps its literal prefix: `/srv/containerlab-node-manager/*` still names the directory
    prefix = re.split(r'[*?\[]', absolute, 1)[0]
    if prefix == DATA_ROOT or prefix.startswith(DATA_ROOT + '/') or DATA_ROOT.startswith(prefix.rstrip('/') + '/') and prefix.rstrip('/') != '':
        return True
    if absolute.endswith(STATE_FILES):
        scratch = absolute.startswith(('/tmp/', '/var/tmp/')) or inside(absolute, project)
        return not scratch
    return False


def data_reason(name: str, args: list[str], cwd: str, project: str) -> str | None:
    if name not in DATA_COMMANDS:
        return None
    if name == 'find' and not any(arg in ('-delete', '-exec', '-execdir', '-ok', '-okdir', '-fprint', '-fprintf', '-fls') for arg in args):
        return None  # a read-only find
    if name == 'rsync' and not any(arg.startswith('--delete') or arg == '--remove-source-files' for arg in args):
        return None  # copying data out is allowed; deleting at either end is not
    if name == 'dd':
        args = [arg[3:] for arg in args if arg.startswith('of=')]
    if name == 'rsync':
        args = [arg for arg in args if not arg.startswith('--')]
    for arg in args:
        if touches_data(arg, cwd, project):
            return MESSAGES['data']
    return None


# ----------------------------------------------------------------------------- the decision

def check(command: str, cwd: str, project: str, depth: int = 0) -> str | None:
    if depth > 8:
        return 'the command nests shells too deeply to be read'
    for raw in segments(command):
        if not raw:
            continue
        if raw[0] == 'cd':
            cwd = os.path.normpath(os.path.join(cwd, os.path.expanduser(raw[1]))) if len(raw) > 1 else os.path.expanduser('~')
            continue
        kind, payload = strip_wrappers(raw)
        if kind == 'shell':
            reason = check(payload, cwd, project, depth + 1)
            if reason:
                return reason
            continue
        tokens = payload
        if not tokens:
            continue
        name = os.path.basename(tokens[0])
        args = tokens[1:]
        if name == 'git':
            reason = git_reason(args, cwd, project)
        elif name in ('docker', 'podman'):
            reason = docker_reason(args)
        elif name == 'docker-compose':
            reason = docker_reason(['compose', *args])
        elif name == 'gh':
            reason = gh_reason(args)
        else:
            reason = data_reason(name, args, cwd, project)
        if reason:
            return f'Refused: {reason}. Command: {" ".join(tokens)}. {HOW_TO_PROCEED}'
    return None


def decide(command: str, cwd: str, project: str) -> str | None:
    """The reason to refuse `command`, or None."""
    return check(command, cwd, project)


def main(argv: list[str]) -> int:
    project = os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd()
    if len(argv) >= 2 and argv[0] == '--check':
        reason = decide(argv[1], os.getcwd(), project)
        print(reason or 'allowed')
        return 1 if reason else 0
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError):
        print('guard-bash.py: the hook input was not JSON; refusing the call rather than guessing', file=sys.stderr)
        return 2
    if payload.get('tool_name') != 'Bash':
        return 0
    command = (payload.get('tool_input') or {}).get('command') or ''
    cwd = payload.get('cwd') or os.getcwd()
    reason = decide(command, cwd, project)
    if reason:
        json.dump({'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                          'permissionDecisionReason': reason}}, sys.stdout)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
