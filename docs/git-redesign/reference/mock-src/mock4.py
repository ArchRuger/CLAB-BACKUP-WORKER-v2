#!/usr/bin/env python3
"""Option F, second version: Save and Load are two equal buttons in the lab header and the chip is
pure status. Same emulation as before; only the header control (and its panels) is replaced."""
import json
import emulate as m
import mock2 as r2
import mock3 as f1
from playwright.sync_api import sync_playwright

CSS = f1.CSS + """
#lab-content{--lab-action-col:35rem}
.rx-dot.info{background:var(--accent)}
.rx-pop.rx-wide{width:440px}
.rx-pop .rx-h:first-child{margin-top:0}
.rx-pop .rx-h{margin:16px 0 0}
.rx-ver[disabled]{cursor:default;color:var(--muted)}
.rx-ver .rx-why{display:block;font-size:12px;color:var(--muted);margin-top:2px}
.rx-devs{list-style:none;margin:0 0 14px;padding:0;border:1px solid var(--line);border-radius:var(--radius)}
.rx-devs li{display:flex;align-items:center;gap:10px;padding:8px 12px;font-size:13px;border-top:1px solid var(--line)}
.rx-devs li:first-child{border-top:0}
.rx-devs label{display:flex;align-items:center;gap:10px;margin:0;font-weight:500;color:var(--ink)}
.rx-devs input{margin:0;flex:none}
.rx-devs small{color:var(--muted);font-size:12px;font-weight:400}
.rx-devs .rx-end{margin-left:auto;color:var(--muted);font-size:12px;white-space:nowrap}
.rx-devs .rx-end.ok{color:var(--ok-strong);font-weight:600}
.rx-devs .rx-end.bad{color:var(--danger-strong);font-weight:600}
.rx-devs .rx-end.now{color:var(--accent-strong);font-weight:600}
.rx-devs li.rx-off{color:var(--muted)}
.rx-kv{margin:0 0 4px;font-size:13px;color:var(--text)}
.rx-kv span{color:var(--muted)}
"""
ver, CHEV, STAR, FOOT = r2.ver, r2.CHEV, r2.STAR, f1.FOOT

CHIPS = dict(f1.CHIPS, **{
    'loading': '<span class="rx-dot busy"></span>Loading… 2 of 4',
    'running': '<span class="rx-dot info"></span>Running ospf-up',
    'partial': '<span class="rx-dot warn"></span>Loaded 3 of 4',
    'stopped': '<span class="rx-dot"></span>Saved 21 min ago',
})


def header(chip, chip_panel='', load_panel='', load_disabled=False, save_disabled=False, wide=True):
    cp = f'<div class="rx-pop">{chip_panel}</div>' if chip_panel else ''
    lp = f'<div class="rx-pop{" rx-wide" if wide else ""}">{load_panel}</div>' if load_panel else ''
    dis = lambda on: ' disabled' if on else ''
    return (f'<span class="rx-head"><span class="menu"><button type="button" class="button secondary rx-chip" aria-haspopup="true" aria-expanded="{"true" if chip_panel else "false"}">{CHIPS[chip]}{CHEV}</button>{cp}</span>'
            f'<button type="button" class="button primary"{dis(save_disabled)}>Save</button>'
            f'<span class="menu"><button type="button" class="button secondary"{dis(load_disabled)} aria-haspopup="true" aria-expanded="{"true" if load_panel else "false"}">Load</button>{lp}</span></span>')


def state(dot, title, sub):
    return f'<p class="rx-state"><span class="rx-dot {dot}"></span>{title}</p><p class="rx-sub">{sub}</p>'


def li(name, when, star=False, why='', disabled=False):
    extra = f'<span class="rx-why">{why}</span>' if why else ''
    return (f'<li><button type="button" class="rx-ver"{" disabled" if disabled else ""}><span>{STAR if star else ""}{name}{extra}</span>'
            f'<span class="rx-when">{when}</span></button></li>')


MINE = li('Interface descriptions cleaned up', '21 minutes ago') + li('ospf-up', '2 hours ago', True) + li('loopbacks-reachable', '5 hours ago', True)
THEIRS = (li('Final state (instructor)', '2 of 4 devices') + li('Broken', '4 devices')
          + li('Starting state', 'View only', why='Saved without the files needed to load it', disabled=True))
LOAD_FOOT = '<div class="rx-foot"><button type="button" class="rx-quiet">All versions</button><button type="button" class="rx-quiet">Browse the repository…</button></div>'
P_LOAD = f'<h2 class="rx-h">Your versions</h2><ul class="rx-list">{MINE}</ul><h2 class="rx-h">From your instructor</h2><ul class="rx-list">{THEIRS}</ul>{LOAD_FOOT}'
P_LOAD_FRESH = (f'<p class="rx-sub">This lab has no saves of its own yet. You can start from one of these.</p>'
                f'<h2 class="rx-h">From your instructor</h2><ul class="rx-list">{THEIRS}</ul>{LOAD_FOOT}')


def dev(name, kind, end, cls='', checked=True, off=False):
    box = f'<input type="checkbox"{" checked" if checked else ""}{" disabled" if off else ""}>'
    return f'<li class="{"rx-off" if off else ""}"><label>{box}<span>{name} <small>{kind}</small></span></label><span class="rx-end {cls}">{end}</span></li>'


def status(name, kind, end, cls=''):
    return f'<li><span>{name} <small>{kind}</small></span><span class="rx-end {cls}">{end}</span></li>'


