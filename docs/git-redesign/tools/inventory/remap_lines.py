#!/usr/bin/env python3
"""Move the `path:line` references of a decisions file from one commit to another (read-only on the code).

Each referenced Python file of the manager is compared between OLD and NEW (difflib); a line inside an unchanged
block moves with it, a line inside a changed block is reported for a hand check (and mapped to the start of the
new block). Shorthand references (`:123` or `:123-130` after a path in the same line) use the last path named
before them on that line. Only app/*.py references are moved; page scripts are rewritten by hand.

  python3 docs/git-redesign/tools/inventory/remap_lines.py OLD NEW FILE [--write]
"""
import difflib, re, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = Path(subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True, cwd=HERE).stdout.strip())
PATH = re.compile(r'(app/(?:host_git|git_progress|git_place|git_places|main|restore)\.py)')
REF = re.compile(r'(app/(?:host_git|git_progress|git_place|git_places|main|restore)\.py)?:(\d+(?:-\d+)?(?:, ?\d+(?:-\d+)?)*)')


def show(ref, rel):
    return subprocess.run(['git', 'show', ref + ':clab-backup-ui/' + rel], capture_output=True, text=True, cwd=ROOT).stdout.splitlines()


def line_map(old, new):
    m, unsure = {}, set()
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        for k in range(i1, i2):
            if tag == 'equal': m[k + 1] = j1 + (k - i1) + 1
            else: m[k + 1] = j1 + 1; unsure.add(k + 1)
    return m, unsure


def main():
    old_ref, new_ref, target = sys.argv[1:4]
    write = '--write' in sys.argv
    maps = {}
    def mapped(rel, n):
        if rel not in maps: maps[rel] = line_map(show(old_ref, rel), show(new_ref, rel))
        m, unsure = maps[rel]
        return m.get(n, n), n in unsure
    out, flags = [], []
    for no, line in enumerate(Path(target).read_text().splitlines(), 1):
        last = None; pieces = []; pos = 0
        for hit in REF.finditer(line):
            path = hit.group(1) or last
            before = line[hit.start() - 1] if hit.start() else ''
            if hit.group(1): last = hit.group(1)
            if path is None or (not hit.group(1) and before not in ' ('):
                continue
            def one(token):
                a, _, b = token.partition('-')
                na, ua = mapped(path, int(a))
                if ua: flags.append(f'{target}:{no} {path}:{a} -> {na} (changed block)')
                if not b: return str(na)
                nb, ub = mapped(path, int(b))
                if ub: flags.append(f'{target}:{no} {path}:{b} -> {nb} (changed block)')
                return f'{na}-{nb}'
            moved = ', '.join(one(t.strip()) for t in hit.group(2).split(','))
            pieces.append(line[pos:hit.start(2)] + moved); pos = hit.end(2)
        pieces.append(line[pos:]); out.append(''.join(pieces))
    for f in flags: print(f)
    if write: Path(target).write_text('\n'.join(out) + '\n')


if __name__ == '__main__':
    main()
