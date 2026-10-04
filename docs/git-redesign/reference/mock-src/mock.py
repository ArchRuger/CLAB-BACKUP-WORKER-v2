#!/usr/bin/env python3
"""Redesign mockups rendered inside the project's real page: the real index.html, style.css and
scripts load exactly as in emulate.py, then the Progress panel's content is replaced by each
option's markup (the project's own classes plus the small px-* stylesheet below)."""
import json
import emulate as m
from app.textdiff import unified
from playwright.sync_api import sync_playwright

CSS = """
.px-composer{display:grid;gap:10px}
.px-composer-label{font-size:15px;font-weight:600;color:var(--ink);margin:0}
.px-composer-row{display:flex;gap:8px;flex-wrap:wrap}
.px-composer-row input{flex:1 1 320px;min-height:36px;margin:0}
.px-split{display:inline-flex}
.px-split .button:first-child{border-radius:var(--radius) 0 0 var(--radius)}
.px-split .px-split-more{border-radius:0 var(--radius) var(--radius) 0;border-left:1px solid rgba(255,255,255,.5);padding:7px 9px}
.px-composer-foot{display:flex;justify-content:space-between;align-items:center;gap:8px 16px;flex-wrap:wrap}
.px-composer-foot .git-destination-line,.px-strip .git-destination-line{margin:0;color:var(--muted)}
.px-seg{display:inline-flex;padding:3px;gap:2px;background:var(--surface-2);border-radius:8px}
.px-seg button{border:0;background:transparent;padding:5px 12px;border-radius:6px;font-size:13px;font-weight:500;color:var(--muted);cursor:pointer}
.px-seg button[aria-pressed="true"]{background:var(--surface);color:var(--ink);font-weight:600;box-shadow:0 1px 2px rgba(23,36,48,.2)}
.px-seg button span{font-weight:500;margin-left:4px;color:var(--muted)}
.px-seg.px-big button{padding:7px 16px;font-size:14px}
.px-day{font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:18px 0 8px}
.px-list{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.px-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px 16px;align-items:center;padding:10px 12px;border:1px solid var(--line);border-radius:var(--radius);background:var(--surface)}
.px-row strong{color:var(--ink)}
.px-row .pill{margin-left:8px}
.px-row small{display:block;margin-top:2px}
.px-row .actions{padding:0;flex-wrap:nowrap}
.px-more-groups{margin-top:16px;display:grid;gap:6px}
.px-more-groups summary{cursor:pointer;font-size:14px;font-weight:600;color:var(--accent-strong)}
.px-review{border:1px solid var(--line-strong);border-radius:var(--radius-lg);padding:16px;background:var(--surface);display:grid;gap:12px}
.px-review-head{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:flex-start}
.px-review-head h3,.px-review-head h2{font-size:16px;margin:0}
.px-review-head .pill{margin-left:8px}
.px-review-plain{border:0;padding:0}
.px-review-head p{margin:4px 0 0}
.px-review .op-notice,.px-review .git-destination-line{margin:0}
.px-review .diff-file{margin:0}
.px-review-files{display:grid;gap:8px}
.px-review-actions{display:flex;justify-content:flex-end;gap:8px;flex-wrap:wrap}
.px-steps{list-style:none;display:flex;flex-wrap:wrap;gap:8px 0;margin:0;padding:0;counter-reset:s}
.px-steps li{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--muted);font-weight:500}
.px-steps li::before{counter-increment:s;content:counter(s);width:24px;height:24px;border-radius:50%;border:1.5px solid var(--line-strong);display:grid;place-items:center;font-size:12px;font-weight:700;color:var(--muted);background:var(--surface);box-sizing:border-box}
.px-steps li.done{color:var(--text)}
.px-steps li.done::before{content:"\\2713";background:var(--ok);border-color:var(--ok);color:#fff}
.px-steps li.now{color:var(--ink);font-weight:600}
.px-steps li.now::before{background:var(--accent);border-color:var(--accent);color:#fff}
.px-steps li:not(:last-child)::after{content:"";width:40px;height:1.5px;background:var(--line-strong);margin:0 12px 0 4px}
.px-saving{display:flex;align-items:center;justify-content:space-between;gap:12px 24px;flex-wrap:wrap}
.px-saving p{margin:0}
.px-strip{display:flex;align-items:center;gap:8px 12px;flex-wrap:wrap;margin:0 0 12px}
.px-grow{flex:1}
.px-splitcard{padding:0;display:flex;flex-wrap:wrap;overflow:hidden}
.px-pane-list{flex:0 0 380px;border-right:1px solid var(--line);padding-bottom:12px}
.px-newsave{padding:16px;border-bottom:1px solid var(--line);display:grid;gap:8px}
.px-newsave label{margin:0;font-weight:600;color:var(--ink)}
.px-newsave input{margin:0}
.px-newsave .actions{padding:0}
.px-group{font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin:14px 16px 4px}
.px-item{display:block;width:100%;text-align:left;border:0;border-left:3px solid transparent;background:transparent;padding:8px 16px 8px 13px;cursor:pointer}
.px-item strong{display:block;color:var(--ink);font-size:13px;font-weight:600}
.px-item small{color:var(--muted);font-size:12px}
.px-item .pill{margin-left:6px}
.px-item[aria-current="true"]{background:var(--accent-soft);border-left-color:var(--accent)}
.px-pane-list details{margin:10px 16px 0}
.px-pane-list details summary{cursor:pointer;font-size:13px;font-weight:600;color:var(--accent-strong)}
.px-pane-detail{flex:1 1 560px;min-width:0;padding:20px;display:grid;gap:12px;align-content:start}
.px-detail-head{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;align-items:flex-start}
.px-detail-head h2 .pill{margin-left:8px}
.px-detail-head p{margin:4px 0 0}
.px-detail-head .actions{padding:0}
.px-pane-detail .git-destination-line,.px-pane-detail .op-notice{margin:0}
.px-pane-detail .diff-file{margin:0}
.px-subnav{display:flex;align-items:center;justify-content:space-between;gap:8px 12px;flex-wrap:wrap;margin:0 0 12px}
.px-savecard{display:grid;gap:14px}
.px-savecard .actions{padding:0}
.px-tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:12px}
.px-tile{border:1px solid var(--line);border-radius:var(--radius);padding:14px;display:grid;gap:4px;align-content:start}
.px-tile .actions{padding:0;margin-top:8px}
.px-kicker{font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted)}
.px-tile strong{color:var(--ink);font-size:15px}
.px-activity{list-style:none;margin:8px 0 0;padding:0}
.px-activity li{display:flex;gap:10px;align-items:center;padding:8px 0;border-top:1px solid var(--line);font-size:13px}
.px-activity li span.px-when{margin-left:auto;color:var(--muted);font-size:12px}
.px-foot-link{margin:12px 0 0;font-size:13px}
dialog.px-drawer{width:min(600px,100vw)}
.px-drawer h3{font-size:15px;margin:20px 0 6px}
.px-drawer .git-node-scope{grid-template-columns:repeat(2,minmax(0,1fr));margin:8px 0}
.px-drawer details{margin-top:8px}
.px-drawer details summary{cursor:pointer;font-size:13px;font-weight:600;color:var(--accent-strong)}
.px-drawer-foot{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-top:20px;padding-top:16px;border-top:1px solid var(--line)}
"""

