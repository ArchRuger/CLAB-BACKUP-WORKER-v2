"""Keep setup output free of host inspection/source contents."""
import json
import sys

def verify(raw, version):
    if len(raw) > 1024 * 1024: raise ValueError('Oversized operations response.')
    value = json.loads(raw).get('result', {})
    if value.get('protocol') != 'clab-manager-operations-v1' or value.get('version') != version:
        raise ValueError('Operations helper version mismatch.')
    if not isinstance(value.get('actions'), dict): raise ValueError('Missing operation capabilities.')
    return value['version']

if __name__ == '__main__':
    try: print('Operations helper verified: ' + verify(sys.stdin.buffer.read(1024 * 1024 + 1), sys.argv[1]))
    except Exception: sys.exit('Operations preflight failed. Check setup-operations.sh before recreating the manager.')
