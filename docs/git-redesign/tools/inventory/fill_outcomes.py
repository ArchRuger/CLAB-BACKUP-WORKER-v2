#!/usr/bin/env python3
"""Write the decided "New outcome" cells of sections A to E (outcomes_ad.py) into REFUSALS.md and rebuild its
section 9 (counts, the F rows, findings, new refusals). Rerunnable: it replaces the last cell of each decided row
and everything from the line `## 9. New outcomes` to the end of the file; rows it has no decision for (section E)
are left as they are. `{at}` in a decision becomes today's `path:line` of the row's text in its own file, found
by match_refusals.match(). Standard library only.

  python3 docs/git-redesign/tools/inventory/fill_outcomes.py [--check]

--check writes nothing; it fails when a row of A to E has no decision or a decision names no line.
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import match_refusals as m          # noqa: E402
from outcomes_ad import OUT         # noqa: E402
from section9 import SECTION9       # noqa: E402

KINDS = ('Gone', 'Question', 'Reworded', 'Kept, not reachable', 'Kept')
CATS = ('F', 'S', 'X', 'V', 'O')


def short(location):
    return location.replace('clab-backup-ui/app/', 'app/')


def kind(cell):
    return next(k for k in KINDS if cell.startswith(k))


CODES = None


def cell_for(row):
    global CODES
    text = OUT[row['id']]
    if '{code}' in text:
        # The chip code the manager gives this sentence when a placement is refused (`problem_code`, read from today's tables).
        if CODES is None: CODES = m.problem_codes()
        text = text.replace('{code}', m.problem_code(row['text'].strip('`').replace('\\|', '|'), CODES))
    if '{at}' in text:
        own = row['at'].strip('`').split(':')[0]
        lines = [x for x in row['lines'] if x.split(':')[0] == own] if row['status'] in ('same', 'moved') else []
        if not lines: raise SystemExit(row['id'] + ': no line of its own file found; write it explicitly')
        path = short(lines[0].split(':')[0])
        # The location ends the cell, also when more text was appended after a template's `{at}`.
        text = text.replace(' {at}', '').replace('{at}', '').rstrip() + ' ' + path + ':' + ', '.join(x.split(':')[1] for x in lines[:3])
    return text.replace('|', '\\|')


def counts_table(decided):
    table = {c: {k: 0 for k in KINDS} for c in CATS}
    findings = {c: 0 for c in CATS}
    for row, cell in decided:
        table[row['cat']][kind(cell)] += 1
        findings[row['cat']] += 'FINDING' in cell
    head = '| Cat | ' + ' | '.join(KINDS) + ' | Total | of which FINDING |\n|' + '---|' * (len(KINDS) + 3)
    lines = [head]
    for c in CATS:
        lines.append('| ' + c + ' | ' + ' | '.join(str(table[c][k]) for k in KINDS) + ' | ' + str(sum(table[c].values())) + ' | ' + str(findings[c]) + ' |')
    lines.append('| **Total** | ' + ' | '.join('**' + str(sum(table[c][k] for c in CATS)) + '**' for k in KINDS) + ' | **' +
                 str(len(decided)) + '** | **' + str(sum(findings.values())) + '** |')
    return '\n'.join(lines)


def main():
    check = '--check' in sys.argv[1:]
    rows = {r['id']: r for r in m.match('ABCDE')}
    missing = [i for i in rows if i not in OUT]
    if missing: raise SystemExit('no decision for ' + ', '.join(missing))
    decided = [(rows[i], cell_for(rows[i])) for i in rows]
    ad = [(r, c) for r, c in decided if r['section'] in 'ABCD']; e = [(r, c) for r, c in decided if r['section'] == 'E']
    if check:
        print(counts_table(ad)); print(counts_table(e)); return
    source = m.TABLE.read_text()
    cut = source.find('\n## 9. New outcomes')
    if cut != -1: source = source[:cut + 1]
    cells = {row['id']: cell for row, cell in decided}
    out = []; table = False
    for line in source.splitlines():
        if line.startswith('## '): table = line.startswith('## 8. ')   # only the rows of the table (section 8)
        hit = re.match(r'\| (R-\d{3}) \|', line)
        if table and hit and hit.group(1) in cells:
            parts = re.split(r'(?<!\\)\|', line)
            if len(parts) != 10: raise SystemExit(hit.group(1) + ': unexpected column count')
            parts[8] = ' ' + cells[hit.group(1)] + ' '
            line = '|'.join(parts)
        out.append(line)
    text = '\n'.join(out).rstrip('\n') + '\n\n' + SECTION9.replace('{COUNTS}', counts_table(ad)).replace('{COUNTS_E}', counts_table(e)).replace('{COUNTS_ALL}', counts_table(decided)).strip('\n') + '\n'
    m.TABLE.write_text(text)
    print('wrote', len(decided), 'cells and section 9')


if __name__ == '__main__':
    main()
