#!/usr/bin/env python3
"""Radically simple versions of the Progress workflow, rendered inside the project's real page
(same emulation as emulate.py). Only the Progress panel, or the header's save control, is replaced."""
import json
import emulate as m
from playwright.sync_api import sync_playwright

CSS = """
.rx-col{max-width:620px;margin:48px auto 72px;position:relative}
.rx-more{position:absolute;top:0;right:0}
.rx-state{display:flex;align-items:center;gap:12px;font-size:28px;font-weight:700;letter-spacing:-.02em;color:var(--ink);margin:0;line-height:1.2}
.rx-dot{width:12px;height:12px;border-radius:50%;background:var(--ok);flex:none}
.rx-dot.warn{background:var(--warn)}
.rx-sub{margin:8px 0 28px;color:var(--muted);font-size:15px;line-height:1.5;max-width:520px}
.rx-save{min-height:48px;padding:12px 28px;font-size:16px}
.rx-row{display:flex;align-items:center;gap:8px 18px;flex-wrap:wrap}
.rx-quiet{border:0;background:none;padding:6px 2px;font-size:14px;font-weight:600;color:var(--accent-strong);cursor:pointer}
.rx-note{margin:16px 0 0;font-size:12px;color:var(--muted)}
.rx-h{font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:64px 0 4px}
.rx-list{list-style:none;margin:0;padding:0}
.rx-list>li{border-bottom:1px solid var(--line)}
.rx-ver{display:flex;width:100%;justify-content:space-between;gap:16px;align-items:baseline;padding:14px 2px;border:0;background:none;text-align:left;cursor:pointer;font-size:15px;color:var(--text)}
.rx-ver .rx-when{color:var(--muted);font-size:13px;white-space:nowrap}
.rx-ver svg{color:var(--accent);margin-right:8px;vertical-align:-2px}
.rx-list>li.rx-open{border:1px solid var(--line);border-radius:var(--radius-lg);background:var(--surface);padding:4px 16px 16px;margin:8px -16px}
.rx-open .rx-ver{font-weight:600;color:var(--ink)}
.rx-open p{margin:0 0 14px;color:var(--muted);font-size:13px}
.rx-foot{margin:20px 0 0}
.rx-center{max-width:520px;margin:96px auto 120px;text-align:center}
.rx-center .rx-state{justify-content:center}
.rx-center .rx-sub{margin-left:auto;margin-right:auto}
.rx-center .rx-row{justify-content:center}
.rx-center .rx-back{margin-top:28px}
dialog.rx-dialog{width:min(560px,calc(100vw - 32px))}
.rx-dialog .rx-list{margin-top:8px}
.rx-dialog .rx-note{margin-top:14px}
.rx-dialog .rx-ver{padding:12px 10px;border-radius:var(--radius)}
.rx-dialog li.rx-picked{border-bottom-color:transparent}
.rx-dialog li.rx-picked .rx-ver{background:var(--accent-soft);color:var(--ink);font-weight:600}
.rx-head{display:flex;align-items:center;gap:8px}
.rx-chip{gap:8px;font-weight:500}
.rx-chip .rx-dot{width:8px;height:8px}
.rx-pop{position:absolute;top:calc(100% + 6px);right:0;width:380px;box-sizing:border-box;padding:18px;background:var(--surface);border:1px solid var(--line);border-radius:var(--radius-lg);box-shadow:var(--shadow-menu);z-index:20;text-align:left;white-space:normal}
.rx-pop .rx-save{min-height:40px;padding:8px 22px;font-size:14px}
.rx-pop .rx-note{margin-top:12px}
.rx-pop .rx-state{font-size:18px;gap:10px}
.rx-pop .rx-state .rx-dot{width:10px;height:10px}
.rx-pop .rx-sub{font-size:13px;margin:6px 0 14px}
.rx-pop .rx-h{margin:18px 0 0}
.rx-pop .rx-ver{font-size:13px;padding:9px 2px}
.rx-pop .rx-ver .rx-when{font-size:12px}
.rx-pop .rx-list>li:last-child{border-bottom:0}
.rx-pop .rx-foot{margin:10px 0 0;padding:10px 0 0;border-top:1px solid var(--line);display:flex;justify-content:space-between}
.rx-pop .rx-quiet{font-size:13px;padding:2px}
.rx-menu{min-width:260px}
"""

