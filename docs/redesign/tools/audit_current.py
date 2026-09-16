"""Screenshot and text-dump every screen of the CURRENT (pre-redesign) UI at three desktop viewports."""
import json, sys, time, pathlib
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:8081'
OUT = pathlib.Path('/tmp/claude-1000/-home-clabllm/58f9753c-3287-4bf9-9f68-d2da708ca22e/scratchpad/shots/before')
OUT.mkdir(parents=True, exist_ok=True)
VIEWPORTS = [(1920, 1080), (1440, 900), (1366, 768)]
report = {'console_errors': [], 'screens': {}, 'failures': []}


def visible_text(page):
    return page.evaluate("""() => {
      const out = [];
      const walk = (root) => {
        for (const el of root.querySelectorAll('button, a, summary, h1, h2, h3, label, [role=status], .badge, th, small, p, strong')) {
          if (!(el.offsetParent !== null || el.closest('dialog[open]'))) continue;
          const t = (el.innerText || el.textContent || '').trim().replace(/\\s+/g, ' ');
          if (!t || t.length > 160) continue;
          const tag = el.tagName.toLowerCase();
          const id = el.id ? '#' + el.id : '';
          const dis = el.disabled ? ' [disabled' + (el.title ? ': ' + el.title : '') + ']' : '';
          out.push(tag + id + ': ' + t + dis);
        }
      };
      walk(document);
      return Array.from(new Set(out));
    }""")


def shot(page, name, vp, full=False):
    path = OUT / f'{name}--{vp[0]}x{vp[1]}.png'
    try:
        page.screenshot(path=str(path), full_page=full)
        report['screens'].setdefault(name, {})[f'{vp[0]}x{vp[1]}'] = {
            'text': visible_text(page) if vp == VIEWPORTS[0] else None,
            'scrollWidth': page.evaluate('document.documentElement.scrollWidth'),
            'scrollHeight': page.evaluate('document.documentElement.scrollHeight'),
        }
    except Exception as e:  # noqa
        report['failures'].append(f'{name}@{vp}: {e}')


def close_dialogs(page):
    page.keyboard.press('Escape')
    page.evaluate("document.querySelectorAll('dialog[open]').forEach(d=>{try{d.close()}catch(e){}})")
    page.wait_for_timeout(200)


def click(page, selector, wait=800):
    page.click(selector, timeout=4000)
    page.wait_for_timeout(wait)


