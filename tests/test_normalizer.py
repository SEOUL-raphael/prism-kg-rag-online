import unittest

from govrag.normalizer import find_records, normalize_record, parse_date, since_year


class NormalizerTests(unittest.TestCase):
    def test_parse_date(self):
        self.assertEqual(parse_date("20260102"), "2026-01-02")
        self.assertEqual(parse_date("2026.1.2"), "2026-01-02")

    def test_since_year(self):
        self.assertTrue(since_year("2026-01-01", 2026))
        self.assertTrue(since_year("2027-03-04", 2026))
        self.assertFalse(since_year("2025-12-31", 2026))

    def test_find_records_nested_items(self):
        payload = {"response": {"body": {"items": {"item": [{"title": "A"}, {"title": "B"}]}}}}
        rows = find_records(payload)
        self.assertEqual(len(rows), 2)

    def test_find_records_explicit_path(self):
        payload = {"sbPressBoard": {"row": [{"TITLE": "A"}, {"TITLE": "B"}]}}
        rows = find_records(payload, ["sbPressBoard", "row"])
        self.assertEqual(len(rows), 2)

    def test_normalize_record(self):
        source = {
            "id": "sample",
            "org": "기관",
            "region": "지역",
            "mapping": {
                "title": ["sj"],
                "date": ["reg"],
                "body": ["cn"],
                "detail_url": ["url"],
                "attachments": ["fileUrl"],
            },
        }
        record = normalize_record(
            source,
            {"sj": "제목", "reg": "2026-06-01", "cn": "본문", "url": "https://example.test", "fileUrl": "a.pdf"},
        )
        self.assertEqual(record["title"], "제목")
        self.assertEqual(record["date"], "2026-06-01")
        self.assertIn("a.pdf", record["attachments"])

    def test_normalize_html_body_and_wtime(self):
        source = {
            "id": "sample",
            "mapping": {
                "title": ["title"],
                "date": ["wtime"],
                "body": ["contents"],
            },
        }
        record = normalize_record(
            source,
            {"title": "제목", "wtime": "2026-06-29 10:11:12", "contents": "<p>본문&nbsp;<b>내용</b></p>"},
        )
        self.assertEqual(record["date"], "2026-06-29")
        self.assertEqual(record["body"], "본문 내용")


if __name__ == "__main__":
    unittest.main()
