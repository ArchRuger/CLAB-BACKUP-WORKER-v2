#!/usr/bin/env python3
"""Option F in full: the Progress tab is gone and saving lives in the lab header. Every board is the
project's real page (emulate.py) with only the header's save control replaced, plus drawers/toasts."""
import json
import emulate as m
import mock as r1
import mock2 as r2
from playwright.sync_api import sync_playwright

CSS = r1.CSS + r2.CSS + """
.rx-dot.bad{background:var(--danger)}
.rx-dot.none{background:transparent;box-shadow:inset 0 0 0 2px var(--muted)}
.rx-dot.busy{background:var(--accent);box-shadow:0 0 0 4px var(--accent-soft)}
.rx-pop .rx-open{margin:6px -10px;padding:2px 10px 12px}
.rx-pop .rx-open p{font-size:12px;margin-bottom:10px}
.rx-pop .button.small{min-height:32px}
.rx-pop #rx-name{width:100%;margin:8px 0 12px;box-sizing:border-box}
.rx-pop label.rx-keep{display:flex;align-items:center;gap:8px;font-size:13px;margin:0 0 4px;color:var(--text);font-weight:400}
.rx-pop label.rx-keep input{width:auto;margin:0;flex:none}
.rx-pop .rx-sub+.rx-row{margin-top:-2px}
dialog.rx-drawer{width:min(760px,100vw)}
.rx-drawer .drawer-head .rx-row{margin-top:14px}
.rx-drawer .diff-file{margin:0 0 8px}
.rx-drawer .rx-h{margin:28px 0 4px}
.rx-drawer .rx-h:first-child{margin-top:16px}
.rx-drawer .rx-list>li.rx-open{margin:8px -12px;padding:4px 12px 14px}
.rx-drawer .rx-foot{margin:24px 0 0}
"""
CLOSE = '<button type="button" class="icon-button close" aria-label="Close"><svg class="icon" width="16" height="16" aria-hidden="true"><use href="#i-close"></use></svg></button>'
ver, versions, CHEV, STAR = r2.ver, r2.versions, r2.CHEV, r2.STAR

CHIPS = {
    'saved': '<span class="rx-dot"></span>Saved 21 min ago',
    'saving': '<span class="rx-dot busy"></span>Saving…',
    'pending': '<span class="rx-dot warn"></span>1 save to upload',
    'just': '<span class="rx-dot"></span>Saved just now',
    'failed': '<span class="rx-dot bad"></span>Upload failed',
    'none': '<span class="rx-dot none"></span>Not saved yet',
}
FOOT = '<div class="rx-foot"><button type="button" class="rx-quiet">All versions</button><button type="button" class="rx-quiet">Save settings</button></div>'
EARLIER = '<li>' + ver('Interface descriptions cleaned up', '21 minutes ago') + '</li>'


def header(chip, panel='', disabled=False):
    pop = f'<div class="rx-pop">{panel}</div>' if panel else ''
    return (f'<span class="rx-head"><span class="menu"><button type="button" class="button secondary rx-chip" aria-haspopup="true" aria-expanded="{"true" if panel else "false"}">{CHIPS[chip]}{CHEV}</button>{pop}</span>'
            f'<button type="button" class="button primary"{" disabled" if disabled else ""}>Save</button></span>')


def state(dot, title, sub):
    return f'<p class="rx-state"><span class="rx-dot {dot}"></span>{title}</p><p class="rx-sub">{sub}</p>'


P_REST = state('', 'Saved 21 minutes ago', 'Interface descriptions cleaned up') + '<h2 class="rx-h">Go back to</h2>' + versions() + FOOT
P_SAVING = state('busy', 'Saving…', 'Reading the configuration of 4 devices. You can keep working.')
P_CONFIRM = (state('warn', 'Not uploaded yet', '2 devices changed since your last save: ceos and xrv9k. 19 lines added, 1 removed.')
             + '<div class="rx-row"><button type="button" class="button primary rx-save">Upload</button><button type="button" class="rx-quiet">Not now</button><button type="button" class="rx-quiet">See changes</button></div>'
             + '<p class="rx-note">Saved files can contain passwords or keys.</p><h2 class="rx-h">Go back to</h2>' + versions(first=EARLIER) + FOOT)