with sync_playwright() as p:
    browser = p.chromium.launch()
    for vp in VIEWPORTS:
        ctx = browser.new_context(viewport={'width': vp[0], 'height': vp[1]})
        page = ctx.new_page()
        page.on('console', lambda m: report['console_errors'].append(f'{vp}: {m.type}: {m.text}') if m.type in ('error', 'warning') else None)
        page.on('pageerror', lambda e: report['console_errors'].append(f'{vp}: pageerror: {e}'))
        page.goto(BASE + '/', wait_until='networkidle')
        page.wait_for_timeout(2500)
        # Lab workspace default (topology tab)
        shot(page, '01-workspace-topology', vp)
        shot(page, '01-workspace-topology-full', vp, full=True)
        for tab in ['inventory', 'git', 'backups']:
            try:
                click(page, f'[data-tab={tab}]', 1500)
                shot(page, f'02-tab-{tab}', vp, full=True)
            except Exception as e:
                report['failures'].append(f'tab {tab}@{vp}: {e}')
        for tab in ['credentials', 'logs']:
            try:
                page.evaluate("document.getElementById('extra-views').open=true")
                click(page, f'[data-tab={tab}]', 1500)
                shot(page, f'02-tab-{tab}', vp, full=True)
            except Exception as e:
                report['failures'].append(f'tab {tab}@{vp}: {e}')
        # Node details drawer
        try:
            click(page, '[data-tab=inventory]', 800)
            click(page, '[data-details]', 1200)
            shot(page, '03-node-details', vp)
            close_dialogs(page)
        except Exception as e:
            report['failures'].append(f'details@{vp}: {e}')
        # Save menu
        try:
            page.evaluate("const m=document.getElementById('git-save-menu'); if(m){m.hidden=false; m.open=true}")
            page.wait_for_timeout(400)
            shot(page, '04-git-save-menu', vp)
            page.evaluate("const m=document.getElementById('git-save-menu'); if(m){m.open=false}")
        except Exception as e:
            report['failures'].append(f'savemenu@{vp}: {e}')
        # Git settings dialog
        try:
            click(page, '#git-open-settings', 1500)
            shot(page, '05-git-settings-dialog', vp)
            close_dialogs(page)
        except Exception as e:
            report['failures'].append(f'gitsettings@{vp}: {e}')
        # History dialog via save menu action
        try:
            page.evaluate("const m=document.getElementById('git-save-menu'); if(m){m.hidden=false; m.open=true}")
            click(page, '[data-git-action=history]', 2500)
            shot(page, '06-git-history-dialog', vp)
            close_dialogs(page)
        except Exception as e:
            report['failures'].append(f'githistory@{vp}: {e}')
        try:
            page.evaluate("const m=document.getElementById('git-save-menu'); if(m){m.hidden=false; m.open=true}")
            click(page, '[data-git-action=load]', 2500)
            shot(page, '06b-git-load-dialog', vp)
            close_dialogs(page)
        except Exception as e:
            report['failures'].append(f'gitload@{vp}: {e}')
        # Capture dialog
        try:
            click(page, '#capture-open', 2500)
            shot(page, '07-capture-dialog', vp)
            close_dialogs(page)
        except Exception as e:
            report['failures'].append(f'capture@{vp}: {e}')
        # Sidebar dialogs
        for sel, name in [('#vm-projects', '08-deploy-new-lab'), ('#operations-history', '09-operation-history'), ('#inspect-all', '10-inspect-all'), ('#vm-settings', '11-vm-connection'), ('#manager-settings', '12-manager-settings'), ('#new-lab', '13-manual-discovery'), ('#update-definition', '14-update-yaml'), ('#link-deployment', '15-link-deployment'), ('#export-sessions', '16-export-sessions'), ('#import-map', '17-import-map'), ('#lab-destroy', '18-destroy-dialog')]:
            try:
                click(page, sel, 1800)
                shot(page, name, vp)
                close_dialogs(page)
            except Exception as e:
                report['failures'].append(f'{name}@{vp}: {e}')
        # Topology context menu
        try:
            click(page, '[data-tab=topology]', 1500)
            node = page.query_selector('#topology-map g[data-node], #topology-map [data-node]')
            if node:
                node.click(button='right')
                page.wait_for_timeout(600)
                shot(page, '19-topology-context-menu', vp)
                page.keyboard.press('Escape')
            else:
                report['failures'].append(f'no topology node element@{vp}')
        except Exception as e:
            report['failures'].append(f'ctx@{vp}: {e}')
        # Edit diagram
        try:
            click(page, '#map-edit', 1200)
            shot(page, '20-diagram-editor', vp)
            page.keyboard.press('Escape')
            page.wait_for_timeout(300)
            page.evaluate("const b=document.getElementById('map-edit'); if(b&&/Done|Exit|Stop|Finish/i.test(b.textContent)) b.click()")
        except Exception as e:
            report['failures'].append(f'editor@{vp}: {e}')
        # Second lab
        try:
            page.evaluate("[...document.querySelectorAll('[data-lab]')].find(b=>/bgp-core/.test(b.textContent))?.click()")
            page.wait_for_timeout(2000)
            shot(page, '21-second-lab-topology', vp)
            page.evaluate("[...document.querySelectorAll('[data-lab]')].find(b=>/clabllm-dev/.test(b.textContent))?.click()")
        except Exception as e:
            report['failures'].append(f'lab2@{vp}: {e}')
        # Secondary pages
        if vp == VIEWPORTS[0]:
            for path, name in [('/static/debug.html', '30-debug'), ('/static/vm-connection.html', '31-vm-connection-guide'), ('/static/capture-setup.html', '32-capture-setup'), ('/static/workspace.html', '33-workspace-page')]:
                try:
                    page.goto(BASE + path, wait_until='networkidle')
                    page.wait_for_timeout(1500)
                    shot(page, name, vp, full=True)
                except Exception as e:
                    report['failures'].append(f'{name}: {e}')
            try:
                state = json.loads(page.evaluate("fetch('/api/state').then(r=>r.text())"))
                lab = state['labs'][0]
                node = next((n for n in lab['nodes'] if n.get('ssh_ready')), lab['nodes'][0])
                page.goto(BASE + f"/static/terminal.html#lab={lab['id']}&node={node['name']}&label={lab['name']}", wait_until='networkidle')
                page.wait_for_timeout(6000)
                shot(page, '34-terminal', vp)
            except Exception as e:
                report['failures'].append(f'terminal: {e}')
        ctx.close()
    browser.close()

(OUT / 'audit-report.json').write_text(json.dumps(report, indent=1))
print('screens:', len(report['screens']), 'failures:', len(report['failures']), 'console:', len(report['console_errors']))
for f in report['failures']:
    print('FAIL', f)
