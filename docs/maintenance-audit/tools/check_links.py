#!/usr/bin/env python3
"""Relative Markdown link and anchor check over tracked .md files (stdlib only)."""
import os, re, subprocess, sys, urllib.parse
root = subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], text=True).strip()
files = subprocess.check_output(['git', 'ls-files', '*.md'], text=True, cwd=root).splitlines()
LINK = re.compile(r'(?<!\!)\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)|!\[[^\]]*\]\(([^)\s]+)\)')
def slug(h):
    h = re.sub(r'[`*_]', '', h.strip().lower())
    h = re.sub(r'[^\w\- ]', '', h)
    return h.replace(' ', '-')
def anchors(path):
    out, fence = set(), False
    for line in open(path, encoding='utf-8'):
        if line.startswith('```'): fence = not fence
        if not fence and line.startswith('#'):
            out.update(re.findall(r'\{#([^}]+)\}', line))
            out.add(slug(re.sub(r'\{#[^}]+\}', '', line.lstrip('#'))))
        out.update(re.findall(r'<a\s+(?:id|name)="([^"]+)"', line))
    return out
bad = 0
for f in files:
    path = os.path.join(root, f); fence = False
    for n, line in enumerate(open(path, encoding='utf-8'), 1):
        if line.startswith('```'): fence = not fence
        if fence: continue
        for m in LINK.finditer(line):
            t = m.group(1) or m.group(2)
            if re.match(r'[a-z]+:', t) or t.startswith('<'): continue
            target, _, frag = t.partition('#')
            target = urllib.parse.unquote(target)
            dest = path if not target else os.path.normpath(os.path.join(os.path.dirname(path), target))
            if not os.path.exists(dest):
                print(f'{f}:{n}: missing {t}'); bad += 1
            elif frag and dest.endswith('.md') and slug(urllib.parse.unquote(frag)) not in anchors(dest):
                print(f'{f}:{n}: no anchor {t}'); bad += 1
print(f'{len(files)} files, {bad} problems')
sys.exit(1 if bad else 0)
