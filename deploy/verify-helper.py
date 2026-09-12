"""Check the installed helper's response without exposing deployment file contents."""
import json
import re
import sys


def main():
    try:
        raw = sys.stdin.buffer.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024: raise ValueError('Discovery helper response exceeded the size limit.')
        if not raw.strip(): raise ValueError('Discovery helper returned no response. Check its installation and Docker service.')
        data = json.loads(raw)
        expected = sys.argv[1]
        if not isinstance(data, dict) or data.get('protocol') != 'clab-manager-files-v1':
            raise ValueError('Discovery helper returned an unsupported protocol.')
        if data.get('helper_version') != expected:
            def safe_version(value):
                return value if isinstance(value, str) and re.fullmatch(r'\d+\.\d+\.\d+', value) else '(missing or invalid)'
            raise ValueError('Discovery helper version mismatch: source VERSION expects ' + safe_version(expected)
                             + ', installed helper reports ' + safe_version(data.get('helper_version')) + '. Use matching release files.')
        if not isinstance(data.get('sources'), dict) or not isinstance(data.get('inspect'), (dict, list)):
            raise ValueError('Discovery helper returned an invalid inventory/source structure.')
    except json.JSONDecodeError:
        print('Discovery helper returned invalid JSON; manager has not been recreated. Check the helper and Docker service.', file=sys.stderr)
        return 1
    except (ValueError, TypeError, IndexError) as error:
        print(str(error) + ' Manager has not been recreated.', file=sys.stderr)
        return 1
    print('Verified discovery/file helper ' + expected)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
