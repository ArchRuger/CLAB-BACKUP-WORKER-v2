import os,sys
from playwright.sync_api import sync_playwright
BASE='http://127.0.0.1:8081'; lab,out=sys.argv[1],sys.argv[2]
with sync_playwright() as pw:
    b=pw.chromium.launch(); p=b.new_page(viewport={'width':1440,'height':1000})
    p.goto(f'{BASE}/#lab={lab}&view=progress'); p.wait_for_timeout(4000)
    if p.locator('#git-change-folder:not([open])').count(): p.locator('#git-change-folder > summary').click(); p.wait_for_timeout(2500)
    def show(label):
        print('===',label); print(p.locator('#git-places-panel').inner_text().replace('\n',' | '))
        for a in ('new','use'):
            x=p.locator(f'[data-git-places-action="{a}"]')
            if x.count(): print(f'[{a}] disabled={x.first.is_disabled()} title={x.first.get_attribute("title")!r}')
    p.locator('#git-places-panel nav.git-crumbs button').first.click(); p.wait_for_timeout(600); show('lab b: top level')
    p.screenshot(path=os.path.join(out,'fb-b-top.png'),full_page=True)
    p.locator('#git-places-panel tr.row.folder[data-git-place="git-redesign"]').first.click(); p.wait_for_timeout(700); show("lab b: looking at lab a's folder git-redesign")
    p.screenshot(path=os.path.join(out,'fb-b-other-lab-folder.png'),full_page=True)
    p.locator('#git-places-panel tr.row.folder[data-git-place="git-redesign/b"]').first.click(); p.wait_for_timeout(700); show("lab b: its own folder git-redesign/b")
    b.close()
