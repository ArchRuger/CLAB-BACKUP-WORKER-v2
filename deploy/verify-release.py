"""Check release metadata without importing application code or contacting the VM.

Two checks live here.

``verify(root)`` is the runtime lockstep check: every file that carries the release number
(the application, the VM helpers, the image label, the Compose image tags and the versioned
static assets) must agree with ``clab-backup-ui/VERSION``. The VM scripts run it with
``--runtime`` before touching the host.

``verify_docs(root)`` keeps the documentation honest. The living guides may name the manager's
release only where they mean the current one; a versioned source folder (``~/projects/v1.x.y``)
or image tag (``clab-backup:1.x.y``) is refused outright, and the README, the changelog, the
validation record and the handoff notes must lead with the current release. Release history is
written as ``since 1.19.3`` or ``1.22.0 or later``, which is allowed anywhere; the history files
(``docs/CHANGELOG.md``, ``clab-backup-ui/VALIDATION.md``, ``agent instructions.md``),
``docs/archive/`` and the design notes under ``docs/redesign/`` may name any release. A third-party version that shares the manager's major
number (the Flow panel, for example) is recognised by the component name before it.

``python3 deploy/verify-release.py`` runs both checks (CI does the same);
``python3 deploy/set-release.py NEW`` moves every marker to the next release.
"""
from pathlib import Path
import re
import sys


FIELDS = {
    'clab-backup-ui/app/__init__.py': r'__version__\s*=\s*[\'"]([^\'"]+)[\'"]',
    'clab-backup-ui/app/host_files.py': r'[\'"]helper_version[\'"]\s*:\s*[\'"]([^\'"]+)[\'"]',
    'clab-backup-ui/app/host_operations.py': r'^VERSION\s*=\s*[\'"]([^\'"]+)[\'"]',
    'clab-backup-ui/app/host_git.py': r'^VERSION\s*=\s*[\'"]([^\'"]+)[\'"]',
    'clab-backup-ui/Dockerfile': r'org\.opencontainers\.image\.version="([^"]+)"',
    'clab-backup-ui/compose.yml': r'^\s+image:\s+clab-backup:([^\s]+)',
    'deploy/compose.capture.yml': r'^\s+image:\s+clab-capture-service:([^\s]+)',
    # Footer fallback shown before the first /api/state response arrives.
    'clab-backup-ui/app/static/app.js': r"state\.version\|\|'([^']+)'",
}
for name in ('index.html', 'terminal.html', 'workspace.html', 'vm-connection.html', 'debug.html', 'capture-setup.html', 'capture-session.html', 'grafana.html'):
    FIELDS['clab-backup-ui/app/static/' + name] = r'/static/[^"\s?]+\?v=([^"\s]+)'

# Living documentation: what a user or an agent reads for the current release.
DOC_ROOTS = ('README.md', 'docs', 'deploy', 'clab-backup-ui/README.md', 'clab-backup-ui/NODE-FEATURES.md',
             'clab-backup-ui/app/static/vm-connection.html', 'clab-backup-ui/app/static/capture-setup.html')
# Release history: may name any release.
HISTORY_FILES = ('docs/CHANGELOG.md', 'clab-backup-ui/VALIDATION.md', 'agent instructions.md')
HISTORY_DIRS = ('docs/archive/', 'docs/redesign/')
# Where the current release must be named first, and how.
LEADS = {
    'README.md': r'Current release: \*\*(\d+\.\d+\.\d+)\*\*',
    'docs/CHANGELOG.md': r'^## Changes in (\d+\.\d+\.\d+)',
    'clab-backup-ui/VALIDATION.md': r'^# .*?(\d+\.\d+\.\d+)\s*$',
    'agent instructions.md': r'^# .*?(\d+\.\d+\.\d+)\s*$',
}
# A release number: not part of a longer dotted sequence (an IP address) or of a word ("v1.2.3",
# "4.35.0F"); a sentence-ending full stop after it is fine.
TOKEN = re.compile(r'(?<![\w.])(\d+)\.(\d+)\.(\d+)(?!\w|\.\d)')
HISTORY_BEFORE = re.compile(r'(?:since|before|until|introduced in|added in|new in|as of|upgrading from|prior to|'
                            r'older than|earlier than|newer than|later than)\s*\**$', re.I)
HISTORY_AFTER = re.compile(r'^\**\s+(?:or|and)\s+(?:later|earlier|newer|older)\b', re.I)
# A component whose own version can share the manager's major number, named shortly before it,
# or the file name of an archived guide (docs/archive/UI-UPDATE-1.12.1.md) in a link.
THIRD_PARTY = re.compile(r'(?:flow[- ]panel|andrewbmchugh|xterm|addon-fit|novnc|packetflix|edgeshark|gostwire|ghostwire|'
                         r'pygnmi|grpcio|protobuf|dictdiffer|paramiko|websockify|cshargextcap|plugin|archive/)[^\n]{0,40}$', re.I)
