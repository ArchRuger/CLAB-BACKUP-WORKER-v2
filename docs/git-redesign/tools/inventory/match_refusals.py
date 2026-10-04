#!/usr/bin/env python3
"""Match every row of docs/git-redesign/inventory/REFUSALS.md against today's sources (read-only).

For each table row of the requested sections it takes the row's text (placeholders as written) and
looks for it among the refusal texts the sources raise now:

  same     the text is raised in the row's own file (lines listed)
  moved    the text is raised only in another listed file
  near     no exact match; the closest current text by similarity (ratio shown)
  gone     nothing similar is raised any more

Current texts are taken the way the inventory took them: a Python `ast` walk renders every
`raise X(...)` / `HTTPException(code, ...)` / `_Fail(...)` / `RestoreError(...)` message (string
concatenations and f-strings with `{expr}` placeholders), plus every other string constant of three
or more words (for `reason` fields, question sentences and messages built outside a raise). Shell
files are searched line by line. The script also lists current raise texts that match no row of the
inventory (`--new`), which is the raw list of refusals added since the inventory was taken.

Usage (from anywhere inside the checkout):
  python3 docs/git-redesign/tools/inventory/match_refusals.py --sections ABCD [--tsv out.tsv] [--new]

Standard library only. It reads files; it changes nothing.
"""
import argparse, ast, difflib, re, subprocess, sys
from pathlib import Path

ROOT = Path(subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True,
                           cwd=Path(__file__).resolve().parent).stdout.strip())
TABLE = ROOT / 'docs/git-redesign/inventory/REFUSALS.md'
PY = ['clab-backup-ui/app/host_git.py', 'clab-backup-ui/app/git_progress.py', 'clab-backup-ui/app/git_place.py',
      'clab-backup-ui/app/git_places.py', 'clab-backup-ui/app/restore.py', 'clab-backup-ui/app/restore_drivers.py',
      'clab-backup-ui/app/restore_eos.py', 'clab-backup-ui/app/restore_junos.py', 'clab-backup-ui/app/restore_iosxr.py',
      'clab-backup-ui/app/restore_compare.py', 'clab-backup-ui/app/main.py', 'deploy/git-onboard.py',
      'deploy/git-registrations.py']
SH = ['deploy/setup-git.sh']
JS = ['clab-backup-ui/app/static/status.js', 'clab-backup-ui/app/static/save-header.js',
      'clab-backup-ui/app/static/save-drawers.js', 'clab-backup-ui/app/static/git-places.js',
      'clab-backup-ui/app/static/git-progress.js', 'clab-backup-ui/app/static/load.js',
      'clab-backup-ui/app/static/restore.js']
RAISERS = {'ValueError', 'HTTPException', '_Fail', 'LookupError', 'RestoreError', 'RuntimeError', 'PermissionError'}


CONSTANTS = {}
FUNCS = {}   # module-level functions whose body is one `return <text>` (a sentence built from arguments)


def render(node):
    """A message expression as text, `{expr}` for anything that is not a literal. A module-level name bound
    to a literal text (`LAB_GONE = '...'`) is rendered as that text."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str): return node.value
    if isinstance(node, ast.Name) and node.id in CONSTANTS: return CONSTANTS[node.id]
    if isinstance(node, ast.Call) and getattr(node.func, 'id', None) in FUNCS: return render(FUNCS[node.func.id])
    if isinstance(node, ast.JoinedStr):
        return ''.join(v.value if isinstance(v, ast.Constant) else '{' + ast.unparse(v.value) + '}' for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add): return render(node.left) + render(node.right)
    if isinstance(node, ast.IfExp): return '{' + render(node.body) + '|' + render(node.orelse) + '}'
    return '{' + ast.unparse(node) + '}'


def source(rel, ref=None):
    """A file's text in the working tree, or at the Git commit `ref` (None when it did not exist there)."""
    if ref is None:
        return (ROOT / rel).read_text() if (ROOT / rel).exists() else None
    done = subprocess.run(['git', 'show', ref + ':' + rel], capture_output=True, text=True, cwd=ROOT)
    return done.stdout if done.returncode == 0 else None


def raiser(name):
    return bool(name) and (name in RAISERS or name.endswith('Error') or name.endswith('Problem'))


