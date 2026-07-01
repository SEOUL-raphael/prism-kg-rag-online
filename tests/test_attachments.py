import unittest

from govrag.attachments import find_attachment_links, guess_extension, looks_like_attachment


class AttachmentTests(unittest.TestCase):
    def test_looks_like_attachment(self):
        self.assertTrue(looks_like_attachment("https://example.test/a.pdf"))
        self.assertTrue(looks_like_attachment("https://example.test/download?id=1&file=hwp"))
        self.assertTrue(looks_like_attachment("https://example.test/portal/cmmn/file/fileDown.do?atchFileId=1"))

    def test_find_attachment_links(self):
        html = '<a href="/files/a.pdf">PDF</a><a href="/view">view</a>'
        links = find_attachment_links(html, "https://example.test/news/1")
        self.assertEqual(links, ["https://example.test/files/a.pdf"])

    def test_find_attachment_links_ignores_javascript_wrapper(self):
        html = """
        <a href="/portal/cmmn/file/fileDown.do?atchFileId=1">file</a>
        <a href="javascript:previewAjax('https://example.test/portal/cmmn/file/fileDown.do?atchFileId=1', 'a.hwp');">preview</a>
        """
        links = find_attachment_links(html, "https://example.test/news/1")
        self.assertEqual(links, ["https://example.test/portal/cmmn/file/fileDown.do?atchFileId=1"])

    def test_guess_extension_from_content_disposition(self):
        ext, media_type = guess_extension(
            "https://example.test/fileDown.do?atchFileId=1",
            "application/octet-stream",
            "attachment; filename*=UTF-8''press.hwp",
        )
        self.assertEqual(ext, ".hwp")
        self.assertEqual(media_type, "application/hwp")


if __name__ == "__main__":
    unittest.main()