P_NAME = ('<p class="rx-state"><span class="rx-dot"></span>Saved just now</p><label class="sr-only" for="rx-name">Name of this save</label>'
          '<input id="rx-name" value="ceos and xrv9k changed" maxlength="120" autocomplete="off">'
          '<label class="rx-keep checkbox-label"><input type="checkbox">Keep as a checkpoint</label>'
          '<h2 class="rx-h">Go back to</h2>' + versions(first=EARLIER) + FOOT)
P_OPEN = state('', 'Saved 21 minutes ago', 'Interface descriptions cleaned up') + '<h2 class="rx-h">Go back to</h2>' + versions(opened='ospf-up').replace(
    'class="button secondary"', 'class="button secondary small"') + FOOT
P_GOBACK = (state('warn', 'Go back to ospf-up?', 'The running configuration of all 4 devices is replaced with this version. The current one is backed up first; nothing reboots.')
            + '<div class="rx-row"><button type="button" class="button danger">Go back</button><button type="button" class="rx-quiet">Cancel</button><button type="button" class="rx-quiet">Choose devices</button></div>')
P_FIRST = (state('none', 'Not saved yet', 'Your first save goes to CLAB-MNGR-DEV-LLM, in a folder named restore-square.')
           + '<div class="rx-row"><button type="button" class="button primary rx-save">Save</button><button type="button" class="rx-quiet">Choose another place</button></div>'
           + '<p class="rx-note">Saved files can contain passwords or keys.</p>')
P_FAILED = (state('bad', 'Upload failed', 'Your save is safe on the lab VM, but github.com could not be reached.')
            + '<div class="rx-row"><button type="button" class="button primary rx-save">Try again</button><button type="button" class="rx-quiet">Details</button></div>'
            + '<h2 class="rx-h">Go back to</h2>' + versions(first=EARLIER) + FOOT)


def changes_drawer(diff):
    return f'''<dialog class="drawer rx-drawer" id="rx-drawer" aria-labelledby="rx-drawer-title"><div class="drawer-head"><div class="dialog-head"><h2 id="rx-drawer-title">What changed</h2>{CLOSE}</div>
 <p class="drawer-meta">ceos and xrv9k · 19 lines added, 1 removed · not uploaded yet</p>
 <div class="rx-row"><button type="button" class="button primary">Upload</button><button type="button" class="rx-quiet">Not now</button></div></div>
 <div class="drawer-content"><p class="rx-note">Saved files can contain passwords or keys.</p>{diff}</div></dialog>'''


def versions_drawer():
    def group(title, rows):
        return f'<h3 class="rx-h">{title}</h3><ul class="rx-list">{rows}</ul>'
    li = lambda *a, **k: '<li>' + ver(*a, **k) + '</li>'
    opened = ('<li class="rx-open">' + ver('Final state (instructor)', '9 files') + '<p>From your instructor · can be applied to all 4 devices</p>'
              '<div class="rx-row"><button type="button" class="button secondary">Go back to this version…</button><button type="button" class="rx-quiet">See what’s different</button></div></li>')
    return f'''<dialog class="drawer rx-drawer" id="rx-drawer" aria-labelledby="rx-drawer-title"><div class="drawer-head"><div class="dialog-head"><h2 id="rx-drawer-title">All versions</h2>{CLOSE}</div>
 <p class="drawer-meta">Everything saved for restore-square. Choose one to go back to it.</p></div>
 <div class="drawer-content">
 {group('Your saves', li('Interface descriptions cleaned up', '21 minutes ago') + li('Point-to-point OSPF on all four links', '47 minutes ago'))}
 {group('Checkpoints', li('ospf-up', '2 hours ago', True) + li('loopbacks-reachable', '5 hours ago', True))}
 {group('Starting point', li('Starting configuration', 'Yesterday'))}
 {group('From your instructor', opened + li('Starting state', '5 files') + li('Broken', '9 files'))}
 <div class="rx-foot"><button type="button" class="rx-quiet">Browse the repository…</button></div></div></dialog>'''


