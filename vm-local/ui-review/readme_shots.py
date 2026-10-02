#!/usr/bin/env python3
"""Two live screenshots for the README: an SSH terminal with two commands and their output, and a
browser Wireshark session on a chosen device with a ping running so packets are on screen. The
capture session is ended afterwards.

    CLAB_BASE=http://127.0.0.1:8081 CLAB_SHOTS=~/ui-review/readme-shots \
    CLAB_CAPTURE_IFACES=eth0 CLAB_PING=172.20.20.3 python readme_shots.py
"""
import os
import sys

from playwright.sync_api import sync_playwright

BASE = os.environ.get('CLAB_BASE', 'http://127.0.0.1:8081')
OUT = os.path.expanduser(os.environ.get('CLAB_SHOTS', '~/ui-review/readme-shots'))
NODE_HINT = os.environ.get('CLAB_NODE', 'PTX1')
COMMANDS = [c for c in os.environ.get('CLAB_COMMANDS', 'show version;;show interfaces terse | match "et-0/0/[0-1] "').split(';;') if c]
IFACES = [i for i in os.environ.get('CLAB_CAPTURE_IFACES', 'eth0').split(',') if i]
PING = os.environ.get('CLAB_PING', '172.20.20.3')
PING_COMMAND = os.environ.get('CLAB_PING_COMMAND', f'ping {PING} count 40')


def log(*a):
    print(*a, flush=True)


def open_lab(page):
    page.goto(BASE + '/')
    page.wait_for_function('() => typeof state !== "undefined" && state.loaded', timeout=20000)
    if page.evaluate('() => document.getElementById("home") && !document.getElementById("home").hidden'):
        card = page.locator('#home-continue button[data-lab]').first
        if card.count() == 0:
            card = page.locator('article.lab-card button[data-lab]').first
        card.click()
    page.wait_for_selector('#lab-content:not([hidden])', timeout=10000)
    return page.evaluate('() => state.labs[0]')


def terminal_url(lab):
    node = next((n for n in lab['nodes'] if NODE_HINT in n['name']), lab['nodes'][0])
    return f"{BASE}/static/terminal.html#lab={lab['id']}&node={node['name']}&label={lab['name']}"


def connect_terminal(page, lab):
    page.goto(terminal_url(lab))
    page.wait_for_function('() => /Connected/.test(document.getElementById("status").textContent)', timeout=60000)
    page.wait_for_timeout(2500)
    target = page.locator('.xterm-helper-textarea')
    if target.count():
        target.first.focus()
    else:
        page.locator('.xterm').first.click()


def type_command(page, command, settle):
    page.keyboard.type(command, delay=15)
    page.keyboard.press('Enter')
    page.wait_for_timeout(settle)


def terminal_shot(page, lab):
    connect_terminal(page, lab)
    for command in COMMANDS:
        type_command(page, command, 3000)
    page.wait_for_timeout(1500)
    page.screenshot(path=os.path.join(OUT, 'ssh-terminal.png'))
    log('shot ssh-terminal')


def capture_shot(ctx, page, lab):
    open_lab(page)
    page.click('#tab-tools')
    page.wait_for_selector('#tools-view:not([hidden])')
    page.click('#capture-open')
    page.wait_for_selector('#capture-dialog[open]')
    page.wait_for_function('() => document.querySelectorAll("#capture-target option").length > 1', timeout=30000)
    picked = page.evaluate('''hint => { const sel = document.getElementById('capture-target');
      const opt = [...sel.options].find(o => o.textContent.includes(hint)) || [...sel.options].find(o => o.value);
      if (!opt) return null; sel.value = opt.value; sel.dispatchEvent(new Event('change', {bubbles: true})); return opt.textContent; }''', NODE_HINT)
    log('capture target:', picked)
    page.wait_for_function('() => document.querySelectorAll("#capture-interfaces input[type=checkbox], #capture-interfaces-all input[type=checkbox]").length > 0', timeout=60000)
    page.wait_for_timeout(500)
    ticked = page.evaluate('''wanted => { const out = [];
      const more = document.getElementById('capture-more'); if (more && !more.hidden) more.open = true;
      const boxes = [...document.querySelectorAll('#capture-interfaces input[type=checkbox], #capture-interfaces-all input[type=checkbox]')];
      for (const b of boxes) { const name = (b.value || b.closest('label')?.textContent || '').trim(); const want = wanted.includes(name);
        if (b.checked !== want) b.click(); if (want) out.push(name); }
      return out; }''', IFACES)
    log('interfaces ticked:', ticked)
    page.wait_for_function('() => !document.getElementById("capture-prepare").disabled', timeout=10000)
    page.click('#capture-prepare')
    page.wait_for_function('() => !document.getElementById("capture-launch").hidden', timeout=120000)
    url = page.evaluate('() => document.getElementById("capture-launch").href')
    log('session url:', url)
    page.goto(url)
    page.wait_for_function('() => /Connected to Wireshark/.test(document.getElementById("viewer-status").textContent)', timeout=120000)
    page.wait_for_timeout(6000)
    # traffic: a ping from the device in a second tab while the viewer keeps running
    term = ctx.new_page()
    try:
        connect_terminal(term, lab)
        term.keyboard.type(PING_COMMAND, delay=15)
        term.keyboard.press('Enter')
        log('ping started:', PING_COMMAND)
    except Exception as exc:
        log('ping step failed:', repr(exc)[:200])
    page.bring_to_front()
    for i, wait in enumerate((9000, 10000), start=1):
        page.wait_for_timeout(wait)
        page.screenshot(path=os.path.join(OUT, f'wireshark-in-browser-{i}.png'))
        log(f'shot wireshark-in-browser-{i}')
    try:
        term.keyboard.press('Control+C')
        term.close()
    except Exception:
        pass
    ended = page.evaluate('''async () => { const id = location.hash.slice(1);
      const r = await fetch('/api/capture/sessions/' + id + '/end', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'});
      return r.status; }''')
    log('session ended, status', ended)


def main():
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={'width': 1440, 'height': 900}, device_scale_factor=1)
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        lab = open_lab(page)
        try:
            terminal_shot(page, lab)
        except Exception as exc:
            log('terminal step failed:', repr(exc)[:300])
        try:
            capture_shot(ctx, page, lab)
        except Exception as exc:
            log('capture step failed:', repr(exc)[:300])
            try:
                page.screenshot(path=os.path.join(OUT, 'zz-capture-error.png'))
            except Exception:
                pass
        log('page errors:', errors)
        ctx.close()
        browser.close()


if __name__ == '__main__':
    main()
