"""The vendored containerlab topology schemas (app/static/clab-schema/; docs/parity-campaign/C08-DESIGN.md §5).

Standard library only, so it runs in CI's first group with the system python3. The expected digests are literals of
this file: a schema refresh changes this test in the same reviewed diff, never only SOURCES.txt (which the fetch
script writes), and a tampered checkout changes a digest this file does not.
"""
import hashlib
import json
from pathlib import Path
import re
import unittest

APP = Path(__file__).resolve().parents[1]
FOLDER = APP / 'app' / 'static' / 'clab-schema'
CHECK = APP / 'app' / 'static' / 'lab-builder-check.js'
FETCH = APP / 'lab-builder' / 'fetch-schema.mjs'
# containerlab v0.79.0 schemas/clab.schema.json, verified against GitHub when it was vendored (C08-DESIGN.md §0).
EXPECTED = {'0.79.0.json': '51a7025041d90fcded90911d4947773794464ccd903f01c03d5b2ff988f58d02'}
RAW = 'https://raw.githubusercontent.com/srl-labs/containerlab/'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    """SOURCES.txt rows as {file: (tag, url, sha256, date)}; comment lines skipped."""
    rows = {}
    for line in (FOLDER / 'SOURCES.txt').read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'):
            continue
        fields = line.split('  ')
        assert len(fields) == 5, line
        name, tag, url, checksum, fetched = fields
        assert checksum.startswith('sha256 ') and fetched.startswith('fetched '), line
        assert name not in rows, f'{name} is listed twice'
        rows[name] = (tag, url, checksum[len('sha256 '):], fetched[len('fetched '):])
    return rows


class VendoredSchema(unittest.TestCase):
    def test_every_file_in_sources_exists_with_its_digest(self):
        rows = sources()
        self.assertIn('LICENSE', rows)
        for name, (tag, url, checksum, fetched) in rows.items():
            self.assertTrue((FOLDER / name).is_file(), name)
            self.assertEqual(digest(FOLDER / name), checksum, name)
            self.assertRegex(tag, r'^v\d+\.\d+\.\d+$')
            self.assertTrue(url.startswith(RAW), url)
            self.assertRegex(fetched, r'^\d{4}-\d{2}-\d{2}$')
            if name.endswith('.json'):
                self.assertEqual(name, tag[1:] + '.json')
                self.assertTrue(url.endswith('/schemas/clab.schema.json'), url)
            else:
                self.assertTrue(url.endswith('/LICENSE'), url)

    def test_every_schema_file_is_listed_and_pinned_here(self):
        files = sorted(p.name for p in FOLDER.glob('*.json'))
        self.assertEqual(files, sorted(EXPECTED))
        self.assertEqual(sorted(n for n in sources() if n.endswith('.json')), files)
        self.assertEqual(sorted(p.name for p in FOLDER.iterdir()), sorted(files + ['LICENSE', 'SOURCES.txt']))
        for name, checksum in EXPECTED.items():
            self.assertEqual(digest(FOLDER / name), checksum, name)
            self.assertEqual(sources()[name][2], checksum, name)

    def test_each_schema_is_containerlabs_topology_schema(self):
        for name in EXPECTED:
            data = json.loads((FOLDER / name).read_text(encoding='utf-8'))
            self.assertEqual(data['$id'], 'https://containerlab.dev/clab.schema.json')
            self.assertEqual(data['type'], 'object')
            self.assertIsInstance(data['definitions']['node-config'], dict)
            self.assertIsInstance(data['properties']['topology'], dict)

    def test_the_licence_is_containerlabs_bsd_licence(self):
        text = (FOLDER / 'LICENSE').read_text(encoding='utf-8')
        self.assertIn('Redistribution and use', text)
        self.assertIn('Nokia', text)

    def test_the_validator_lists_exactly_the_vendored_versions(self):
        source = CHECK.read_text(encoding='utf-8')
        match = re.search(r"^const BUILDER_SCHEMA_VERSIONS=\[([^\]]*)\];", source, re.M)
        self.assertIsNotNone(match)
        versions = re.findall(r"'([^']*)'", match.group(1))
        self.assertEqual(sorted(v + '.json' for v in versions), sorted(EXPECTED))
        for v in versions:
            self.assertRegex(v, r'^\d+\.\d+\.\d+$')


class FetchScript(unittest.TestCase):
    source = FETCH.read_text(encoding='utf-8')

    def test_names_the_raw_url_and_requires_a_pinned_digest_or_commit(self):
        self.assertIn('const RAW = "https://raw.githubusercontent.com/srl-labs/containerlab";', self.source)
        self.assertIn('/schemas/clab.schema.json`', self.source)
        self.assertIn(r'const TAG = /^v\d+\.\d+\.\d+$/', self.source)
        self.assertIn('if (!TAG.test(tag)) fail(', self.source)
        self.assertIn('if (!expected && !commit) fail(', self.source)
        self.assertIn('if (expected && digest !== expected) fail(', self.source)
        self.assertIn('COMMIT = /^[0-9a-f]{40}$/', self.source)
        self.assertIn('redirect: "error"', self.source)
        # The tag is checked before a path or a URL is derived from it.
        self.assertLess(self.source.index('if (!TAG.test(tag))'), self.source.index('const version = tag.slice(1)'))
        self.assertLess(self.source.index('if (expected && digest !== expected)'), self.source.index('put(file, schema)'))

    def test_writes_only_its_three_files_in_the_schema_folder(self):
        self.assertIn('resolve(dirname(fileURLToPath(import.meta.url)), "../app/static/clab-schema")', self.source)
        # Every write goes through put(name, …) into `out`; put is called for the three file names only.
        self.assertEqual(re.findall(r'writeFileSync\(([^,]+),', self.source), ['part'])
        self.assertEqual(re.findall(r'renameSync\(([^)]+)\)', self.source), ['part, target'])
        self.assertIn('const target = join(out, name)', self.source)
        self.assertEqual(sorted(re.findall(r'(?<!function )\bput\(("[^"]+"|\w+),', self.source)), sorted(['file', '"LICENSE"', '"SOURCES.txt"']))
        self.assertIn('const file = `${version}.json`', self.source)
        for word in ('unlinkSync', 'rmSync', 'appendFileSync', 'child_process', 'eval(', 'new Function', 'import('):
            self.assertNotIn(word, self.source)
        # The download is data: JSON.parse, never a module import.
        self.assertIn('JSON.parse(schema.toString("utf8"))', self.source)

    def test_never_replaces_a_vendored_release(self):
        # The behaviour is the comparison of the bytes already on disk with the download, and it runs, with a failure
        # that stops the script, before the first put(file, schema) can write anything.
        compare = 'if (!readFileSync(existing).equals(schema)) fail('
        self.assertIn('const file = `${version}.json`, existing = join(out, file);', self.source)
        self.assertIn('if (existsSync(existing)) {', self.source)
        self.assertIn(compare, self.source)
        self.assertIn('a vendored release is never replaced', self.source)
        self.assertEqual(self.source.count('put(file, schema)'), 1)
        self.assertLess(self.source.index('if (existsSync(existing)) {'), self.source.index(compare))
        self.assertLess(self.source.index(compare), self.source.index('put(file, schema)'))
        # Identical bytes end the run without a write; nothing else can fall through to the writes.
        identical = self.source.index('nothing written.`);', self.source.index(compare))
        self.assertLess(identical, self.source.index('put(file, schema)'))
        self.assertIn('process.exit(0);', self.source[identical:self.source.index('put(file, schema)')])


if __name__ == '__main__':
    unittest.main()