def python_texts(rel, ref=None):
    text = source(rel, ref)
    if text is None: return [], []
    tree = ast.parse(text, rel)
    CONSTANTS.clear(); FUNCS.clear()
    for stmt in tree.body:
        if isinstance(stmt, ast.FunctionDef):
            body = [b for b in stmt.body if not (isinstance(b, ast.Expr) and isinstance(b.value, ast.Constant))]
            if len(body) == 1 and isinstance(body[0], ast.Return) and isinstance(body[0].value, (ast.BinOp, ast.JoinedStr, ast.Constant)):
                FUNCS[stmt.name] = body[0].value
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            if isinstance(stmt.value, (ast.Constant, ast.JoinedStr, ast.BinOp)):
                text = render(stmt.value)
                if isinstance(stmt.value, ast.Constant) and not isinstance(stmt.value.value, str): continue
                CONSTANTS[stmt.targets[0].id] = text
    raised, strings = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
            if raiser(name) and node.args:
                arg = node.args[1] if name == 'HTTPException' and len(node.args) > 1 else node.args[0]
                if name == 'HTTPException':
                    arg = next((k.value for k in node.keywords if k.arg == 'detail'), arg)
                raised.append((rel, node.lineno, render(arg)))
        if isinstance(node, (ast.Constant, ast.JoinedStr, ast.BinOp)):
            if isinstance(node, ast.BinOp) and not isinstance(node.op, ast.Add): continue
            text = render(node)
            if len(text.split()) >= 3: strings.append((rel, node.lineno, text))
    return raised, strings


def line_texts(rel, ref=None):
    out = []
    for i, line in enumerate((source(rel, ref) or '').splitlines(), 1):
        out.append((rel, i, line))
    return out


def norm(text):
    text = text.replace('`', '').replace('\\|', '|').replace('’', "'").replace('‘', "'")
    text = re.sub(r'\{[^{}]*(\{[^{}]*\}[^{}]*)*\}', '{}', text)
    return re.sub(r'\s+', ' ', text).strip()


def plain(text):
    """A shell line: only quotes and spaces normalised (its `{ ...; }` groups are code, not placeholders)."""
    return re.sub(r'\s+', ' ', text.replace('’', "'")).strip()


def fragments(text):
    return [f.strip() for f in norm(text).split('{}') if len(f.strip()) >= 12]


def rows(sections):
    current, out = None, []
    for line in TABLE.read_text().splitlines():
        if line.startswith('#'):   # a table section starts at `### A.` … `### E.` and ends at the next heading
            m = re.match(r'### ([A-E])\. ', line)
            current = m.group(1) if m else None
            continue
        if current in sections and line.startswith('| R-'):
            cells = [c.strip() for c in re.split(r'(?<!\\)\|', line.strip())[1:-1]]
            out.append({'section': current, 'id': cells[0], 'text': cells[1], 'at': cells[2], 'trigger': cells[3],
                        'channel': cells[4], 'cat': cells[5], 'outcome': cells[7], 'cells': cells})
    return out


def current_texts():
    raised, strings = [], []
    for rel in PY:
        r, s_ = python_texts(rel); raised += r; strings += s_
    shell = [t for rel in SH for t in line_texts(rel)]
    js = [t for rel in JS for t in line_texts(rel)]
    return raised, strings, shell, js


def match(sections):
    """One dict per row: status (same, moved, near, gone), `lines` (today's `file:line` of every exact match, the
    row's own file first), `best` (the closest text when there is no exact match) and `page` (browser lines that
    carry the text's first fragment)."""
    raised, strings, shell, js = current_texts()
    out = []
    for row in rows(set(sections)):
        own = row['at'].strip('`').split(':')[0]
        want = norm(row['text'])
        frags = fragments(row['text']) or [want]
        exact = [(f, l) for f, l, t in raised + strings if want and (norm(t) == want or all(fr in norm(t) for fr in frags))]
        # Shell and page-script lines are searched as plain text: their `{ … }` are code, not placeholders.
        exact += [(f, l) for f, l, t in shell + js if all(fr in plain(t).replace('\\u2019', "'") for fr in frags)]
        exact = sorted(set(exact), key=lambda x: (x[0] != own, x[0], x[1]))
        best, ratio = '', 0.0
        if exact:
            status = 'same' if any(f == own for f, _ in exact) else 'moved'
            lines = [f'{f}:{l}' for f, l in exact]
        else:
            scored = sorted(((difflib.SequenceMatcher(None, want, norm(t)).ratio(), f, l, t) for f, l, t in raised + strings), reverse=True)
            ratio, f, l, t = scored[0] if scored else (0, '', 0, '')
            status = 'near' if ratio >= 0.72 else 'gone'
            lines = [f'{f}:{l}']
            best = norm(t)
        page = [f'{f}:{l}' for f, l, t in js if frags and all(fr in norm(t) for fr in frags[:1])][:3]
        out.append(dict(row, status=status, lines=lines, best=best, ratio=ratio, page=page))
    return out


