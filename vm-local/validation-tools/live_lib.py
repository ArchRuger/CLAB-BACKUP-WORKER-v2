import json, os, sys, time
from playwright.sync_api import sync_playwright
BASE = os.environ.get('CLAB_BASE', 'http://127.0.0.1:8081'); OUT = os.environ['OUT']; LAB = os.environ.get('CLAB_LAB', 'clab-llm-dev2'); POLL_MS = 4000
class Run:
    def __init__(self, ctx, page, tag):
        self.ctx, self.page, self.tag = ctx, page, tag; self.console, self.pageerrors, self.checks, self.notes = [], [], [], []
        self.attach(page)
    def attach(self, page):
        page.on('console', lambda m: self.console.append({'type': m.type, 'text': m.text, 'url': page.url}) if m.type == 'error' else None)
        page.on('pageerror', lambda e: self.pageerrors.append(str(e)))
    def check(self, name, ok, detail=''):
        self.checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)[:400]}); print(('  ok   ' if ok else '  FAIL ') + f'[{self.tag}] {name}' + ('' if ok else f': {str(detail)[:300]}'), flush=True)
    def note(self, name, value): self.notes.append({name: value}); print(f'  note [{self.tag}] {name}: {str(value)[:500]}', flush=True)
    def shot(self, name, full=False, page=None): (page or self.page).screenshot(path=os.path.join(OUT, f'{self.tag}-{name}.png'), full_page=full)
    def js(self, expr, arg=None): return self.page.evaluate(expr, arg)
    def open_lab(self, name=LAB):
        p = self.page
        if not p.url.startswith(BASE): p.goto(BASE + '/')
        p.wait_for_function('() => typeof state !== "undefined" && state.loaded', timeout=20000)
        if not p.evaluate('() => document.getElementById("home") && !document.getElementById("home").hidden'): p.click('#crumb-home')
        p.wait_for_selector('#home:not([hidden])', timeout=10000)
        card = p.locator(f'article.lab-card:has(h3:text-is("{name}")) button[data-lab]').first
        if card.count() == 0: card = p.locator('#home-continue button[data-lab]').first
        card.click(); p.wait_for_selector('#lab-content:not([hidden])', timeout=10000)
        p.wait_for_function('() => document.getElementById("title").textContent.trim().length > 0')
    def tab(self, name):
        self.page.click(f'#tab-{name}'); self.page.wait_for_selector(f'#{name}-view:not([hidden])', timeout=5000)
    def report(self, name):
        real = [c for c in self.console if 'Failed to load resource: the server responded with a status of' not in c['text']]
        handled = [c for c in self.console if c not in real]
        ok = sum(c['ok'] for c in self.checks)
        summary = {'tag': self.tag, 'checks': f'{ok}/{len(self.checks)}', 'console_errors': real, 'handled_http': handled, 'pageerrors': self.pageerrors, 'notes': self.notes, 'failed': [c for c in self.checks if not c['ok']]}
        json.dump(summary, open(os.path.join(OUT, f'{name}.json'), 'w'), indent=1)
        print(f'{self.tag}: {ok}/{len(self.checks)} checks, console errors {len(real)}, handled http {len(handled)}, page errors {len(self.pageerrors)}', flush=True)
        for c in real: print('   console:', c['text'][:300])
        for e in self.pageerrors: print('   pageerror:', e[:300])
        return summary
def session(tag, width=1440, height=900):
    pw = sync_playwright().start(); b = pw.chromium.launch(headless=True); ctx = b.new_context(viewport={'width': width, 'height': height}, device_scale_factor=1)
    p = ctx.new_page(); return pw, b, ctx, Run(ctx, p, tag)

def node_address(platform_substr):
    import json, urllib.request
    d = json.load(urllib.request.urlopen(BASE + '/api/state', timeout=30))
    for lab in d['labs']:
        if lab['name'] == LAB:
            for n in lab['nodes']:
                if platform_substr in (n.get('platform') or ''): return n.get('address')
    return None
