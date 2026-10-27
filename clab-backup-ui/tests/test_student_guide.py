"""The student quick start served by the manager (campaign 2 D10): the Help entry's flag and the PDF route."""
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import GUIDE_NAME, create_app, guide_path


class StudentGuideTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.app = create_app(self.tmp.name); self.client = TestClient(self.app)
        self.headers = {'Origin': 'http://testserver'}

    def tearDown(self): self.tmp.cleanup()

    def test_without_the_pdf_the_flag_is_false_and_the_route_is_404(self):
        self.assertIsNone(guide_path(self.root))
        self.assertIs(self.client.get('/api/state', headers=self.headers).json()['student_guide'], False)
        answer = self.client.get('/student-guide')
        self.assertEqual(answer.status_code, 404); self.assertIn('not installed', answer.json()['detail'])

    def test_with_the_pdf_the_flag_is_true_and_the_route_serves_it_inline(self):
        (self.root / 'guide').mkdir(); (self.root / 'guide' / GUIDE_NAME).write_bytes(b'%PDF-1.4\n%fixture\n')
        self.assertEqual(guide_path(self.root), self.root / 'guide' / GUIDE_NAME)
        self.assertIs(self.client.get('/api/state', headers=self.headers).json()['student_guide'], True)
        answer = self.client.get('/student-guide')
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.headers['content-type'], 'application/pdf')
        self.assertTrue(answer.headers['content-disposition'].startswith('inline'), answer.headers['content-disposition'])
        self.assertTrue(answer.content.startswith(b'%PDF'))

    def test_a_symlink_or_a_folder_in_place_of_the_pdf_is_not_served(self):
        (self.root / 'guide').mkdir(); target = self.root / 'elsewhere.pdf'; target.write_bytes(b'%PDF-1.4\n')
        (self.root / 'guide' / GUIDE_NAME).symlink_to(target)
        self.assertIsNone(guide_path(self.root)); self.assertEqual(self.client.get('/student-guide').status_code, 404)


if __name__ == '__main__':
    unittest.main()