def problem_codes():
    """HELPER_PROBLEMS and MANAGER_PROBLEMS of git_progress.py as {sentence: code}, read with ast (no import)."""
    rel = 'clab-backup-ui/app/git_progress.py'
    tree = ast.parse(source(rel), rel)
    python_texts(rel)   # fills CONSTANTS for the names the tables use
    codes = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and getattr(stmt.targets[0], 'id', '') in ('HELPER_PROBLEMS', 'MANAGER_PROBLEMS'):
            for key, value in zip(stmt.value.keys, stmt.value.values):
                codes[render(key)] = value.value
    return codes


def problem_code(text, codes):
    """git_progress.problem_code: the exact sentence, else the first table sentence the text contains, else other."""
    text = str(text or '')
    if text in codes: return codes[text]
    return next((code for sentence, code in codes.items() if sentence in text), 'other')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sections', default='ABCD')
    ap.add_argument('--tsv')
    ap.add_argument('--new', action='store_true', help='list current raise texts no row matches')
    ap.add_argument('--new-since', metavar='REF', help='list current raise texts (and setup-git.sh echo lines) that '
                    'the same files did not raise at commit REF, each with its closest text there')
    args = ap.parse_args()
    raised, strings, shell, js = current_texts()
    codes = problem_codes()
    result = []
    for r in match(args.sections):
        text = r['text'].strip('`').replace('\\|', '|')
        where = ', '.join(x.replace('clab-backup-ui/app/', '').replace('deploy/', '') for x in r['lines'][:6])
        if r['status'] in ('near', 'gone'): where += f' ({r["ratio"]:.2f})'
        result.append((r['id'], r['cat'], r['at'].strip('`').replace('clab-backup-ui/app/', ''), r['status'], where,
                       problem_code(text, codes) if r['section'] == 'A' else '', ' '.join(r['page']), r['best'][:160], norm(r['text'])[:120]))
    if args.tsv:
        Path(args.tsv).write_text('\n'.join('\t'.join(map(str, r)) for r in result) + '\n')
    for r in result:
        print(' | '.join(map(str, r)))
    counts = {}
    for r in result: counts[r[3]] = counts.get(r[3], 0) + 1
    print('counts:', counts, file=sys.stderr)
    if args.new_since:
        old = []
        for rel in PY:
            old += [norm(t) for _, _, t in python_texts(rel, args.new_since)[0]]
        old_sh = [plain(t) for rel in SH for _, _, t in line_texts(rel, args.new_since)]
        print('\n# raise texts that are new since ' + args.new_since + ' (closest text there, ratio)')
        seen = set()
        for f, l, t in raised:
            n = norm(t)
            if not n.replace('{}', '').strip() or n in old or (f, n) in seen: continue
            seen.add((f, n))
            best = max(old, key=lambda o: difflib.SequenceMatcher(None, n, o).ratio(), default='')
            print(f'{f}:{l}\t{n[:300]}\t<- {difflib.SequenceMatcher(None, n, best).ratio():.2f} {best[:120]}')
        for f, l, t in shell:
            p_ = plain(t)
            if ('echo' in p_ or 'raise ValueError' in p_ or 'error' in p_) and p_ not in old_sh:
                print(f'{f}:{l}\t{p_[:300]}\t<- shell line changed')
    if args.new:
        known = [norm(r['text']) for r in rows(set('ABCDE'))]
        print('\n# current raise texts that match no inventory row')
        for f, l, t in raised:
            n = norm(t)
            fr = [x for x in n.split('{}') if len(x.strip()) >= 12] or [n]
            if not n.replace('{}', '').strip(): continue
            if any(n == k or all(x.strip() in k for x in fr) or difflib.SequenceMatcher(None, n, k).ratio() >= 0.9 for k in known):
                continue
            print(f'{f}:{l}\t{n[:300]}')


if __name__ == '__main__':
    main()
