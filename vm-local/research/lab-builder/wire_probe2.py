from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b=p.chromium.launch(); pg=b.new_context(viewport={'width':1440,'height':900}).new_page()
    pg.goto('http://127.0.0.1:8090/static/lab-builder.html#draft=new:wires'); pg.wait_for_timeout(5000)
    print(pg.evaluate("""()=>{const p=document.querySelector('path.react-flow__edge-path'); if(!p) return 'none'; const c=getComputedStyle(p); const svg=p.closest('svg'), s=getComputedStyle(svg); return JSON.stringify({d:p.getAttribute('d'),stroke:c.stroke,width:c.strokeWidth,opacity:c.opacity,inlineStyle:p.getAttribute('style'),svg:{cls:svg.getAttribute('class'),w:s.width,h:s.height,overflow:s.overflow,pos:s.position,maxw:s.maxWidth,disp:s.display}})}"""))
    b.close()
