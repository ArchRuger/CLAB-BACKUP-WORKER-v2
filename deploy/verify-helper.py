"""Check the installed helper's response without exposing deployment file contents."""
import json
import sys


def main():
    try:
        raw = sys.stdin.buffer.read(16 * 1024 * 1024 + 1)
        if len(raw) > 16 * 1024 * 1024: raise ValueError()
        data = json.loads(raw)
        expected = sys.argv[1]
        if (not isinstance(data, dict) or data.get('protocol') != 'clab-manager-files-v1'
                or data.get('helper_version') != expected or not isinstance(data.get('sources'), dict)
                or not isinstance(data.get('inspect'), (dict, list))):
            raise ValueError()
    except (ValueError, TypeError, IndexError):
        print('Helper verification failed; manager has not been recreated. Check the installed helper and Docker service.', file=sys.stderr)
        return 1
    print('Verified discovery/file helper ' + expected)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