CHEV = '<svg class="icon" width="16" height="16" aria-hidden="true"><use href="#i-chevron"></use></svg>'
DOTS = '<svg class="icon" width="16" height="16" aria-hidden="true"><circle cx="3" cy="8" r="1.5"></circle><circle cx="8" cy="8" r="1.5"></circle><circle cx="13" cy="8" r="1.5"></circle></svg>'
GEAR = '<svg class="icon" width="16" height="16" aria-hidden="true"><use href="#i-settings"></use></svg>'
DEST = '<code>CLAB-MNGR-DEV-LLM</code><span aria-hidden="true">›</span><code>restore-square/qa-1-30-37</code>'
NEW = 'eBGP between ceos and cjunosevolved, xrv9k announces its loopback'


def kebab(name, menu=False):
    items = ('<div class="menu-list" role="menu"><button type="button" role="menuitem">Compare with my latest save</button><button type="button" role="menuitem">Download as ZIP</button>'
             '<hr class="menu-sep" role="separator"><button type="button" role="menuitem">Apply to running lab…</button></div>') if menu else ''
    return f'<span class="menu"><button type="button" class="icon-button" aria-label="More actions for {name}" aria-haspopup="menu" aria-expanded="{"true" if menu else "false"}">{DOTS}</button>{items}</span>'


