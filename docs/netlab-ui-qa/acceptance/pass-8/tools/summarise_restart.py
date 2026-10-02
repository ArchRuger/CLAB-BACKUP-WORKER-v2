#!/usr/bin/env python3
"""Summarise a check_restart_device.py JSON record: per run the job, its times and message, links after, the
target's container id before/after, and the readiness timeline. Usage: summarise_restart.py <record.json>"""
import json, sys
d = json.load(open(sys.argv[1]))
print('record', sys.argv[1], 'device', d.get('device'), 'kind', d.get('kind'), 'started', d.get('started'), 'finished', d.get('finished'))
tgt = d.get('label') or ''
for name, r in (d.get('runs') or {}).items():
    job = r.get('job') or {}
    b = (r.get('before') or {}); a = (r.get('after') or {})
    key = d.get('device') if d.get('device') in b else None
    print('run', name, 'entry', r.get('entry'))
    print('  job', (job.get('id') or '')[:8], job.get('status'), job.get('created'), job.get('finished'), '|', job.get('message'))
    if key: print('  container', b[key]['id'][:12], '->', (a.get(key) or {}).get('id', '')[:12], 'start', b[key]['started'], '->', (a.get(key) or {}).get('started'))
    others = [k for k in b if k != key]
    print('  others unchanged', all(b[k].get('id') == (a.get(k) or {}).get('id') and b[k].get('started') == (a.get(k) or {}).get('started') for k in others if a))
    la = r.get('links_after') or []
    print('  links after', [x for x in la if x.startswith('eth')])
    for k in ('readiness', 'timeline', 'states', 'readiness_timeline'):
        if k in r: print('  ' + k, json.dumps(r[k])[:900])
    extra = [k for k in r if k not in ('before', 'after', 'links_before', 'links_after', 'job', 'entry', 'design_before', 'design_after')]
    print('  other keys', extra)
print('checks', len(d.get('checks', [])), 'failed', sum(1 for c in d.get('checks', []) if not c.get('ok')))
for c in d.get('checks', []):
    if not c.get('ok'): print('  FAIL', c.get('name'), str(c.get('detail'))[:300])
for rv in (d.get('reviews') or {}).items():
    print('review', json.dumps(rv)[:600])
