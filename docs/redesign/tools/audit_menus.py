import json
from playwright.sync_api import sync_playwright
BASE='http://127.0.0.1:8081'
with sync_playwright() as p:
    b=p.chromium.launch(); page=b.new_page(viewport={'width':1920,'height':1080})
    page.goto(BASE+'/',wait_until='networkidle'); page.wait_for_timeout(2000)
    page.click('[data-tab=topology]'); page.wait_for_timeout(1500)
    el=page.query_selector('#topology-map .map-device')
    el.dispatch_event('contextmenu', {'clientX': 640, 'clientY': 1000, 'button': 2}); page.wait_for_timeout(600)
    page.screenshot(path='shots/before/19-topology-context-menu--1920x1080.png')
    print('CONTEXT MENU:', page.evaluate("[...document.querySelectorAll('#node-context-menu button, #node-context-menu a, #node-context-menu strong, #node-context-menu p')].map(e=>e.tagName+': '+e.textContent.trim()+(e.disabled?' [disabled: '+e.title+']':''))"))
    page.keyboard.press('Escape'); page.wait_for_timeout(300)
    # link click
    link=page.query_selector('#topology-map .capture-hit') or page.query_selector('#topology-map .topology-wire')
    if link:
        link.dispatch_event('click'); page.wait_for_timeout(1200)
        print('LINK CLICK -> open dialogs:', page.evaluate("[...document.querySelectorAll('dialog[open]')].map(d=>d.id+': '+(d.querySelector('h2')?.textContent||''))"))
        page.evaluate("document.querySelectorAll('dialog[open]').forEach(d=>d.close())")
    page.click('#lab-actions'); page.wait_for_timeout(1200)
    page.screenshot(path='shots/before/23-lab-actions-menu--1920x1080.png')
    print('LAB ACTIONS:', page.evaluate("[...document.querySelectorAll('dialog[open] *')].filter(e=>['H2','H3','BUTTON','P','STRONG','SMALL','LABEL','A'].includes(e.tagName)).map(e=>e.tagName+(e.id?'#'+e.id:'')+': '+e.textContent.trim().replace(/\\s+/g,' ').slice(0,140)+(e.disabled?' [disabled: '+e.title+']':'')).filter(t=>t.split(': ')[1])"))
    b.close()