ACTIONS = '<div class="rx-row"><button type="button" class="button danger">Load</button><button type="button" class="rx-quiet">Cancel</button><button type="button" class="rx-quiet">See what’s different</button></div>'
P_CONFIRM = (state('warn', 'Load ospf-up?', 'The running configuration of the ticked devices is replaced. The current one is backed up first; nothing reboots.')
             + '<ul class="rx-devs">' + dev('ceos', 'EOS', '5 lines differ') + dev('cjunosevolved', 'Junos', '4 lines differ')
             + dev('vjunos-switch', 'Junos', 'Already matches') + dev('xrv9k', 'IOS-XR', '7 lines differ') + '</ul>' + ACTIONS)
P_PARTIAL_VERSION = (state('warn', 'Load Final state (instructor)?', 'This version covers 2 of your 4 devices. The others are left as they are.')
                     + '<ul class="rx-devs">' + dev('cjunosevolved', 'Junos', '12 lines differ') + dev('vjunos-switch', 'Junos', '9 lines differ')
                     + dev('ceos', 'EOS', 'Not in this version', checked=False, off=True) + dev('xrv9k', 'IOS-XR', 'Not in this version', checked=False, off=True) + '</ul>' + ACTIONS)
P_LOADING = (state('busy', 'Loading ospf-up…', 'Each device checks the new configuration itself and undoes it if it loses contact. You can keep working.')
             + '<ul class="rx-devs">' + status('ceos', 'EOS', 'Loaded', 'ok') + status('cjunosevolved', 'Junos', 'Loaded', 'ok')
             + status('vjunos-switch', 'Junos', 'Loading…', 'now') + status('xrv9k', 'IOS-XR', 'Waiting') + '</ul>')
P_RUNNING = (state('info', 'Running ospf-up', 'Loaded 1 minute ago on all 4 devices.')
             + '<p class="rx-kv"><span>Your latest save:</span> Interface descriptions cleaned up, 22 minutes ago</p>'
             + '<p class="rx-kv"><span>Before loading:</span> backed up automatically</p>'
             + '<div class="rx-foot"><button type="button" class="rx-quiet">Undo this load</button><button type="button" class="rx-quiet">What changed</button></div>')
P_PARTIAL = (state('warn', 'Loaded on 3 of 4 devices', 'xrv9k did not accept ospf-up and kept its previous configuration.')
             + '<ul class="rx-devs">' + status('ceos', 'EOS', 'Loaded', 'ok') + status('cjunosevolved', 'Junos', 'Loaded', 'ok')
             + status('vjunos-switch', 'Junos', 'Loaded', 'ok') + status('xrv9k', 'IOS-XR', 'Kept previous', 'bad') + '</ul>'
             + '<div class="rx-row"><button type="button" class="button primary">Try xrv9k again</button><button type="button" class="rx-quiet">Undo this load</button><button type="button" class="rx-quiet">Details</button></div>')
P_STOPPED = state('none', 'Start the lab to load a version', 'Loading puts a saved configuration onto running devices. This lab is not running.') + '<div class="rx-row"><button type="button" class="button primary">Start lab</button></div>'
P_STATUS = (state('', 'Saved 21 minutes ago', 'Interface descriptions cleaned up')
            + '<p class="rx-kv"><span>Running:</span> your latest save</p><p class="rx-kv"><span>Uploaded:</span> yes, to github.com</p>' + FOOT)
P_SAVE = (state('warn', 'Not uploaded yet', '2 devices changed since your last save: ceos and xrv9k. 19 lines added, 1 removed.')
          + '<div class="rx-row"><button type="button" class="button primary rx-save">Upload</button><button type="button" class="rx-quiet">Not now</button><button type="button" class="rx-quiet">See changes</button></div>'
          + '<p class="rx-note">Saved files can contain passwords or keys.</p>')


def board(browser, world, name, head, toast='', stopped=False):
    page = browser.new_page(viewport=dict(width=1440, height=900))
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
    if stopped:
        page.evaluate("""() => { const p = document.getElementById('lab-state'); p.textContent = 'Stopped'; p.className = 'pill neutral';
          document.getElementById('lab-ready').textContent = 'Not running';
          document.querySelectorAll('#devices-view .pill').forEach(x => { x.textContent = 'Not running'; x.className = 'pill neutral'; });
          document.querySelectorAll('#devices-view button').forEach(b => { if (/Open CLI/.test(b.textContent)) b.disabled = true; }); }""")
    if toast:
        page.evaluate('(text) => notify(text)', toast)
    page.wait_for_timeout(350)
    page.screenshot(path=str(m.OUT / f'{name}.png'))
    page.close()
    return errors


def main():
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        rest, rev = m.build('rest'), m.build('review')
        out['01'] = board(b, rest, 'G01-rest', header('saved'))
        out['02'] = board(b, rest, 'G02-load-open', header('saved', load_panel=P_LOAD))
        out['03'] = board(b, rest, 'G03-load-confirm', header('saved', load_panel=P_CONFIRM))
        out['04'] = board(b, rest, 'G04-loading', header('loading', load_panel=P_LOADING, save_disabled=True))
        out['05'] = board(b, rest, 'G05-running', header('running', chip_panel=P_RUNNING), toast='ospf-up loaded on 4 devices.')
        out['06'] = board(b, rest, 'G06-partial-failure', header('partial', chip_panel=P_PARTIAL))
        out['07'] = board(b, rest, 'G07-partial-version', header('saved', load_panel=P_PARTIAL_VERSION))
        out['08'] = board(b, rest, 'G08-fresh-lab', header('none', load_panel=P_LOAD_FRESH))
        out['09'] = board(b, rest, 'G09-not-running', header('stopped', load_panel=P_STOPPED, wide=False), stopped=True)
        out['10'] = board(b, rest, 'G10-status', header('saved', chip_panel=P_STATUS))
        out['11'] = board(b, rev, 'G11-save', header('pending', chip_panel=P_SAVE))
        b.close()
    print(json.dumps(out))


if __name__ == '__main__':
    main()