VERSIONED_PATH = re.compile(r'projects/v\d+\.\d+\.\d+')
VERSIONED_IMAGE = re.compile(r'clab-(?:backup|capture-service):\d+\.\d+\.\d+')


def read_version(root):
    version = (root / 'clab-backup-ui/VERSION').read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('clab-backup-ui/VERSION must contain one numeric release, such as 1.15.1.')
    return version


def verify(root):
    version = read_version(root)
    problems = []
    for name, pattern in FIELDS.items():
        values = re.findall(pattern, (root / name).read_text(encoding='utf-8'), re.MULTILINE)
        if not values:
            problems.append(name + ': missing release metadata')
        elif any(value != version for value in values):
            safe = sorted({v if re.fullmatch(r'\d+\.\d+\.\d+', v) else '(invalid)' for v in values})
            problems.append(name + ': found ' + ', '.join(safe))
    if problems:
        raise ValueError('Mixed release files: clab-backup-ui/VERSION expects ' + version + '\n  '
                         + '\n  '.join(problems) + '\nObtain a complete matching source release before running setup.')
    return version


def living_docs(root):
    """(relative path, Path) of every living documentation file under DOC_ROOTS."""
    for entry in DOC_ROOTS:
        path = root / entry
        files = sorted(path.rglob('*.md')) if path.is_dir() else [path] if path.is_file() else []
        for file in files:
            rel = file.relative_to(root).as_posix()
            if rel in HISTORY_FILES or rel.startswith(HISTORY_DIRS):
                continue
            yield rel, file


def release_tokens(text, current):
    """Every token that looks like a manager release: (line number, start, end, token, kind).

    kind is 'current' (names this release), 'history' ("since x", "x or later"),
    'third-party' (a named component's own version) or 'stale' (another release named
    as if it were the current one). Lines are split on '\\n' so positions apply to
    ``text.split('\\n')`` unchanged.
    """
    major = current.split('.')[0]
    for number, line in enumerate(text.split('\n'), 1):
        for match in TOKEN.finditer(line):
            if match.group(1) != major:
                continue
            before, after, token = line[:match.start()], line[match.end():], match.group(0)
            if THIRD_PARTY.search(before):
                kind = 'third-party'
            elif HISTORY_BEFORE.search(before) or HISTORY_AFTER.match(after):
                kind = 'history'
            elif token == current:
                kind = 'current'
            else:
                kind = 'stale'
            yield number, match.start(), match.end(), token, kind


def verify_docs(root):
    version = read_version(root)
    problems = []
    for rel, path in living_docs(root):
        text = path.read_bytes().decode('utf-8')
        for number, _start, _end, token, kind in release_tokens(text, version):
            if kind == 'stale':
                problems.append(f'{rel}:{number}: names release {token}, but this checkout is {version}. Drop the number, '
                                f'write it as history ("since {token}", "{token} or later"), or name the component before a third-party version.')
        for number, line in enumerate(text.split('\n'), 1):
            if VERSIONED_PATH.search(line):
                problems.append(f'{rel}:{number}: versioned source folder; the guides use ~/projects/clab-manager')
            if VERSIONED_IMAGE.search(line):
                problems.append(f'{rel}:{number}: versioned image tag; refer to the release in clab-backup-ui/VERSION instead')
    for rel, pattern in LEADS.items():
        match = re.search(pattern, (root / rel).read_bytes().decode('utf-8'), re.MULTILINE)
        if not match:
            problems.append(f'{rel}: no release heading found')
        elif match.group(1) != version:
            problems.append(f'{rel}: leads with {match.group(1)}; add the {version} section at the top')
    if problems:
        raise ValueError(f'Documentation disagrees with clab-backup-ui/VERSION ({version}):\n  ' + '\n  '.join(problems)
                         + '\nMove every marker with python3 deploy/set-release.py NEW, then write the release sections by hand.')
    return version


def main(argv):
    options = [a for a in argv if a.startswith('--')]
    roots = [a for a in argv if not a.startswith('--')]
    if len(roots) > 1 or any(o not in ('--runtime', '--docs') for o in options):
        sys.exit('Usage: verify-release.py [--runtime | --docs] [SOURCE_ROOT]')
    root = Path(roots[0]).resolve() if roots else Path(__file__).resolve().parents[1]
    try:
        if '--docs' not in options:
            print('Source release verified: ' + verify(root))
        if '--runtime' not in options:
            print('Documentation names only release ' + verify_docs(root) + '.')
    except (OSError, ValueError) as error:
        sys.exit(str(error))


if __name__ == '__main__':
    main(sys.argv[1:])
