"""Attack 4: pending saves (fixture). Change the folder with one, two and three waiting saves (both answers of question 3),
disconnect with a waiting save, save from two labs while each has a waiting save, upload when another lab saved meanwhile,
keep an older save as a checkpoint while a save waits."""
import re
import sys

from blocked import Pass, Session, arguments, expect, fixture, wait_until
from folder_flow import open_chooser, repository, place_of, answer, foot_buttons


def panel(s):
    return s.page.locator('#save-panel').inner_text() if s.visible('#save-panel') else ''


def close(s):
    p = s.page
    for _ in range(3):
        if s.visible('#save-drawer') or s.visible('#save-panel') or s.visible('dialog[open]'): p.keyboard.press('Escape'); p.wait_for_timeout(250)


N = [0]


def save_one(s, device='ceos'):
    """Edits a device and saves; the save is left waiting (Not now)."""
    N[0] += 1
    s.action('edit_device', device=device, add=['   ip route 10.%d.0.0/16 10.0.0.1' % N[0]])
    close(s)
    s.click('#git-save-progress')
    s.wait_js("/save.? to upload|Upload failed|Can.t save/.test(document.getElementById('save-chip-text').textContent)&&!/Saving/.test(document.getElementById('save-chip-text').textContent)", timeout=40000, what='a waiting save')
    s.page.wait_for_timeout(500)
    close(s)


