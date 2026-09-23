import unittest

from app.textdiff import unified


class UnifiedDiffTests(unittest.TestCase):
    def test_no_change_is_identical_with_no_hunks(self):
        result = unified('a\nb\nc\n', 'a\nb\nc\n')
        self.assertTrue(result['identical'])
        self.assertEqual(result['hunks'], [])
        self.assertEqual(result['added'], 0)
        self.assertEqual(result['removed'], 0)
        self.assertFalse(result['truncated'])

    def test_one_hunk_for_a_single_changed_region(self):
        before = 'a\nb\nc\nd\ne\n'
        after = 'a\nb\nX\nd\ne\n'
        result = unified(before, after)
        self.assertFalse(result['identical'])
        self.assertEqual(len(result['hunks']), 1)
        hunk = result['hunks'][0]
        types = [row['type'] for row in hunk['lines']]
        self.assertIn('del', types)
        self.assertIn('add', types)
        self.assertEqual(result['added'], 1)
        self.assertEqual(result['removed'], 1)

    def test_multiple_hunks_for_distant_changes(self):
        before = '\n'.join(str(n) for n in range(30)) + '\n'
        after_lines = list(str(n) for n in range(30))
        after_lines[1] = 'CHANGED-TOP'
        after_lines[28] = 'CHANGED-BOTTOM'
        after = '\n'.join(after_lines) + '\n'
        result = unified(before, after, context=3)
        self.assertGreaterEqual(len(result['hunks']), 2)
        self.assertEqual(result['added'], 2)
        self.assertEqual(result['removed'], 2)

    def test_insert_at_top(self):
        result = unified('a\nb\n', 'new\na\nb\n')
        self.assertEqual(result['added'], 1)
        self.assertEqual(result['removed'], 0)
        add_rows = [row for hunk in result['hunks'] for row in hunk['lines'] if row['type'] == 'add']
        self.assertEqual(add_rows[0]['text'], 'new')
        self.assertIsNone(add_rows[0]['old'])
        self.assertEqual(add_rows[0]['new'], 1)

    def test_delete_at_end(self):
        result = unified('a\nb\nc\n', 'a\nb\n')
        self.assertEqual(result['removed'], 1)
        self.assertEqual(result['added'], 0)
        del_rows = [row for hunk in result['hunks'] for row in hunk['lines'] if row['type'] == 'del']
        self.assertEqual(del_rows[0]['text'], 'c')
        self.assertIsNone(del_rows[0]['new'])

    def test_long_lines_are_capped_but_not_dropped(self):
        long_line = 'x' * 5000
        result = unified('a\n', long_line + '\n')
        self.assertFalse(result['identical'])
        rows = [row for hunk in result['hunks'] for row in hunk['lines']]
        self.assertTrue(any(len(row['text']) <= 4000 for row in rows))

    def test_reordering_produces_delete_and_add_not_a_move(self):
        result = unified('a\nb\nc\n', 'c\nb\na\n')
        self.assertGreater(result['removed'], 0)
        self.assertGreater(result['added'], 0)

    def test_oversize_input_is_truncated_not_raised(self):
        before = '\n'.join(f'line{n}' for n in range(50)) + '\n'
        after = '\n'.join(f'line{n}x' for n in range(50)) + '\n'
        result = unified(before, after, max_lines=10)
        self.assertTrue(result['truncated'])
        self.assertFalse(result['identical'])

    def test_binary_content_is_reported_truncated(self):
        result = unified('a\n', 'b\x00inary\n')
        self.assertTrue(result['truncated'])
        self.assertIn('note', result)

    def test_crlf_is_preserved_as_text_not_normalised(self):
        before = 'a\r\nb\r\n'
        after = 'a\r\nB\r\n'
        result = unified(before, after)
        self.assertFalse(result['identical'])
        rows = [row for hunk in result['hunks'] for row in hunk['lines']]
        self.assertTrue(any(row['text'].endswith('\r') for row in rows if row['type'] in ('del', 'add')))

    def test_empty_before_is_all_additions(self):
        result = unified('', 'a\nb\n')
        self.assertEqual(result['removed'], 0)
        self.assertEqual(result['added'], 2)

    def test_empty_after_is_all_deletions(self):
        result = unified('a\nb\n', '')
        self.assertEqual(result['added'], 0)
        self.assertEqual(result['removed'], 2)


if __name__ == '__main__':
    unittest.main()
