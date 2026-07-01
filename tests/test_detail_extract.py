import unittest

from govrag.detail_extract import extract_detail_body_from_html, extract_element_by_id


class DetailExtractTests(unittest.TestCase):
    def test_extract_element_by_id(self):
        html = '<html><body><div id="nav">skip</div><div id="dbData"><p>본문&nbsp;<b>내용</b></p></div></body></html>'
        block = extract_element_by_id(html, "dbData")
        self.assertIn("본문", block)
        self.assertNotIn("skip", block)

    def test_extract_detail_body_text(self):
        html = '<div id="dbData"><p>사회적경제기업 <span>지원</span></p></div>'
        self.assertEqual(extract_detail_body_from_html(html, {"html_id": "dbData"}), "사회적경제기업 지원")

    def test_extract_detail_body_stops_at_footer(self):
        html = '<div id="dbData"><p>본문</p><p>목록 이전글 메뉴</p></div>'
        text = extract_detail_body_from_html(html, {"html_id": "dbData", "stop_phrases": ["목록 이전글"]})
        self.assertEqual(text, "본문")


if __name__ == "__main__":
    unittest.main()