def row(title, pill, meta, name, menu=False, note=''):
    pill_html = f'<span class="pill {pill[0]}">{pill[1]}</span>' if pill else ''
    note_html = f'<small class="caption">{note}</small>' if note else ''
    return (f'<li class="px-row"><div><strong>{title}</strong>{pill_html}{note_html}<small class="caption">{meta}</small></div>'
            f'<div class="actions"><button type="button" class="button secondary small">View</button>{kebab(name, menu)}</div></li>')


def composer(value=''):
    return f'''<section class="card px-composer" aria-label="Save lab progress">
 <label class="px-composer-label" for="px-note">What changed since your last save?</label>
 <div class="px-composer-row"><input id="px-note" maxlength="120" autocomplete="off" placeholder="For example: eBGP between ceos and cjunosevolved" value="{value}">
  <span class="px-split"><button type="button" class="button primary">Save progress</button><button type="button" class="button primary px-split-more" aria-label="More save actions: create checkpoint, save on this VM only">{CHEV}</button></span></div>
 <div class="px-composer-foot"><p class="git-destination-line"><span>Saves to</span>{DEST}<span>· 4 devices ·</span><button type="button" class="link-button">Save settings</button></p><span class="pill ok">Saved to Git 21 minutes ago</span></div>
</section>'''


def history_rows(first=''):
    return f'''<h3 class="px-day">Today</h3><ol class="px-list">{first}
 {row('Interface descriptions cleaned up', None if first else ('ok', 'Latest'), '21 minutes ago · 9 files · uploaded to github.com', 'the latest save')}
 {row('Point-to-point OSPF on all four links', None, '47 minutes ago · 9 files · uploaded to github.com', 'this save')}
 {row('ospf-up', ('info', 'Checkpoint'), '2 hours ago · 9 files', 'ospf-up', menu=not first, note='OSPF adjacencies up on every device')}
 {row('loopbacks-reachable', ('info', 'Checkpoint'), '5 hours ago · 9 files', 'loopbacks-reachable', note='Every loopback answers ping')}
</ol><h3 class="px-day">Yesterday</h3><ol class="px-list">
 {row('Baseline', ('neutral', 'Baseline'), 'Yesterday · 9 files', 'the baseline', note='Starting configuration from the lab guide')}
</ol><div class="px-more-groups"><details><summary>From your instructor (3)</summary></details><details><summary>Other labs in this repository (1)</summary></details></div>'''


def history_card(body):
    return f'''<section class="card" aria-labelledby="px-history-title">
 <div class="section-heading"><div><h2 id="px-history-title">History</h2><p>Every save and checkpoint of this lab, newest first.</p></div>
  <div class="actions"><div class="px-seg" role="group" aria-label="Show"><button type="button" aria-pressed="true">All</button><button type="button" aria-pressed="false">Saves<span>2</span></button><button type="button" aria-pressed="false">Checkpoints<span>2</span></button></div><button type="button" class="button ghost small">Browse the repository…</button></div></div>
 {body}</section>'''


