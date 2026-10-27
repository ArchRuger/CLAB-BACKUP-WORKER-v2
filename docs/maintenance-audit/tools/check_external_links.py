#!/usr/bin/env python3
"""Check the external links of the living guides and say why each unresolved one failed.

`check_links.py` resolves relative links and anchors; this tool supplements it for `http(s)` URLs. Every URL
found in the living guides (README.md, docs/*.md, deploy/*.md, clab-backup-ui/README.md, NODE-FEATURES.md) is
fetched once (HEAD, then GET on 405/403/404) with a bounded timeout, and the outcome is classified so a dead
link is told apart from one that answers but refuses an anonymous client:

    ok            2xx or 3xx
    placeholder   a token the reader replaces (VM_IP, OWNER/REPOSITORY): not fetched
    auth          401, 403, 407 (the page exists but wants a login or refuses robots)
    rate-limited  429
    not-found     404, 410 (a dead link, unless the site answers 404 for a HEAD only: GET is tried first)
    server-error  5xx (transient until proven otherwise; rerun before calling it dead)
    unreachable   DNS failure, connection refused, TLS error, timeout

    python3 docs/maintenance-audit/tools/check_external_links.py              # table on stdout, exit 1 when any not-found
    python3 docs/maintenance-audit/tools/check_external_links.py --all-md     # every tracked Markdown file, history included
    python3 docs/maintenance-audit/tools/check_external_links.py --write docs/parity-campaign/EXTERNAL-LINKS.md

Standard library only; run from anywhere inside the checkout. Localhost, private addresses and example hosts
(`example.com`, `192.0.2.*`, `*.local`, `127.*`, `192.168.*`, `172.16-31.*`, `10.*`) are listed as `skipped`.
"""
import argparse
import re
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit

LIVING = ('README.md', 'clab-backup-ui/README.md', 'clab-backup-ui/NODE-FEATURES.md')
LIVING_GLOBS = ('docs/*.md', 'deploy/*.md', 'deploy/**/*.md')
URL = re.compile(r'https?://[^\s<>()\[\]"\'`]+')
SKIP = re.compile(r'^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|192\.0\.2\.|198\.51\.100\.|203\.0\.113\.|example\.(com|org|net)|.*\.local$|.*\.lan$|.*\.internal$|<)')
UA = 'clab-manager-docs-link-check/1 (+https://github.com/ArchRuger/CLAB-BACKUP-WORKER-v2)'


def checkout_root():
    return Path(subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True, check=True).stdout.strip())


def files(root, all_md):
    if all_md:
        out = subprocess.run(['git', 'ls-files', '-z', '*.md', '**/*.md'], cwd=root, capture_output=True, text=True, check=True).stdout
        return sorted(p for p in out.split('\0') if p)
    found = [p for p in LIVING if (root / p).is_file()]
    for pattern in LIVING_GLOBS:
        found.extend(str(p.relative_to(root)) for p in root.glob(pattern) if p.is_file())
    return sorted(set(found))


def urls(root, paths):
    seen = {}
    for path in paths:
        text = (root / path).read_text(encoding='utf8', errors='replace')
        for number, line in enumerate(text.splitlines(), 1):
            for match in URL.findall(line):
                url = match.rstrip('.,;:!?*_)>')
                while url.endswith(')') and url.count(')') > url.count('('): url = url[:-1]
                seen.setdefault(url, []).append('%s:%d' % (path, number))
    return seen


PLACEHOLDER = re.compile(r'(^|[/.:@])[A-Z][A-Z0-9_]{2,}([/.:@]|$)')


def fetch(url, timeout):
    host = urlsplit(url).hostname or ''
    if SKIP.match(host) or '.' not in host: return 'skipped', '', 'local, private or example host (a name without a dot: a compose service or an example VM name)'
    # A placeholder the reader replaces (http://VM_IP:8081, https://github.com/OWNER/REPOSITORY.git) is not a link.
    if PLACEHOLDER.search(urlsplit(url).netloc) or PLACEHOLDER.search(urlsplit(url).path): return 'placeholder', '', 'a token the reader replaces'
    context = ssl.create_default_context()
    for method in ('HEAD', 'GET'):
        request = urllib.request.Request(url, method=method, headers={'User-Agent': UA, 'Accept': '*/*'})
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=context) as answer:
                return 'ok', str(answer.status), ''
        except urllib.error.HTTPError as exc:
            code = exc.code
            if method == 'HEAD' and code in (403, 404, 405, 501): continue
            if code in (401, 403, 407): return 'auth', str(code), 'answers, but refuses an anonymous client'
            if code == 429: return 'rate-limited', str(code), 'answers, but throttles: rerun later'
            if code in (404, 410): return 'not-found', str(code), 'the page is gone or the address is wrong'
            if 500 <= code < 600: return 'server-error', str(code), 'the server failed: transient until a rerun agrees'
            return 'other', str(code), exc.reason if isinstance(exc.reason, str) else ''
        except urllib.error.URLError as exc:
            reason = str(exc.reason)
            return 'unreachable', '', reason[:120]
        except (TimeoutError, ssl.SSLError, ConnectionError, OSError) as exc:
            return 'unreachable', '', str(exc)[:120]
    return 'other', '', ''


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--all-md', action='store_true')
    parser.add_argument('--write', metavar='PATH', help='write the Markdown table to this path (relative to the checkout)')
    parser.add_argument('--timeout', type=float, default=12.0)
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    root = checkout_root()
    found = urls(root, files(root, args.all_md))
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = dict(zip(found, pool.map(lambda u: fetch(u, args.timeout), found)))
    counts = Counter(status for status, _, _ in results.values())
    lines = ['# External links of the living guides', '',
             'Generated by `docs/maintenance-audit/tools/check_external_links.py`%s. Statuses: ok, auth (answers, refuses an' % (' (--all-md)' if args.all_md else ''),
             'anonymous client), rate-limited, not-found (dead), server-error (transient until a rerun agrees), unreachable, placeholder, skipped.', '',
             'Counts: ' + ', '.join('%s %d' % (k, v) for k, v in sorted(counts.items())) + ', total %d.' % len(results), '',
             '| URL | Status | Code | Reason | Where |', '|---|---|---|---|---|']
    for url in sorted(results, key=lambda u: (results[u][0] == 'ok', u)):
        status, code, reason = results[url]
        where = ', '.join(found[url][:3]) + (' (+%d)' % (len(found[url]) - 3) if len(found[url]) > 3 else '')
        lines.append('| %s | %s | %s | %s | %s |' % (url.replace('|', '%7C'), status, code, reason.replace('|', '/'), where.replace('|', '/')))
    text = '\n'.join(lines) + '\n'
    if args.write:
        (root / args.write).write_text(text); print('Wrote %s (%d links; %s).' % (args.write, len(results), ', '.join('%s %d' % (k, v) for k, v in sorted(counts.items()))))
    else:
        sys.stdout.write(text)
    return 1 if counts.get('not-found') else 0


if __name__ == '__main__':
    sys.exit(main())
