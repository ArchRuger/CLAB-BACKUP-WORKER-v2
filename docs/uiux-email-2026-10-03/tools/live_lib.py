"""Helpers for the live dev1 browser acceptance run (persistent profile, 1600x1000, 127.0.0.1)."""
import json, os, sys, time
from playwright.sync_api import sync_playwright
S = '/tmp/claude-1000/-home-archtop-CLAB-Two-Worker-Kit/9c1d6dac-d5ed-49d8-805d-d33fd62bbeaa/scratchpad/live'
E = '/home/archtop/projects/clab-manager/docs/uiux-email-2026-10-03/evidence'
BASE = 'http://127.0.0.1:8081'
LAB = 'UX-ACCEPT-01'
RES = S + '/results.jsonl'

def record(step, ok, detail=''):
    print(('PASS  ' if ok else 'FAIL  ') + step + ('  · ' + str(detail) if detail else ''), flush=True)
    with open(RES, 'a') as f: f.write(json.dumps({'step': step, 'ok': bool(ok), 'detail': str(detail)[:1500]}) + '\n')

class Sess:
    def __init__(self, p, w=1600, h=1000):
        self.ctx = p.chromium.launch_persistent_context(S + '/profile', viewport={'width': w, 'height': h}, accept_downloads=True)
        self.pg = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.noise = []
        self.pg.on('console', lambda m: self.noise.append(m.text[:200]) if m.type == 'error' and 'Failed to load resource' not in m.text else None)
        self.pg.on('pageerror', lambda e: self.noise.append(str(e)[:200]))
    def shot(self, name): self.pg.screenshot(path=f'{E}/{name}.png'); print('shot', name)
    def node(self, text): return self.pg.locator('.react-flow__node').filter(has_text=text).first
    def center(self, loc): b = loc.bounding_box(); return b['x'] + b['width'] / 2, b['y'] + b['height'] / 2
    def menu(self, target, item):
        x, y = self.center(target); self.pg.mouse.click(x, y, button='right'); self.pg.wait_for_timeout(350); self.pg.get_by_role('menuitem', name=item).click(); self.pg.wait_for_timeout(500)
    def drag(self, text, x, y):
        pg = self.pg
        if not pg.get_by_text(text, exact=True).first.is_visible(): pg.click('[data-testid="panel-tab-nodes"]'); pg.wait_for_timeout(400)
        b = pg.get_by_text(text, exact=True).first.bounding_box(); pg.mouse.move(b['x'] + 10, b['y'] + 8); pg.mouse.down(); pg.mouse.move(x, y, steps=12); pg.mouse.up(); pg.wait_for_timeout(700)
    def draft(self):
        return json.loads(self.pg.evaluate(f"localStorage.getItem('clab-builder:draft:new:{LAB}')") or 'null')