def review(diff, totals, heading='h3', boxed=True):
    cls = 'px-review' if boxed else 'px-review px-review-plain'
    return f'''<div class="{cls}">
 <div class="px-review-head"><div><{heading}>{NEW}<span class="pill warn" style="">Waiting for your review</span></{heading}><p class="caption">Saved on this VM just now · {totals}</p></div>
  <div class="px-review-actions"><button type="button" class="button secondary">Not now — keep it on the VM</button><button type="button" class="button primary">Upload these changes</button></div></div>
 <p class="op-notice">This save is on the lab VM only. Nothing is uploaded to github.com unless you choose <strong>Upload these changes</strong>. Configuration files may contain passwords or keys.</p>
 <div class="px-review-files">{diff}</div>
 <div><button type="button" class="link-button">Open the full saved version</button></div>
</div>'''.replace(' style=""', '')


def option_a_rest():
    return composer() + history_card(history_rows())


def option_a_review(diff, totals):
    saving = f'''<section class="card px-saving" aria-label="Save in progress"><ol class="px-steps"><li class="done">Described</li><li class="done">Read 4 devices</li><li class="now">Review changes</li><li>Upload</li></ol><p class="caption">Saving to CLAB-MNGR-DEV-LLM › restore-square/qa-1-30-37</p></section>'''
    return saving + history_card(f'<h3 class="px-day">Now</h3>{review(diff, totals)}' + history_rows(first=' '))


def list_pane(new=False):
    top = (f'<button type="button" class="px-item" aria-current="true"><strong>{NEW}</strong><small>Just now · on this VM</small><span class="pill warn">Review</span></button>' if new else '')
    cur = lambda on: ' aria-current="true"' if on else ''
    return f'''<aside class="px-pane-list" aria-label="Versions of this lab">
 <div class="px-newsave"><label for="px-b-note">What changed?</label><input id="px-b-note" maxlength="120" autocomplete="off" placeholder="Describe this save"><div class="actions"><button type="button" class="button primary">Save progress</button><button type="button" class="button secondary">Create checkpoint…</button></div></div>
 <h3 class="px-group">My saves</h3>{top}
 <button type="button" class="px-item"><strong>Interface descriptions cleaned up</strong><small>21 minutes ago · uploaded</small>{'' if new else '<span class="pill ok">Latest</span>'}</button>
 <button type="button" class="px-item"><strong>Point-to-point OSPF on all four links</strong><small>47 minutes ago · uploaded</small></button>
 <h3 class="px-group">Checkpoints</h3>
 <button type="button" class="px-item"{cur(not new)}><strong>ospf-up</strong><small>2 hours ago · OSPF adjacencies up on every device</small></button>
 <button type="button" class="px-item"><strong>loopbacks-reachable</strong><small>5 hours ago · Every loopback answers ping</small></button>
 <h3 class="px-group">Baseline</h3>
 <button type="button" class="px-item"><strong>Baseline</strong><small>Yesterday · Starting configuration from the lab guide</small></button>
 <h3 class="px-group">From your instructor</h3>
 <button type="button" class="px-item"><strong>Final state (instructor)</strong><small>restore-square/Final · 9 files</small></button>
 <button type="button" class="px-item"><strong>Starting state</strong><small>restore-square/start/latest · 5 files</small></button>
 <button type="button" class="px-item"><strong>Broken</strong><small>restore-square/Broken/latest · 9 files</small></button>
 <details><summary>Other labs in this repository (1)</summary></details>
</aside>'''


def strip(status='<span class="pill ok">Saved to Git 21 minutes ago</span>'):
    return f'''<div class="px-strip"><p class="git-destination-line"><span>Saving to</span>{DEST}<span>· 4 devices</span></p>{status}<span class="px-grow"></span><button type="button" class="button ghost small">Browse the repository…</button><button type="button" class="button ghost small">{GEAR}Save settings</button></div>'''