SETTINGS = r1.DRAWER.replace('id="px-drawer"', 'id="rx-drawer"')


def board(browser, world, name, head, drawer=None, toast='', width=1440, files=None):
    page = browser.new_page(viewport=dict(width=width, height=900))
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.route('**/*', m.make_handler(world))
    page.goto(f'http://manager.local/#lab={m.LAB_ID}&view=devices')
    page.wait_for_selector('#devices-view', timeout=15000)
    page.wait_for_timeout(700)
    page.evaluate('() => { renderGitProgress = () => {}; gitShowRepository = async () => {}; refresh = async () => {}; }')
    page.evaluate('''([css, html]) => { const s = document.createElement("style"); s.textContent = css; document.head.appendChild(s);
      document.querySelector('.git-save-control').innerHTML = html; const p = document.getElementById('lab-progress'); if (p) p.hidden = true;
      document.getElementById('tab-progress').hidden = true; }''', [CSS, head])
    if drawer:
        html = drawer
        if files is not None:
            diff = page.evaluate('(files) => gitFilesDiffMarkup(files, "Before this save", "This save")', files)
            html = drawer(diff)
        page.evaluate('''(html) => { document.body.insertAdjacentHTML("beforeend", html); const d = document.getElementById("rx-drawer");
          d.querySelectorAll('details.diff-file').forEach((x, i) => { x.open = true; }); d.showModal(); if (document.activeElement) document.activeElement.blur(); }''', html)
    if toast:
        page.evaluate('(text) => notify(text)', toast)
    page.wait_for_timeout(350)
    page.screenshot(path=str(m.OUT / f'{name}.png'))
    page.close()
    return errors


def main():
    files, _ = r1.diff_files([('ceos.cfg', m.CEOS_A, m.CEOS_B), ('xrv9k.cfg', m.XR_A, m.XR_B)])
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        rest, rev = m.build('rest'), m.build('review')
        out['01'] = board(b, rest, 'F01-rest', header('saved'))
        out['02'] = board(b, rest, 'F02-saving', header('saving', P_SAVING, disabled=True))
        out['03'] = board(b, rev, 'F03-confirm', header('pending', P_CONFIRM))
        out['04'] = board(b, rev, 'F04-changes', header('pending'), drawer=changes_drawer, files=files)
        out['05'] = board(b, rev, 'F05-uploaded', header('just'), toast='Uploaded to github.com.')
        out['06'] = board(b, rev, 'F06-name', header('just', P_NAME))
        out['07'] = board(b, rest, 'F07-open', header('saved', P_REST))
        out['08'] = board(b, rest, 'F08-version', header('saved', P_OPEN))
        out['09'] = board(b, rest, 'F09-goback', header('saved', P_GOBACK))
        out['10'] = board(b, rest, 'F10-wentback', header('saved'), toast='Back on ospf-up. 4 devices updated.')
        out['11'] = board(b, rest, 'F11-all-versions', header('saved'), drawer=versions_drawer())
        out['12'] = board(b, rest, 'F12-first-save', header('none', P_FIRST))
        out['13'] = board(b, rev, 'F13-failed', header('failed', P_FAILED))
        out['14'] = board(b, rest, 'F14-unchanged', header('saved'), toast='Nothing changed since your last save.')
        out['15'] = board(b, rest, 'F15-settings', header('saved'), drawer=SETTINGS)
        out['16'] = board(b, rev, 'F16-narrow', header('pending', P_CONFIRM), width=760)
        b.close()
    print(json.dumps(out))


if __name__ == '__main__':
    main()
