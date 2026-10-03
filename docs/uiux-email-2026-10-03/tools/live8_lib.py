"""Task 8 live helpers: reuses live_lib with a fresh profile under the live8 scratch folder."""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(__file__))
import live_lib
from live_lib import *
S8 = '/tmp/claude-1000/-home-archtop-CLAB-Two-Worker-Kit/9c1d6dac-d5ed-49d8-805d-d33fd62bbeaa/scratchpad/live8'
live_lib.S = S8; live_lib.RES = S8 + '/results.jsonl'
LABID = '22af301586f848d59bdaeb046b9c19b5'
live_lib.LAB = 'UX-ACCEPT-01'
def new_sess(p, w=1600, h=1000, fresh=False):
    import shutil
    if fresh: shutil.rmtree(S8 + '/profile', ignore_errors=True)
    s = live_lib.Sess(p, w, h); return s
def api(pg, method, path, body=None):
    js = """async ([m,p,b]) => { const o={method:m,headers:{'Origin':location.origin}}; if(b!==null){o.headers['Content-Type']='application/json'; o.body=JSON.stringify(b);} const r=await fetch(p,o); let t=await r.text(); let j=null; try{j=JSON.parse(t)}catch(e){} return {status:r.status, json:j, text:t.slice(0,300)} }"""
    return pg.evaluate(js, [method, path, body])
def open_lab(pg, view='advanced'):
    pg.goto(f'{BASE}/#lab={LABID}&view={view}'); pg.wait_for_timeout(2500)
def record(step, ok, detail=''):
    live_lib.record(step, ok, detail)
