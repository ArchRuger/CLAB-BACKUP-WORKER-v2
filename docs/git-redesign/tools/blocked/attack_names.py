"""Attack 1: folder names and paths (fixture). Every hostile string typed into the chooser's Folder field and into New folder…,
a 500-character path, 60 levels deep, names that differ only by case, a path through a committed file, the top level, and
latest/baseline/checkpoints at every position; a subset is placed for real (Save here), so the helper's rules are met too."""
import re
import sys

from blocked import Pass, Session, arguments, expect, fixture, wait_until, settle_question3

from folder_flow import open_chooser, repository, place_of  # noqa: E402

HOSTILE = ['', ' ', '/', '//', 'a//b', 'a/b/', '/a/b', ' a / b ', 'my lab', 'UX TEST (3)', 'é', 'Übung/größe', '日本語', 'a\\b',
           '\\\\server\\share', '..', '.', '../..', 'a/../b', 'a/./b', '.hidden', '..hidden', '-dash', '--', '-.-', '.git', '.GIT',
           'a/.git/b', '.Git/hooks', '.gitignore', 'a\tb', '\t', 'latest', 'a/latest', 'checkpoints/x', 'x' * 600, 'x' * 181, 'x' * 182,
           '-' * 300 + 'a', '/'.join(['ab'] * 166), '/'.join(['a'] * 250), 'a' * 250 + '/' + 'b' * 249, 'a?', '?a', 'a?b', 'a-', 'a.',
           'a..b', '~', '$(rm -rf)', 'a;b|c', 'a​b', '﻿a', 'a' + '/' * 50 + 'b', 'CON', 'a:b', '%2e%2e', 'a/%2f/b',
           'a' * 181 + '/' + 'b' * 181 + '/' + 'c' * 181]
RESERVED_POSITIONS = ['latest', 'baseline', 'checkpoints', 'checkpoints/x', 'x/latest', 'x/baseline', 'x/checkpoints', 'x/checkpoints/y',
                      'latest/x', 'baseline/x', 'checkpoints/x/y', 'x/latest/y', 'x/baseline/y', 'x/checkpoints/y/z', 'BGP/latest/x',
                      'BGP/baseline', 'BGP/checkpoints', 'BGP/checkpoints/ospf-up', 'BGP/checkpoints/new-one', 'latest/latest',
                      'checkpoints/checkpoints/checkpoints']


def state_of_chooser(s):
    p = s.page
    s.wait_js("(()=>{const a=document.getElementById('folder-answer');return !!a&&!/Checking/.test(a.textContent);})()", timeout=20000, what='an answer')
    p.wait_for_timeout(150)
    said = p.locator('#folder-answer').inner_text()
    result = p.locator('#folder-result').inner_text().replace('\n', ' ')
    refused = p.locator('#folder-refused').inner_text() if p.locator('#folder-refused').count() and p.locator('#folder-refused').is_visible() else ''
    buttons = [(b.inner_text(), b.is_enabled()) for b in p.locator('#folder-foot button').all()]
    value = p.locator('#folder-path').input_value()
    return dict(said=said, result=result, refused=refused, buttons=buttons, value=value)


