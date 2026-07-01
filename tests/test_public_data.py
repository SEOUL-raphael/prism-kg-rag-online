import unittest

import govrag.public_data as public_data


class PublicDataTests(unittest.TestCase):
    def test_template_supports_page_and_range_tokens(self):
        calls = []
        original = public_data.request_text

        def fake_request_text(url, **kwargs):
            calls.append(url)
            return '{"items": []}', {}, url

        public_data.request_text = fake_request_text
        try:
            source = {
                "id": "sample",
                "sample_key": "demo",
                "url_template": "https://example.test/{key}/{page}/{page_size}/{start}/{end}/{year}",
                "response_format": "json",
            }
            public_data.fetch_template_page(source, 2026, 3, 25)
        finally:
            public_data.request_text = original

        self.assertEqual(calls[0], "https://example.test/demo/3/25/51/75/2026")

    def test_iter_source_records_merges_detail_api_payload(self):
        original = public_data.request_text

        def fake_request_text(url, **kwargs):
            if "gnews_rss" in url:
                text = """
                <rss xmlns:dc="http://purl.org/dc/elements/1.1/">
                  <channel>
                    <item>
                      <title>제목</title>
                      <link>https://example.test/detail</link>
                      <number>N001</number>
                      <dc:date>2026-06-01 오후 2:00:00</dc:date>
                    </item>
                  </channel>
                </rss>
                """
            else:
                text = """
                <rss xmlns:dc="http://purl.org/dc/elements/1.1/">
                  <channel>
                    <item>
                      <description><![CDATA[<p>상세 본문</p>]]></description>
                      <clipname1>https://example.test/a.hwp</clipname1>
                    </item>
                  </channel>
                </rss>
                """
            return text, {}, url

        public_data.request_text = fake_request_text
        try:
            source = {
                "id": "gg",
                "org": "경기도",
                "region": "경기도",
                "sample_key": "demo",
                "url_template": "https://gnews.gg.go.kr/rss/gnews_rss.do?servicekey={key}&page={page}&pagesize={page_size}",
                "response_format": "xml",
                "items_path": ["rss", "channel", "item"],
                "detail_url_template": "https://gnews.gg.go.kr/rss/gnews_bodo_rss.do?servicekey={key}&ca_code={detail_key}",
                "detail_key_fields": ["number"],
                "detail_items_path": ["rss", "channel", "item"],
                "mapping": {
                    "title": ["title"],
                    "date": ["date"],
                    "body": ["description"],
                    "detail_url": ["link"],
                    "attachments": ["clipname1"],
                },
            }
            rows = list(public_data.iter_source_records(source, year=2026, max_pages=1))
        finally:
            public_data.request_text = original

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["date"], "2026-06-01")
        self.assertEqual(rows[0]["body"], "상세 본문")
        self.assertEqual(rows[0]["attachments"], ["https://example.test/a.hwp"])


if __name__ == "__main__":
    unittest.main()
