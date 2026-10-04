"""Prints where lab git-redesign-b saves, its waiting count, the planned folders and what is on GitHub (step 17 helper)."""
import sys, json
sys.path.insert(0, 'docs/git-redesign/tools/live')
from l1lib import *
label = sys.argv[1] if len(sys.argv) > 1 else ''
st = mgr.call('GET', '/api/state')[1]
lab = [l for l in st['labs'] if l['name'] == 'git-redesign-b'][0]
g = mgr.call('GET', f'/api/labs/{lab["id"]}/git')[1]
print(f'  [state {label}] GET /api/labs/{lab["id"][:8]}../git -> binding prefix:', (g.get('binding') or {}).get('repository', {}).get('prefix'))
print('     git_status:', lab.get('git_status'))
print('     git jobs (newest 4):', [(j['status'], j.get('note'), j.get('target'), (j.get('destination') or {}).get('path')) for j in g.get('jobs', [])][:4])
github(label)
print('     slug folders on GitHub:', sorted({'/'.join(p.split('/')[:3]) for p in gh_tree('l1-scaffold/')}))
sa = mgr.call('GET', f'/api/labs/{lab["id"]}/restore/states')[1]
print('     restore/states with l1-scaffold:', [(x['name'], x['group'], x['path'], x['lab'], x['saved_devices']) for x in sa['states'] if 'scaffold' in x['path']])