def option_b_rest(diff, totals):
    detail = f'''<div class="px-pane-detail">
 <div class="px-detail-head"><div><h2>ospf-up<span class="pill info">Checkpoint</span></h2><p>OSPF adjacencies up on every device</p><p class="caption">Saved 2 hours ago · 9 files · can be applied to all 4 devices</p></div>
  <div class="actions"><button type="button" class="button secondary">Download ZIP</button><button type="button" class="button danger-outline">Apply to running lab…</button></div></div>
 <p class="git-destination-line"><code>CLAB-MNGR-DEV-LLM</code><span aria-hidden="true">›</span><code>restore-square/qa-1-30-37/checkpoints/ospf-up</code></p>
 <div><div class="px-seg" role="group" aria-label="Show"><button type="button" aria-pressed="true">Changes since this checkpoint<span>{totals.split(' · ')[0].split(' ')[0]}</span></button><button type="button" aria-pressed="false">Files<span>9</span></button></div></div>
 <p class="caption">What your latest save has that this checkpoint does not ({totals}).</p>
 <div class="px-review-files">{diff}</div>
</div>'''
    return strip() + f'<section class="card px-splitcard">{list_pane()}{detail}</section>'


def option_b_review(diff, totals):
    detail = f'''<div class="px-pane-detail">
 <div class="px-detail-head"><div><h2>Review before uploading</h2><p>{NEW}</p><p class="caption">Saved on this VM just now · {totals}</p></div>
  <div class="actions"><button type="button" class="button secondary">Not now — keep it on the VM</button><button type="button" class="button primary">Upload these changes</button></div></div>
 <p class="op-notice">This save is on the lab VM only. Nothing is uploaded to github.com unless you choose <strong>Upload these changes</strong>. Configuration files may contain passwords or keys.</p>
 <div class="px-review-files">{diff}</div>
</div>'''
    return strip('<span class="pill warn">1 save waiting for your review</span>') + f'<section class="card px-splitcard">{list_pane(new=True)}{detail}</section>'


def subnav(status):
    return f'''<div class="px-subnav"><div class="px-seg px-big" role="group" aria-label="Progress views"><button type="button" aria-pressed="true">Save</button><button type="button" aria-pressed="false">Versions<span>8</span></button><button type="button" aria-pressed="false">Settings</button></div>{status}</div>'''


def tiles():
    def tile(kicker, name, note, meta, compare=True):
        cmp_btn = '<button type="button" class="button secondary small">Compare</button>' if compare else ''
        return (f'<div class="px-tile"><span class="px-kicker">{kicker}</span><strong>{name}</strong><span>{note}</span><span class="caption">{meta}</span>'
                f'<div class="actions"><button type="button" class="button secondary small">View</button>{cmp_btn}<button type="button" class="button danger-outline small">Apply to running lab…</button></div></div>')
    return f'''<section class="card" aria-labelledby="px-back-title"><h2 id="px-back-title">Go back to a version</h2><p class="caption">Applying replaces the running configuration of the devices you choose. The current one is backed up first; nothing reboots.</p>
 <div class="px-tiles">{tile('Latest save', 'Interface descriptions cleaned up', 'Your most recent save', '21 minutes ago · 9 files', compare=False)}{tile('Last checkpoint', 'ospf-up', 'OSPF adjacencies up on every device', '2 hours ago · 9 files')}{tile('Baseline', 'Baseline', 'Starting configuration from the lab guide', 'Yesterday · 9 files')}</div>
 <p class="px-foot-link"><button type="button" class="link-button">All 8 versions, including 3 from your instructor</button></p></section>'''