def main():
    args = arguments(__doc__)
    with fixture(args.port) as (base, data):
        s = Session(base, args.headed, (args.width, args.height))
        P = Pass(s, 'names', args.out)
        p = s.page
        s.switch(capture_seconds=1)
        # shared-b has no save location: the first-save panel's Choose another place is the chooser.
        s.open_lab('shared-b')
        s.click('#git-save-progress')
        expect(p.locator('#save-first-place-other')).to_be_visible(timeout=20000)
        open_chooser(s)
        repository(s, 'Nested-Labs')

        for typed in HOSTILE + RESERVED_POSITIONS + ['BGP/notes.md', 'BGP/notes.md/x', 'README.md/x', 'notes-old/../notes', 'bgp', 'Bgp/edge', 'BGP/EDGE', 'SHARED']:
            label = 'Folder field: %r' % (typed if len(typed) < 40 else typed[:20] + '…(%d chars)' % len(typed))
            s.fill('#folder-path', typed)
            try: x = state_of_chooser(s)
            except AssertionError as exc:
                P.tried(label, ok=False, kind='nothing', note='no answer within 20 s: ' + str(exc)); continue
            problems = []
            if x['refused']: problems.append(('refusal', x['refused']))
            primary = [b for b in x['buttons'] if b[0] != 'Cancel']
            if primary and not any(enabled for _, enabled in primary): problems.append(('greyed', 'answer buttons disabled: %r' % primary))
            for text in (x['said'], x['refused']):
                hit = P.raw_check(text)
                if hit: problems.append(('raw', 'the word %r in %r' % (hit, text)))
            said = '%s | %s | field=%r | %s' % (x['said'], x['result'], x['value'][:60], [b[0] for b in primary])
            if problems: P.tried(label, said, ok=False, kind=problems[0][0], note='; '.join(n for _, n in problems))
            else: P.tried(label, said)

        # 60 levels deep, a 500-character path, typed character by character for the last one (the field's maxlength)
        deep = '/'.join('l%02d' % i for i in range(60))
        s.fill('#folder-path', deep); x = state_of_chooser(s)
        P.tried('60 levels deep (%d chars)' % len(deep), '%s | %s' % (x['said'], x['result'][:80]), ok=not x['refused'], kind='refusal', note=x['refused'])
        long = '/'.join(['abcdefghi'] * 50)   # 499 characters
        s.fill('#folder-path', long + 'xyz'); x = state_of_chooser(s)
        P.tried('a 502-character path typed (field maxlength 500)', 'field keeps %d chars | %s' % (len(x['value']), x['said'][:120]), ok=not x['refused'], kind='refusal', note=x['refused'])
        p.locator('#folder-path').fill('')
        p.locator('#folder-path').type('a' * 30 + '/' + 'b' * 30, delay=5)
        x = state_of_chooser(s)
        P.tried('typed key by key (echo while typing)', '%s | field=%r' % (x['said'], x['value']), ok=x['value'] == 'a' * 30 + '/' + 'b' * 30, kind='untrue', note='the field shows %r' % x['value'])

        # New folder… with hostile names, below the top level and below BGP
        for parent in ['', 'BGP']:
            for name in ['', ' ', 'é', '日本語', '..', '.git', 'latest', 'checkpoints/x', 'my lab', 'a/b/c', 'notes', 'NOTES', 'x' * 600, '-' * 10, '?', 'README.md']:
                label = 'New folder… in %s: %r' % (parent or 'top', name if len(name) < 30 else name[:10] + '…')
                p.locator('#folder-path').fill(parent); state_of_chooser(s)
                s.click('.folder-chooser [data-folder-action="new"]')
                if not p.locator('#folder-new').count():
                    P.tried(label, ok=False, kind='nothing', note='New folder… opened no field'); continue
                before = p.locator('#folder-path').input_value(); sent = len(s.sent)
                p.locator('#folder-new').fill(name)
                p.locator('.folder-new [data-folder-action="new-add"]').click()
                p.wait_for_timeout(1200)
                try: s.wait_js("(()=>{const a=document.getElementById('folder-answer');return !!a&&!/Checking/.test(a.textContent);})()", timeout=8000)
                except AssertionError: pass
                p.wait_for_timeout(1500)
                new_requests = [c for c in s.sent[sent:] if '/folders/new' in c]
                still_open = p.locator('#folder-new').count() > 0
                after = p.locator('#folder-path').input_value()
                notice = p.locator('#folder-answer').inner_text()
                refused = p.locator('#folder-refused').inner_text() if p.locator('#folder-refused').count() else ''
                result = p.locator('#folder-result').inner_text().replace('\n', ' ')
                said = 'path %r -> %r | %s | %s | %s' % (before, after, notice[:120], result[-60:], refused)
                folder = result.split('›')[-1].strip()
                if 'is new' in notice or 'already exists' in notice or 'saves here' in notice or 'top level of' in notice:
                    named = notice.split(' is new')[0].split(' already exists')[0].strip()
                    if ('top level of' in notice and after) or ('is new' in notice and named != after):
                        P.tried(label + ': the sentence is about the folder chosen', said, ok=False, kind='untrue', note='field %r, sentence %r' % (after, notice[:120]))
                if refused: P.tried(label, said, ok=False, kind='refusal', note=refused)
                elif not new_requests and still_open: P.tried(label, said, ok=False, kind='nothing', note='Add sent nothing and the field stays open with no word')
                else: P.tried(label, said)
                if p.locator('#folder-new').count():
                    p.locator('#folder-new').press('Escape')

        # Place for real: a hostile subset, each through Save here (shared-b's first save, then Change… for the rest)
        placed_first = False
        for typed in ['UX TEST (3)', 'é', 'a\\b/.git/x', 'BGP/notes.md/x', 'Bgp', 'checkpoints/x', '/'.join(['abcdefghi'] * 50), deep]:
            label = 'Save here with %r' % (typed if len(typed) < 30 else typed[:12] + '…(%d)' % len(typed))
            if placed_first: open_chooser(s); repository(s, 'Nested-Labs')
            s.fill('#folder-path', typed); x = state_of_chooser(s)
            box = p.locator('#folder-move input')
            if box.count() and box.is_checked(): box.uncheck()
            primary = p.locator('#folder-foot [data-folder-primary]')
            if not primary.count() or not primary.is_enabled():
                P.tried(label, x['said'], ok=False, kind='greyed', note='no enabled primary button'); continue
            sent = len(s.sent)
            primary.click()
            settle_question3(s, P, label)
            try:
                expect(p.locator('#save-drawer')).to_be_hidden(timeout=30000)
                where = wait_until(lambda: place_of(s, 'shared-b'), timeout=20, what='a place')
                P.tried(label, 'answer %r; placed in %s' % (x['said'][:100], where))
            except AssertionError:
                refused = p.locator('#folder-refused').inner_text() if p.locator('#folder-refused').count() else ''
                P.tried(label, x['said'], ok=False, kind='refusal' if refused else 'dead-end', note=refused or 'the drawer stays open',
                        request='; '.join(c for c in s.sent[sent:] if '/git/' in c)[:400])
                if p.locator('#save-drawer').is_visible(): p.keyboard.press('Escape')
            if not placed_first:
                placed_first = True
                s.wait_chip(r'save to upload|Saved|Can.t save', timeout=40000)
            p.wait_for_timeout(500)
            if s.visible('#save-panel'): p.keyboard.press('Escape')
        s.finish()
        return P.summary()


if __name__ == '__main__':
    sys.exit(main())
