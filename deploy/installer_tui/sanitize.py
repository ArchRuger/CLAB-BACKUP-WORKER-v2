"""Turn external command output into inert display text (standard library only).

Helper output is data, never markup or terminal control: every escape sequence,
C0/C1 control character and bidirectional override is removed before a line
reaches the screen, a carriage-return progress line keeps only its final state,
and an over-long line is cut with an explicit marker. A small scrubber blanks
token- and password-shaped values as a second line of defence; the helpers do not
print secrets on the piped path, and nothing here is persisted.
"""
import re

MAX_LINE = 2000

# CSI (ESC [ ... final), OSC (ESC ] ... BEL/ST), DCS/SOS/PM/APC (ESC P|X|^|_ ... ST),
# two-character escapes, and their 8-bit C1 equivalents.
_ESCAPES = re.compile(
    r'\x1b\[[0-?]*[ -/]*[@-~]'
    r'|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?'
    r'|\x1b[PX^_][^\x1b]*(?:\x1b\\)?'
    r'|\x1b[ -/]*[0-~]'
    r'|\x9b[0-?]*[ -/]*[@-~]'
    r'|\x9d[^\x07\x9c]*(?:\x07|\x9c)?'
    r'|[\x90\x98\x9e\x9f][^\x9c]*\x9c?')
# Remaining C0 (except tab), DEL, C1, and Unicode bidi/format overrides that can
# make a line render differently from its bytes.
_CONTROLS = re.compile('[\x00-\x08\x0a-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩﻿]')
_SECRETS = [
    (re.compile(r'\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b'), '[token removed]'),
    (re.compile(r'(?i)\b(password|passwd|secret|token|api[_-]?key)(\s*[=:]\s*)(\S+)'), r'\1\2[removed]'),
    (re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----.*'), '[private key removed]'),
]


def clean_line(text, limit=MAX_LINE):
    """One display line from one raw output line (no trailing newline)."""
    text = text.rstrip('\n')
    # A progress meter rewrites its line with CR; keep what the terminal would show last.
    if '\r' in text:
        parts = [part for part in text.split('\r') if part.strip()]
        text = parts[-1] if parts else ''
    text = _ESCAPES.sub('', text)
    text = text.replace('\x1b', '')
    text = _CONTROLS.sub('', text.expandtabs(4))
    for pattern, replacement in _SECRETS:
        text = pattern.sub(replacement, text)
    if len(text) > limit:
        text = text[:limit] + f' [... {len(text) - limit} more characters not shown]'
    return text


def decode(data):
    """Bytes from a pipe to text; invalid UTF-8 never raises."""
    return data.decode('utf-8', 'replace')
