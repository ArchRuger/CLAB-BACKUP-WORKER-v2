import json, pathlib
from playwright.sync_api import sync_playwright
BASE='http://127.0.0.1:8081'
OUT=pathlib.Path('shots/before'); OUT.mkdir(parents=True,exist_ok=True)
rep={'failures':[],'text':{}}
ITEMS=[('#operations-history','09-operation-history'),('#inspect-all','10-inspect-all'),('#vm-settings','11-vm-connection'),('#manager-settings','12-manager-settings'),('#new-lab','13-manual-discovery'),('#update-definition','14-update-yaml'),('#link-deployment','15-link-deployment'),('#export-sessions','16-export-sessions'),('#import-map','17-import-map'),('#lab-destroy','18-destroy-dialog'),('#remove-lab','18b-remove-lab'),('#vm-refresh','18c-vm-refresh'),('#map-edit','20-diagram-editor'),('#git-repository-refresh','22-git-tab-refresh')]
def vis(page):
    return page.evaluate("""() => Array.from(new Set([...document.querySelectorAll('dialog[open] *, .deploy-view *, main *')].filter(el=>['BUTTON','A','H1','H2','H3','LABEL','SUMMARY','P','STRONG','SMALL','LEGEND'].includes(el.tagName)&&(el.offsetParent!==null||el.closest('dialog[open]'))).map(el=>el.tagName.toLowerCase()+(el.id?'#'+el.id:'')+': '+(el.innerText||el.textContent||'').trim().replace(/\\s+/g,' ').slice(0,140)+(el.disabled?' [disabled'+(el.title?': '+el.title:'')+']':'')).filter(t=>t.split(': ')[1])))""")
with sync_playwright() as p:
    b=p.chromium.launch()
    for vp in [(1920,1080),(1366,768)]:
        ctx=b.new_context(viewport={'width':vp[0],'height':vp[1]}); page=ctx.new_page()
        for sel,name in ITEMS:
            try:
                page.goto(BASE+'/',wait_until='networkidle'); page.wait_for_timeout(2000)
                if sel in ('#map-edit',): page.click('[data-tab=topology]'); page.wait_for_timeout(1200)
                if sel=='#git-repository-refresh': page.click('[data-tab=git]'); page.wait_for_timeout(1500)
                page.click(sel,timeout=4000); page.wait_for_timeout(2000)
                page.screenshot(path=str(OUT/f'{name}--{vp[0]}x{vp[1]}.png'))
                if vp[0]==1920: rep['text'][name]=vis(page)
            except Exception as e: rep['failures'].append(f'{name}@{vp}: {str(e)[:120]}')
        # deploy page text + topology context menu via dispatch
        try:
            page.goto(BASE+'/',wait_until='networkidle'); page.wait_for_timeout(2000)
            page.click('#vm-projects'); page.wait_for_timeout(2500)
            if vp[0]==1920: rep['text']['08-deploy-new-lab']=vis(page)
            page.goto(BASE+'/',wait_until='networkidle'); page.wait_for_timeout(2000)
            page.click('[data-tab=topology]'); page.wait_for_timeout(1500)
            info=page.evaluate("""() => { const svg=document.getElementById('topology-map'); const g=[...svg.querySelectorAll('g,circle,rect,text')].filter(e=>e.dataset&&Object.keys(e.dataset).length); return {count:svg.childElementCount, sample:g.slice(0,6).map(e=>e.tagName+' '+JSON.stringify(e.dataset)), classes:[...new Set([...svg.querySelectorAll('*')].map(e=>e.getAttribute('class')).filter(Boolean))].slice(0,30)} }""")
            rep['topology_dom']=info
            el=page.query_selector('#topology-map [data-node], #topology-map g.node, #topology-map .node')
            if el:
                el.click(button='right'); page.wait_for_timeout(700)
                page.screenshot(path=str(OUT/f'19-topology-context-menu--{vp[0]}x{vp[1]}.png'))
                if vp[0]==1920: rep['text']['19-context']=page.evaluate("[...document.querySelectorAll('#node-context-menu *')].map(e=>e.tagName+': '+e.textContent.trim()).filter(t=>t.split(': ')[1])")
            else: rep['failures'].append(f'ctx-no-node@{vp}')
        except Exception as e: rep['failures'].append(f'extra@{vp}: {str(e)[:120]}')
        ctx.close()
    b.close()
(OUT/'audit-rest.json').write_text(json.dumps(rep,indent=1))
print('failures:',rep['failures']); print('topology:',json.dumps(rep.get('topology_dom'))[:800])
for k,v in rep['text'].items(): print('\n##',k); print('\n'.join(v[:60]))