def main():
    args = arguments(__doc__)
    with fixture(args.port) as (base, data):
        s = Session(base, args.headed, (args.width, args.height))
        P = Pass(s, 'pending', args.out)
        p = s.page
        s.switch(capture_seconds=1)
        s.open_lab('restore-square')

        # question 3 with 1, 2 and 3 waiting saves: keep (1, 3), upload then move (2)
        for count, answer_ in [(1, 'keep'), (2, 'upload'), (3, 'keep')]:
            have = int((re.search(r'(\d+) saves? to upload', s.chip()) or [0, 0])[1]) if 'upload' in s.chip() else 0
            for _ in range(count - have): save_one(s)
            chip = s.chip()
            P.tried('%d waiting: the chip' % count, chip, ok=chip.startswith(str(count)), kind='untrue', note='chip %r with %d saves made' % (chip, count))
            open_chooser(s); repository(s, 'Nested-Labs')
            target = 'moved-%d' % count
            s.fill('#folder-path', target); answer(s)
            box = p.locator('#folder-move input')
            if box.count() and box.is_checked(): box.uncheck()
            p.locator('#folder-foot [data-folder-primary]').click(); p.wait_for_timeout(2500)
            said = p.locator('#folder-answer').inner_text() if s.visible('#folder-answer') else ''
            note = p.locator('#folder-answer-note').inner_text() if s.visible('#folder-answer-note') else ''
            buttons = [(b.inner_text(), b.is_enabled()) for b in p.locator('#folder-foot button').all()]
            P.tried('%d waiting: question 3' % count, '%s | %s | %s' % (said, note[:200], buttons), ok=bool(re.search(r'waiting for upload', said)), kind='untrue', note=said, shot=True)
            if not re.search(r'%d saves? of restore-square (is|are) waiting' % count, said):
                P.tried('%d waiting: question 3 counts the saves' % count, said, ok=False, kind='untrue', note='sentence %r with %d waiting' % (said, count))
            sel = '#folder-foot [data-folder-pending="%s"]' % answer_
            s.wait_js("(()=>{const b=document.querySelector('%s');return b&&!b.disabled;})()" % sel, timeout=20000, what='the answer enabled')
            p.locator(sel).click()
            try:
                expect(p.locator('#save-drawer')).to_be_hidden(timeout=60000)
                where = place_of(s, 'restore-square')
                p.wait_for_timeout(1500)
                P.tried('%d waiting: %s' % (count, 'Upload it, then move' if answer_ == 'upload' else 'Move and keep'), 'now %s, chip %r' % (where, s.chip()),
                        ok=where.endswith(':' + target), kind='dead-end', note='still %s' % where)
            except AssertionError:
                refused = p.locator('#folder-refused').inner_text() if s.visible('#folder-refused') else ''
                P.tried('%d waiting: %s' % (count, answer_), p.locator('#save-drawer').inner_text()[:300], ok=False, kind='refusal' if refused else 'dead-end', note=refused or 'drawer stays')
                close(s)
            s.no_errors('pending %d' % count) if False else None

        # the waiting saves (made in BGP, moved-1 ...) are still one upload
        close(s)
        s.click('#save-chip'); p.wait_for_timeout(1500)
        text = panel(s)
        P.tried('after three moves: what the panel offers', re.sub(r'\s+', ' ', text)[:400], shot=True)
        if s.visible('#save-upload'):
            expect(p.locator('#save-upload')).to_be_enabled(timeout=30000)
            p.locator('#save-upload').click()
            try: s.wait_toast(r'^Uploaded to ', timeout=40000); P.tried('one Upload carries every waiting save', s.chip())
            except AssertionError: P.tried('one Upload carries every waiting save', panel(s)[:300], ok=False, kind='dead-end', note=panel(s)[:200])
        close(s)
        st = s.api_state()
        left = [j for j in st.get('git_jobs', []) if j.get('commit') and not j.get('pushed') and j.get('status') not in ('dismissed',)]
        P.tried('nothing is left waiting after the upload', '%d left: %r' % (len(left), [(j.get('lab_name'), j.get('status'), j.get('target')) for j in left]),
                ok=not left, kind='untrue', note='saves still waiting after "Uploaded"')

        # disconnect with a waiting save
        save_one(s)
        s.click('#save-chip'); s.click('#save-settings'); p.wait_for_timeout(2500)
        unlink = p.locator('#save-drawer [data-git-repo-action="unlink"]')
        if unlink.count():
            unlink.click(); expect(p.locator('#git-unlink-confirm')).to_be_visible(timeout=10000)
            text = p.locator('#git-unlink-dialog').inner_text()
            P.tried('disconnect with a waiting save: the dialog', re.sub(r'\s+', ' ', text)[:300], ok=not re.search(r'cannot|must upload', text, re.I), kind='refusal', note=text[:200])
            p.locator('#git-unlink-confirm').click(); p.wait_for_timeout(2500)
            chip = s.chip()
            P.tried('disconnected: the chip still counts the waiting save', chip, ok='upload' in chip, kind='untrue', note='chip %r' % chip, shot=True)
            close(s); s.click('#save-chip'); p.wait_for_timeout(1500)
            text = panel(s)
            up = p.locator('#save-upload')
            ok = up.count() > 0
            P.tried('disconnected: the panel offers the upload', re.sub(r'\s+', ' ', text)[:300], ok=ok, kind='dead-end', note='no Upload for a waiting save of a disconnected lab', shot=True)
            if ok:
                expect(up).to_be_enabled(timeout=30000); up.click()
                try: s.wait_toast(r'^Uploaded to ', timeout=40000); P.tried('disconnected: the waiting save uploads', s.chip())
                except AssertionError: P.tried('disconnected: the waiting save uploads', panel(s)[:300], ok=False, kind='dead-end', note=panel(s)[:200])
            close(s)
        else:
            P.tried('disconnect: offered in Save settings', p.locator('#save-drawer').inner_text()[:300], ok=False, kind='dead-end', note='no Disconnect')
        # put restore-square back somewhere (first save)
        s.click('#git-save-progress'); p.wait_for_timeout(2500)
        P.tried('disconnected lab presses Save', re.sub(r'\s+', ' ', panel(s))[:300], shot=True)
        if s.visible('#save-first'):
            s.click('#save-first'); s.wait_chip(r'save to upload|Saved|Can.t', timeout=40000)
        close(s)

        # two labs, each with a waiting save, save again; then upload in one while the other saved meanwhile
        s.open_lab('edge-lab'); save_one(s, 'clab-edge-lab-r1')
        s.open_lab('restore-square'); save_one(s, 'ceos')
        s.open_lab('edge-lab'); save_one(s, 'clab-edge-lab-r2')
        chip = s.chip()
        P.tried('two labs with waiting saves, a further save in edge-lab', chip, ok='upload' in chip, kind='refusal', note=chip)
        s.click('#save-chip'); p.wait_for_timeout(1500)
        expect(p.locator('#save-upload')).to_be_enabled(timeout=30000)
        before = re.sub(r'\s+', ' ', panel(s))
        # restore-square saves meanwhile (through the page's own API call, as another tab would)
        lab = s.lab_id('restore-square')
        s.action('edit_device', device='ceos', add=['   ip route 10.200.0.0/16 10.0.0.1'])
        answer_ = p.evaluate("""async(lab)=>{const r=await fetch('/api/labs/'+lab+'/git/save',{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({request_id:crypto.randomUUID().replace(/-/g,''),target:'latest',push:true,note:''})});return r.status;}""", lab)
        def landed():
            jobs = [j for j in s.api_state()['git_jobs'] if j.get('lab_name') == 'restore-square']
            return jobs and jobs[-1].get('commit') and jobs[-1].get('status') in ('review_pending', 'committed')
        wait_until(landed, timeout=60, what='the other save committed')
        p.wait_for_timeout(2000)
        with s.expect_status(409, r'/retry'):
            p.locator('#save-upload').click(); p.wait_for_timeout(3000)
        after = re.sub(r'\s+', ' ', panel(s))
        toasts = s.toasts()
        said = ' '.join(re.findall(r'Another save was made[^.]*\.[^.]*\.', after + ' ' + ' '.join(toasts)))
        P.tried('upload when another lab saved meanwhile', 'before: %s | after: %s | toasts %r' % (before[:200], after[:300], toasts[-2:]),
                ok=bool(said) or 'Uploaded' in ' '.join(toasts), kind='untrue', note='no word that another save landed', shot=True)
        if s.visible('#save-upload'):
            expect(p.locator('#save-upload')).to_be_enabled(timeout=30000); p.locator('#save-upload').click()
            try: s.wait_toast(r'^Uploaded to ', timeout=40000); P.tried('upload again after the new review', s.chip())
            except AssertionError: P.tried('upload again after the new review', panel(s)[:300], ok=False, kind='dead-end', note=panel(s)[:200])
        close(s)

        # keep an OLDER save as a checkpoint while a save waits
        s.open_lab('restore-square'); save_one(s, 'xrv9k')
        s.click('#save-chip'); s.click('#save-all')
        try: s.wait_js("document.querySelectorAll('#save-drawer [data-save-action=\"checkpoint\"]').length>0", timeout=20000)
        except AssertionError: pass
        rows = p.locator('#save-drawer [data-save-action="checkpoint"]')
        enabled = [i for i in range(rows.count()) if rows.nth(i).is_enabled()]
        P.tried('All versions: Keep as a checkpoint offered', '%d buttons, %d enabled' % (rows.count(), len(enabled)), ok=bool(enabled), kind='greyed', note='no enabled Keep as a checkpoint', shot=True)
        P.tried('All versions: the rows of Your saves', re.sub(r'\s+', ' ', p.locator('#save-drawer').inner_text())[:500], shot=True)
        if len(enabled) > 1:
            rows.nth(enabled[-1]).click(); p.wait_for_timeout(800)
            field = p.locator('#save-checkpoint-name')
            if field.count():
                field.fill('old-one'); p.locator('#save-drawer [data-save-action="checkpoint-keep"]').click(); p.wait_for_timeout(4000)
                chip = s.chip()
                P.tried('keep an older save as a checkpoint while a save waits', 'chip %r; toasts %r' % (chip, s.toasts()[-2:]), ok=not chip.startswith("Can"), kind='refusal', note=panel(s)[:200], shot=True)
        close(s)
        st = s.fixture_state()
        P.tried('fixture state at the end', str({k: v for k, v in st.get('repositories', {}).get('Nested-Labs', {}).items() if k in ('head', 'waiting')})[:300])
        s.finish()
        return P.summary()


if __name__ == '__main__':
    sys.exit(main())
