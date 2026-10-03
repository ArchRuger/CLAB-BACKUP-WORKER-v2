"""Line-level unified diffs for saved configuration text, stdlib only (difflib).

`unified()` never normalises whitespace and never reorders lines: two texts that differ only in
line order come back as a deletion plus an addition, exactly as `difflib` sees them. It is used by
the Git compare route (`app/git_progress.py`) so the review before an upload, and every "Compared
with…" view, shows the same real diff instead of two independent panes.
"""
import difflib

MAX_LINE_LEN = 4000


def _lines(text):
    # Split on '\n' only (not `splitlines()`, which also treats a bare '\r' or '\r\n' as its own
    # line boundary and discards it): a line's own '\r' stays part of its text, so a file whose line
    # endings changed from LF to CRLF is never reported as unchanged.
    return text.split('\n')


def _row(row, line):
    # Lines are compared in full; only the displayed text is cut. A cut row says so (additive field).
    row['text'] = line[:MAX_LINE_LEN]
    if len(line) > MAX_LINE_LEN: row['shortened'] = True
    return row


def unified(before, after, context=3, max_lines=20000):
    """A unified diff of `before` and `after` as a plain-data dict (see module docstring for shape:
    `hunks`, each a list of `{type, old, new, text}` rows; `added`, `removed`, `truncated`,
    `identical`). Oversized or binary-looking input is reported truncated rather than raising: the
    caller always gets a dict back.

    `identical` is True only when the two whole texts are equal. When the line cap cut the comparison
    short, `truncated` is True and `note` says so in plain words, even when the shown lines match (the
    difference then lies past the cap and no hunk can show it); `counts_partial: True` (additive) then
    says that `added`/`removed` cover only the part compared. A caller that cuts only the list it sends
    after counting (restore.review_diff below this function's own cap) sets `truncated` without it, and
    diff-view.js words the two apart. restore.review_diff does not pass the flag on yet, so a text past
    this cap reads there with the neutral wording although its counts cover the cut text. A row whose line was cut to
    MAX_LINE_LEN for display carries `shortened: True` (lines are always compared in full, so a change
    may lie in the part not shown; diff-view.js says so)."""
    before = before or ''
    after = after or ''
    if '\x00' in before or '\x00' in after:
        return {'hunks': [], 'added': 0, 'removed': 0, 'truncated': True, 'identical': False,
                'note': 'Binary content is not shown as a line diff.'}
    if before == after:
        return {'hunks': [], 'added': 0, 'removed': 0, 'truncated': False, 'identical': True}
    before_lines = _lines(before)
    after_lines = _lines(after)
    truncated = False
    if len(before_lines) > max_lines or len(after_lines) > max_lines:
        truncated = True
        before_lines = before_lines[:max_lines]
        after_lines = after_lines[:max_lines]
    if before_lines == after_lines:
        # The texts differ (checked above), so the difference lies past the cap: never call this identical.
        return {'hunks': [], 'added': 0, 'removed': 0, 'truncated': True, 'identical': False, 'counts_partial': True,
                'note': f'This file is too long to compare in full: its first {max_lines} lines are the same, and it changes after that point. Those changes are not shown here.'}
    matcher = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    hunks = []
    added = 0
    removed = 0
    groups = matcher.get_grouped_opcodes(context)
    for group in groups:
        first_tag, first_i1, first_i2, first_j1, first_j2 = group[0]
        last_tag, last_i1, last_i2, last_j1, last_j2 = group[-1]
        old_start = first_i1 + 1 if first_i2 > first_i1 else first_i1
        new_start = first_j1 + 1 if first_j2 > first_j1 else first_j1
        old_count = last_i2 - first_i1
        new_count = last_j2 - first_j1
        rows = []
        for tag, i1, i2, j1, j2 in group:
            if tag == 'equal':
                for offset, line in enumerate(before_lines[i1:i2]):
                    rows.append(_row({'type': 'context', 'old': i1 + offset + 1, 'new': j1 + offset + 1}, line))
                continue
            if tag in ('delete', 'replace'):
                for offset, line in enumerate(before_lines[i1:i2]):
                    rows.append(_row({'type': 'del', 'old': i1 + offset + 1, 'new': None}, line))
                    removed += 1
            if tag in ('insert', 'replace'):
                for offset, line in enumerate(after_lines[j1:j2]):
                    rows.append(_row({'type': 'add', 'old': None, 'new': j1 + offset + 1}, line))
                    added += 1
        hunks.append({'old_start': old_start, 'old_count': old_count, 'new_start': new_start,
                      'new_count': new_count, 'lines': rows})
    result = {'hunks': hunks, 'added': added, 'removed': removed, 'truncated': truncated, 'identical': False}
    if truncated:
        result['counts_partial'] = True
        result['note'] = f'Only the first {max_lines} lines of each version were compared; changes after that point are not shown.'
    return result