DOTS = '<svg class="icon" width="16" height="16" aria-hidden="true"><circle cx="3" cy="8" r="1.5"></circle><circle cx="8" cy="8" r="1.5"></circle><circle cx="13" cy="8" r="1.5"></circle></svg>'
STAR = '<svg class="icon" width="14" height="14" aria-hidden="true"><use href="#i-star"></use></svg>'
CHEV = '<svg class="icon" width="16" height="16" aria-hidden="true"><use href="#i-chevron"></use></svg>'
MENU = '''<div class="menu-list rx-menu" role="menu"><button type="button" role="menuitem">Name this point (checkpoint)…</button><button type="button" role="menuitem">Versions from your instructor</button><button type="button" role="menuitem">Save without uploading</button><hr class="menu-sep" role="separator"><button type="button" role="menuitem">Browse the repository…</button><button type="button" role="menuitem">Save settings…</button></div>'''


def more(open_menu=False):
    return f'<span class="menu rx-more"><button type="button" class="icon-button" aria-label="More: checkpoints, instructor versions, settings" aria-haspopup="menu" aria-expanded="{"true" if open_menu else "false"}">{DOTS}</button>{MENU if open_menu else ""}</span>'


def ver(name, when, star=False):
    return f'<button type="button" class="rx-ver"><span>{STAR if star else ""}{name}</span><span class="rx-when">{when}</span></button>'


def versions(opened='', first=''):
    def item(name, when, star=False, note=''):
        if name == opened:
            return (f'<li class="rx-open">{ver(name, when, star)}<p>{note}</p><div class="rx-row"><button type="button" class="button secondary">Go back to this version…</button>'
                    f'<button type="button" class="rx-quiet">See what’s different</button></div></li>')
        return f'<li>{ver(name, when, star)}</li>'
    return (f'<ul class="rx-list">{first}{item("Point-to-point OSPF on all four links", "47 minutes ago", note="Saved 47 minutes ago · all 4 devices")}'
            f'{item("ospf-up", "2 hours ago", True, "Checkpoint · OSPF adjacencies up on every device · all 4 devices")}'
            f'{item("loopbacks-reachable", "5 hours ago", True, "Checkpoint · Every loopback answers ping")}'
            f'{item("Starting configuration", "Yesterday", note="Baseline · from the lab guide")}</ul>')


SAVED = '<p class="rx-state"><span class="rx-dot"></span>Saved 21 minutes ago</p><p class="rx-sub">Interface descriptions cleaned up</p>'
PENDING = ('<p class="rx-state"><span class="rx-dot warn"></span>Saved here, not uploaded yet</p>'
           '<p class="rx-sub">2 devices changed since your last save: ceos and xrv9k. 19 lines added, 1 removed.</p>')
CONFIRM = ('<div class="rx-row"><button type="button" class="button primary rx-save">Upload</button><button type="button" class="rx-quiet">Not now</button>'
           '<button type="button" class="rx-quiet">See changes</button></div><p class="rx-note">Saved files can contain passwords or keys.</p>')


# D: one line and a list -----------------------------------------------------------------------
def d_rest(opened='', menu=False):
    return f'''<div class="rx-col">{more(menu)}{SAVED}<button type="button" class="button primary rx-save">Save progress</button>
 <h2 class="rx-h">Earlier</h2>{versions(opened)}</div>'''


def d_confirm():
    first = '<li>' + ver('Interface descriptions cleaned up', '21 minutes ago') + '</li>'
    return f'''<div class="rx-col">{more()}{PENDING}{CONFIRM}<h2 class="rx-h">Earlier</h2>{versions(first=first)}</div>'''


# E: two actions -------------------------------------------------------------------------------
def e_rest():
    return f'''<div class="rx-center">{SAVED}<div class="rx-row"><button type="button" class="button primary rx-save">Save progress</button></div>
 <div class="rx-row rx-back"><button type="button" class="rx-quiet">Go back to an earlier version</button></div></div>'''


def e_confirm():
    return f'''<div class="rx-center">{PENDING}{CONFIRM.replace('class="rx-row"', 'class="rx-row"', 1)}</div>'''


E_DIALOG = f'''<dialog class="rx-dialog" id="rx-dialog" aria-labelledby="rx-dialog-title"><div class="dialog-head"><h2 id="rx-dialog-title">Go back to…</h2><button type="button" class="icon-button" aria-label="Close">×</button></div>
 <ul class="rx-list"><li>{ver('Interface descriptions cleaned up', '21 minutes ago')}</li><li>{ver('Point-to-point OSPF on all four links', '47 minutes ago')}</li>
 <li class="rx-picked">{ver('ospf-up', '2 hours ago', True)}</li><li>{ver('loopbacks-reachable', '5 hours ago', True)}</li><li>{ver('Starting configuration', 'Yesterday')}</li><li>{ver('From your instructor (3)', '')}</li></ul>
 <p class="rx-note">Your running configuration is backed up first. Nothing reboots.</p>
 <div class="dialog-actions"><button type="button" class="rx-quiet">See what’s different</button><button type="button" class="button secondary">Cancel</button><button type="button" class="button primary">Go back to ospf-up</button></div></dialog>'''


