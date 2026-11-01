"""`python -m app.recover`: recovery of a lost administrator password (sign-on DESIGN.md 9.5).

Run inside the container by deploy/manager-recover-admin.sh as the container user. It writes a
`mode=recover` setup-code file (valid for 15 minutes), appends `recover.requested` to audit.jsonl without
constructing a Store, and prints the code and its validity to the operator's terminal and nothing else:
no URL (the script builds it from .env), never a log line with the code. It never opens state.enc, never
changes or deletes a user. In setup mode it refuses: the setup code already in the file is the way in.
"""
import os
import sys
from pathlib import Path

from . import accounts
from .store import Store

SETUP_SENTENCE = 'The manager is in setup mode: use the setup code in {root}/setup-code.'
VALID_SENTENCE = 'Valid for 15 minutes. Create one new administrator on the setup page; existing accounts are not changed.'
AUDIT_WARNING = 'The audit log could not be written; check manager storage permissions and free space.'


def setup_file_present(path):
    """True when the file's first line says `mode=setup`, whatever its mode bits: a setup code is never replaced."""
    try: fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError: return False
    try: first = os.read(fd, 256).split(b'\n', 1)[0].strip()
    except OSError: return False
    finally: os.close(fd)
    return first == b'mode=setup'


def audit(root, event, err):
    try: Store.append_audit(root, Store.audit_entry(event, actor='-', source='-', outcome='ok'))
    except OSError: print(AUDIT_WARNING, file=err)


def main(argv=None, root=None, out=None, err=None):
    out = sys.stdout if out is None else out
    err = sys.stderr if err is None else err
    root = Path(root or os.environ.get('DATA_DIR', '/data'))
    if setup_file_present(root/accounts.SETUP_FILE):
        print(SETUP_SENTENCE.format(root=root), file=out)
        return 1
    accounts.read_setup_code(root, on_expired=lambda: audit(root, 'recover.expired', err))
    code = accounts.write_setup_code(root, 'recover')
    audit(root, 'recover.requested', err)
    print(f'Recovery code: {code}', file=out)
    print(VALID_SENTENCE, file=out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
