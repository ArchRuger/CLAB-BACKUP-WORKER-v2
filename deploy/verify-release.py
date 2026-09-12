"""Check release metadata without importing application code or contacting the VM."""
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
    # Footer fallback shown before the first /api/state response arrives.
    'clab-backup-ui/app/static/app.js': r"state\.version\|\|'([^']+)'",
}
for name in ('index.html', 'terminal.html', 'workspace.html', 'vm-connection.html', 'debug.html'):
    FIELDS['clab-backup-ui/app/static/' + name] = r'/static/[^"\s?]+\?v=([^"\s]+)'


def verify(root):
    version = (root / 'clab-backup-ui/VERSION').read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('clab-backup-ui/VERSION must contain one numeric release, such as 1.15.1.')
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


if __name__ == '__main__':
    root = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else Path(__file__).resolve().parents[1]
    try:
        print('Source release verified: ' + verify(root))
    except (OSError, ValueError) as error:
        sys.exit(str(error))