def activity(first=''):
    return f'''<section class="card" aria-labelledby="px-activity-title"><h2 id="px-activity-title">Recent activity</h2><ul class="px-activity">{first}
 <li><span class="pill {'neutral">Earlier save' if first else 'ok">Latest'}</span><span>Interface descriptions cleaned up</span><span class="px-when">21 minutes ago · uploaded</span></li>
 <li><span class="pill neutral">Earlier save</span><span>Point-to-point OSPF on all four links</span><span class="px-when">47 minutes ago · uploaded</span></li>
 <li><span class="pill ok">Checkpoint</span><span>ospf-up · OSPF adjacencies up on every device</span><span class="px-when">2 hours ago · uploaded</span></li>
</ul></section>'''


def option_c_rest():
    save = f'''<section class="card px-savecard" aria-label="Save lab progress">
 <ol class="px-steps"><li class="now">Describe</li><li>Read devices</li><li>Review changes</li><li>Upload</li></ol>
 <div class="px-composer"><label class="px-composer-label" for="px-c-note">What changed since your last save?</label>
  <div class="px-composer-row"><input id="px-c-note" maxlength="120" autocomplete="off" placeholder="For example: eBGP between ceos and cjunosevolved"><button type="button" class="button primary">Save progress</button></div></div>
 <div class="px-composer-foot"><div class="actions"><button type="button" class="button secondary small">Create checkpoint…</button><button type="button" class="button ghost small">Save on this VM only</button></div><p class="git-destination-line"><span>Saves to</span>{DEST}<span>· 4 devices</span></p></div>
</section>'''
    return subnav('<span class="pill ok">Saved to Git 21 minutes ago</span>') + save + tiles() + activity()


def option_c_review(diff, totals):
    save = f'''<section class="card px-savecard" aria-label="Save lab progress">
 <ol class="px-steps"><li class="done">Describe</li><li class="done">Read devices</li><li class="now">Review changes</li><li>Upload</li></ol>
 {review(diff, totals, heading='h2', boxed=False)}
</section>'''
    first = f'<li><span class="pill warn">Latest</span><span>{NEW}</span><span class="px-when">just now · waiting for your review</span></li>'
    return subnav('<span class="pill warn">1 save waiting for your review</span>') + save + activity(first)


DRAWER = f'''<dialog class="drawer px-drawer" id="px-drawer" aria-labelledby="px-drawer-title">
 <div class="drawer-head"><div class="dialog-head"><h2 id="px-drawer-title">Save settings</h2><button type="button" class="icon-button close" aria-label="Close save settings"><svg class="icon" width="16" height="16" aria-hidden="true"><use href="#i-close"></use></svg></button></div>
  <p class="drawer-meta">Where restore-square saves, and which devices each save includes.</p></div>
 <div class="drawer-content">
  <h3>Save location</h3>
  <p class="git-destination-line">{DEST}<span aria-hidden="true">›</span><code>latest/</code></p>
  <div class="actions"><button type="button" class="button secondary small">Change folder…</button><button type="button" class="button secondary small">Use a different repository…</button><button type="button" class="button secondary small">Connect by URL…</button></div>
  <details><summary>Git repo details</summary></details>
  <h3>Devices included in every save</h3>
  <fieldset class="git-node-scope"><legend class="sr-only">Devices included in every save</legend>
   <label class="checkbox-label"><input type="checkbox" checked><span>ceos<small>EOS</small></span></label>
   <label class="checkbox-label"><input type="checkbox" checked><span>cjunosevolved<small>Junos</small></span></label>
   <label class="checkbox-label"><input type="checkbox" checked><span>vjunos-switch<small>Junos (vJunos-switch)</small></span></label>
   <label class="checkbox-label"><input type="checkbox" checked><span>xrv9k<small>IOS-XR</small></span></label></fieldset>
  <p class="form-help">clab-restore-square-host1 can’t be included yet — configuration saves aren’t supported for its platform.</p>
  <p class="form-help">If an included device can’t be reached, the save stops and nothing is written — an older configuration is never saved in its place.</p>
  <details><summary>Registration details</summary></details>
  <details><summary>Advanced repository details</summary></details>
  <div class="px-drawer-foot"><button type="button" class="link-button">Disconnect this lab…</button><button type="button" class="button primary">Save settings</button></div>
 </div></dialog>'''