# F: no Progress tab ---------------------------------------------------------------------------
def f_header(pending=False):
    if pending:
        chip = '<span class="rx-dot warn"></span>1 save to upload'
        body = PENDING.replace('Saved here, not uploaded yet', 'Not uploaded yet') + CONFIRM
    else:
        chip = '<span class="rx-dot"></span>Saved 21 min ago'
        body = SAVED
    first = '' if not pending else '<li>' + ver('Interface descriptions cleaned up', '21 minutes ago') + '</li>'
    pop = f'''<div class="rx-pop">{body}<h2 class="rx-h">Go back to</h2>{versions(first=first)}
 <div class="rx-foot"><button type="button" class="rx-quiet">All versions</button><button type="button" class="rx-quiet">Save settings</button></div></div>'''
    return f'''<span class="rx-head"><span class="menu"><button type="button" class="button secondary rx-chip" aria-haspopup="true" aria-expanded="true">{chip}{CHEV}</button>{pop}</span><button type="button" class="button primary">Save</button></span>'''


def open_page(browser, world, view):
    page = browser.new_page(viewport=dict(width=1440, height=900))
    errors = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.route('**/*', m.make_handler(world))
    page.goto(f'http://manager.local/#lab={m.LAB_ID}&view={view}')
    page.wait_for_selector('#git-saved-versions .git-version-row' if view == 'progress' else '#devices-view', timeout=15000)
    page.wait_for_timeout(700)
    page.evaluate('() => { renderGitProgress = () => {}; gitShowRepository = async () => {}; refresh = async () => {}; }')
    page.evaluate('(css) => { const s = document.createElement("style"); s.textContent = css; document.head.appendChild(s); }', CSS)
    return page, errors


def shot(page, name, full=False):
    page.wait_for_timeout(250)
    page.screenshot(path=str(m.OUT / f'{name}.png'), full_page=full)
    info = page.evaluate('''() => { const vis = e => !!(e.offsetWidth || e.offsetHeight); const v = document.getElementById('progress-view');
      return { h: document.documentElement.scrollHeight, buttons: v && vis(v) ? [...v.querySelectorAll('button')].filter(vis).length : null }; }''')
    return info


def tab_view(browser, world, name, html, dialog=''):
    page, errors = open_page(browser, world, 'progress')
    page.evaluate('''(html) => { document.querySelector('.git-save-control').hidden = true; const p = document.getElementById('lab-progress'); if (p) p.hidden = true;
      document.getElementById('git-view').innerHTML = html; }''', html)
    if dialog:
        page.evaluate('(html) => { document.body.insertAdjacentHTML("beforeend", html); document.getElementById("rx-dialog").showModal(); }', dialog)
    info = shot(page, name)
    page.close()
    return dict(info, errors=errors)


def header_view(browser, world, name, html):
    page, errors = open_page(browser, world, 'devices')
    page.evaluate('''(html) => { const c = document.querySelector('.git-save-control'); c.innerHTML = html; const p = document.getElementById('lab-progress'); if (p) p.hidden = true;
      document.getElementById('tab-progress').hidden = true; }''', html)
    info = shot(page, name)
    page.close()
    return dict(info, errors=errors)


def main():
    out = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        rest, rev = m.build('rest'), m.build('review')
        out['d1'] = tab_view(browser, rest, 'd-1-rest', d_rest())
        out['d2'] = tab_view(browser, rev, 'd-2-confirm', d_confirm())
        out['d3'] = tab_view(browser, rest, 'd-3-version-open', d_rest(opened='ospf-up'))
        out['d4'] = tab_view(browser, rest, 'd-4-more-menu', d_rest(menu=True))
        out['e1'] = tab_view(browser, rest, 'e-1-rest', e_rest())
        out['e2'] = tab_view(browser, rev, 'e-2-confirm', e_confirm())
        out['e3'] = tab_view(browser, rest, 'e-3-go-back', e_rest(), dialog=E_DIALOG)
        out['f1'] = header_view(browser, rest, 'f-1-header', f_header())
        out['f2'] = header_view(browser, rev, 'f-2-header-confirm', f_header(pending=True))
        browser.close()
    print(json.dumps(out))


if __name__ == '__main__':
    main()
