import copy
import json
import unittest
from app.layout import arrange, annotations, decorations
from app.topology import grid_position, parse_drawing


def drawing(names, pairs, positions=None):
    nodes = []
    for i, name in enumerate(names):
        x, y = (positions or {}).get(name, grid_position(i))
        nodes.append({'id': name, 'alias': name, 'label': name, 'x': x, 'y': y})
    links = [[{'node': a, 'interface': 'eth1'}, {'node': b, 'interface': 'eth1'}] for a, b in pairs]
    return {'schema': 3, 'nodes': nodes, 'links': links, 'decorations': [], 'placed': False, 'settings': {}}


class ArrangeTests(unittest.TestCase):
    def check_sane(self, d, result):
        self.assertEqual(sorted(result), sorted(n['id'] for n in d['nodes']))
        points = set()
        for x, y in result.values():
            self.assertIs(type(x), int)
            self.assertIs(type(y), int)
            self.assertLessEqual(abs(x), 100000)
            self.assertLessEqual(abs(y), 100000)
            points.add((x, y))
        self.assertEqual(len(points), len(result), 'no two nodes share a point')

    def test_modes_validated(self):
        d = drawing(['a', 'b'], [('a', 'b')])
        for bad in ('diagonal', '', None, 'Rows'):
            with self.assertRaises(ValueError) as caught:
                arrange(d, bad)
            self.assertEqual(str(caught.exception), 'Choose rows, columns or a ring.')

    def test_chain_rows_one_layer_per_row(self):
        d = drawing(['a', 'b', 'c'], [('a', 'b'), ('b', 'c')])
        r = arrange(d, 'rows')
        self.check_sane(d, r)
        # root is the node with most links (b); a and c are its layer 1.
        self.assertEqual(r['b'][1], 0)
        self.assertEqual(r['a'][1], 120)
        self.assertEqual(r['c'][1], 120)
        self.assertLess(r['a'][0], r['c'][0])
        self.assertEqual(r['b'][0], (r['a'][0] + r['c'][0]) // 2)

    def test_star_rows_centre_on_the_widest_row(self):
        d = drawing(['hub', 'a', 'b', 'c'], [('hub', 'a'), ('hub', 'b'), ('hub', 'c')])
        r = arrange(d, 'rows')
        self.check_sane(d, r)
        self.assertEqual(list(r['hub']), [160, 0])
        self.assertEqual([r[k][0] for k in 'abc'], [0, 160, 320])
        self.assertTrue(all(r[k][1] == 120 for k in 'abc'))

    def test_columns_are_rows_turned(self):
        d = drawing(['hub', 'a', 'b', 'c'], [('hub', 'a'), ('hub', 'b'), ('hub', 'c')])
        rows, columns = arrange(d, 'rows'), arrange(d, 'columns')
        for k in rows:
            self.assertEqual(list(columns[k]), [rows[k][1], rows[k][0]])

    def test_two_components_sit_side_by_side_largest_first(self):
        d = drawing(['x', 'y', 'a', 'b', 'c'], [('x', 'y'), ('a', 'b'), ('b', 'c')])
        r = arrange(d, 'rows')
        self.check_sane(d, r)
        self.assertLess(max(r[k][0] for k in 'abc'), min(r[k][0] for k in 'xy'))
        self.assertGreaterEqual(min(r[k][0] for k in 'xy') - max(r[k][0] for k in 'abc'), 320)

    def test_isolated_nodes_make_a_last_row(self):
        d = drawing(['a', 'b', 'i1', 'i2'], [('a', 'b')])
        r = arrange(d, 'rows')
        self.check_sane(d, r)
        self.assertEqual(r['i1'][1], r['i2'][1])
        self.assertGreater(r['i1'][1], max(r['a'][1], r['b'][1]))
        self.assertEqual(r['i2'][0] - r['i1'][0], 160)

    def test_unlinked_one_row_equals_the_default_grid(self):
        d = drawing(['n%d' % i for i in range(5)], [])
        r = arrange(d, 'rows')
        self.assertEqual({k: tuple(v) for k, v in r.items()}, {'n%d' % i: grid_position(i) for i in range(5)})

    def test_ring_surrounds_the_current_centre(self):
        names = ['n%d' % i for i in range(6)]
        pos = {n: (1000 + (i % 3) * 100, 2000 + (i // 3) * 100) for i, n in enumerate(names)}
        d = drawing(names, [], pos)
        r = arrange(d, 'ring')
        self.check_sane(d, r)
        cx = sum(v[0] for v in r.values()) / 6
        cy = sum(v[1] for v in r.values()) / 6
        self.assertAlmostEqual(cx, 1100, delta=3)
        self.assertAlmostEqual(cy, 2050, delta=3)
        self.assertGreaterEqual(max(v[0] for v in r.values()) - min(v[0] for v in r.values()), 200)

    def test_single_node_ring_and_rows(self):
        d = drawing(['only'], [])
        self.check_sane(d, arrange(d, 'ring'))
        self.check_sane(d, arrange(d, 'rows'))

    def test_deterministic_and_pure(self):
        d = drawing(['a', 'b', 'c', 'd'], [('a', 'b'), ('b', 'c'), ('c', 'a'), ('c', 'd')])
        before = copy.deepcopy(d)
        for mode in ('rows', 'columns', 'ring'):
            self.assertEqual(arrange(d, mode), arrange(d, mode))
        self.assertEqual(d, before, 'arrange never mutates the drawing')

    def test_links_to_unknown_nodes_and_self_links_are_ignored(self):
        d = drawing(['a', 'b'], [('a', 'b'), ('a', 'a'), ('a', 'ghost')])
        self.check_sane(d, arrange(d, 'rows'))

    def test_large_star_stays_within_bounds(self):
        names = ['n%d' % i for i in range(1500)]
        d = drawing(names, [('n0', n) for n in names[1:]])
        for mode in ('rows', 'columns', 'ring'):
            r = arrange(d, mode)
            self.assertEqual(sorted(r), sorted(names))
            self.assertTrue(all(abs(v) <= 100000 for p in r.values() for v in p))


class DecorationAndAnnotationTests(unittest.TestCase):
    def test_decorations_accept_and_bound_new_keys(self):
        row = decorations([{'type': 'line', 'x': 0, 'y': 0, 'lineStartArrow': True, 'lineEndArrow': 'yes',
                            'lineArrowSize': 12, 'roundedBackground': False, 'level': 3}])[0]
        self.assertIs(row['lineStartArrow'], True)
        self.assertIs(row['lineEndArrow'], False)
        self.assertEqual(row['lineArrowSize'], 12)
        self.assertIs(row['roundedBackground'], False)
        self.assertEqual(row['level'], 3)
        defaults = decorations([{'type': 'text', 'x': 0, 'y': 0}])[0]
        self.assertIs(defaults['roundedBackground'], True)
        self.assertEqual(defaults['lineArrowSize'], 10)
        self.assertEqual(defaults['level'], 1)
        for key, value in (('lineArrowSize', 3), ('lineArrowSize', 41), ('level', 0), ('level', 11)):
            with self.assertRaises(ValueError):
                decorations([{'type': 'line', 'x': 0, 'y': 0, key: value}])

    def test_annotations_round_trip_the_new_keys(self):
        raw = json.dumps({
            'nodeAnnotations': [{'id': 'r1', 'position': {'x': 1, 'y': 2}}],
            'freeShapeAnnotations': [{'shapeType': 'line', 'position': {'x': 0, 'y': 0}, 'lineStartArrow': True,
                                      'lineEndArrow': True, 'lineArrowSize': 20}],
            'freeTextAnnotations': [{'text': 'n', 'position': {'x': 0, 'y': 0}, 'roundedBackground': False}],
            'groupStyleAnnotations': [{'name': 'g', 'position': {'x': 0, 'y': 0}, 'level': 4}],
            'viewerSettings': {'nodeStyle': 'boxed', 'boxSpacing': 'narrow', 'linkStyle': 'elbow'}}).encode()
        d = parse_drawing(raw)
        out = annotations(d)
        self.assertEqual(out['freeShapeAnnotations'][0]['lineArrowSize'], 20)
        self.assertIs(out['freeShapeAnnotations'][0]['lineStartArrow'], True)
        self.assertIs(out['freeShapeAnnotations'][0]['lineEndArrow'], True)
        self.assertIs(out['freeTextAnnotations'][0]['roundedBackground'], False)
        self.assertEqual(out['groupStyleAnnotations'][0]['level'], 4)
        self.assertEqual({k: out['viewerSettings'][k] for k in ('nodeStyle', 'boxSpacing', 'linkStyle')},
                         {'nodeStyle': 'boxed', 'boxSpacing': 'narrow', 'linkStyle': 'elbow'})
        again = parse_drawing(json.dumps(out).encode())
        new = ('lineStartArrow', 'lineEndArrow', 'lineArrowSize', 'roundedBackground', 'level')
        pick = lambda items: [{k: v for k, v in i.items() if k in new} for i in items]
        self.assertEqual(pick(again['decorations']), pick(d['decorations']))
        self.assertEqual(again['settings'], d['settings'])


if __name__ == '__main__':
    unittest.main()