def diff_files(pairs):
    files, added, removed = [], 0, 0
    for name, before, after in pairs:
        d = unified(before, after)
        added += d.get('added', 0); removed += d.get('removed', 0)
        files.append(dict(name=name, status='changed', before=before, after=after, diff=d))
    return files, f'{len(files)} files changed · {added} added · {removed} removed'


def render(browser, world, name, html, files=None, drawer=False, height=None):
    page, errors = m.open_progress(browser, world)
    diff = ''
    page.evaluate('() => { renderGitProgress = () => {}; gitShowRepository = async () => {}; refresh = async () => {}; }')
    if files is not None:
        diff = page.evaluate('(files) => gitFilesDiffMarkup(files, "Before this save", "This save")', files)
    html = html.replace('{{DIFF}}', diff)
    page.evaluate('''([css, html]) => {
      const style = document.createElement('style'); style.textContent = css; document.head.appendChild(style);
      document.querySelector('.git-save-control').hidden = true;
      const view = document.getElementById('git-view'); view.innerHTML = html;
      const diffs = [...view.querySelectorAll('details.diff-file')]; diffs.forEach((d, i) => { d.open = i === 0; });
    }''', [CSS, html])
    if drawer:
        page.evaluate('(html) => { document.body.insertAdjacentHTML("beforeend", html); document.getElementById("px-drawer").showModal(); }', DRAWER)
    page.wait_for_timeout(300)
    page.screenshot(path=str(m.OUT / f'{name}.png'), full_page=not drawer)
    size = page.evaluate('() => [document.documentElement.scrollWidth, document.documentElement.scrollHeight]')
    counts = page.evaluate('''() => { const v = document.getElementById('progress-view'); const vis = e => !!(e.offsetWidth || e.offsetHeight);
      return { buttons: [...v.querySelectorAll('button')].filter(vis).length, apply: [...v.querySelectorAll('button')].filter(b => vis(b) && /Apply to running lab/.test(b.textContent)).length }; }''')
    page.close()
    return dict(size=size, counts=counts, errors=errors)


def main():
    review_files, review_totals = diff_files([('ceos.cfg', m.CEOS_A, m.CEOS_B), ('ceos.eoscfg', m.CEOS_A, m.CEOS_B), ('xrv9k.cfg', m.XR_A, m.XR_B), ('xrv9k.xrcfg', m.XR_A, m.XR_B)])
    old = m.CEOS_A.replace('description to-cjunosevolved', 'description link-1').replace('   ip ospf network point-to-point\n', '')
    cp_files, cp_totals = diff_files([('ceos.cfg', old, m.CEOS_A), ('ceos.eoscfg', old, m.CEOS_A)])
    out = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        rest, rev = m.build('rest'), m.build('review')
        out['a-rest'] = render(browser, rest, 'a-1-timeline', option_a_rest())
        out['a-review'] = render(browser, rev, 'a-2-review', option_a_review('{{DIFF}}', review_totals), review_files)
        out['b-rest'] = render(browser, rest, 'b-1-split', option_b_rest('{{DIFF}}', cp_totals), cp_files)
        out['b-review'] = render(browser, rev, 'b-2-review', option_b_review('{{DIFF}}', review_totals), review_files)
        out['c-rest'] = render(browser, rest, 'c-1-save', option_c_rest())
        out['c-review'] = render(browser, rev, 'c-2-review', option_c_review('{{DIFF}}', review_totals), review_files)
        out['drawer'] = render(browser, rest, 'd-settings-drawer', option_a_rest(), drawer=True)
        browser.close()
    print(json.dumps(out, indent=1))


if __name__ == '__main__':
    main()
