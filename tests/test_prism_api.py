import os
import tempfile
import unittest
import urllib.parse

import govrag.prism_api as prism_api
from govrag.storage import connect, init_db


class PrismApiTests(unittest.TestCase):
    def test_extract_list_rows_from_official_shape(self):
        payload = {
            "resultCode": "00",
            "totalCount": "2",
            "research": [
                {
                    "research_id": "123-202500001",
                    "research_name": "지역경제 연구",
                    "organ_name": "테스트시",
                    "report_open_yn": "Y",
                }
            ],
        }
        rows = prism_api.extract_research_rows(payload)
        project = prism_api.project_from_list_row(rows[0])
        self.assertEqual(prism_api.get_total_count(payload), 2)
        self.assertEqual(project["research_id"], "123-202500001")
        self.assertEqual(project["research_name"], "지역경제 연구")

    def test_extract_detail_report_and_files(self):
        payload = {
            "resultCode": "00",
            "research_id": "123-202500001",
            "research": {"research_name": "지역경제 연구", "organ_name": "테스트시"},
            "reportInfo": {
                "title": "최종보고서",
                "summary": "요약",
                "keyword": "지역경제, 정책",
                "url": {
                    "file_url": "https://example.test/report.pdf",
                    "file_type": "전체공개 연구보고서",
                    "file_name": "report.pdf",
                    "file_size": "100",
                },
            },
        }
        sections = prism_api.extract_detail_sections(payload)
        report = prism_api.report_from_detail("123-202500001", sections)
        files = prism_api.files_from_detail("123-202500001", sections)
        self.assertEqual(report["title"], "최종보고서")
        self.assertEqual(files[0]["file_url"], "https://example.test/report.pdf")
        self.assertEqual(files[0]["file_name"], "report.pdf")

    def test_client_records_redacted_failure(self):
        old_key = os.environ.get("PRISM_API_KEY")
        os.environ["PRISM_API_KEY"] = "abc%3D%3D"
        original = prism_api.request_text

        def fake_request_text(url, params=None, **kwargs):
            return '{"resultCode":"99","resultMsg":"bad key"}', {}, url

        prism_api.request_text = fake_request_text
        try:
            with tempfile.TemporaryDirectory() as td:
                db = os.path.join(td, "test.sqlite")
                init_db(db)
                conn = connect(db)
                try:
                    client = prism_api.PrismApiClient(conn=conn, quota_limit=10)
                    with self.assertRaises(Exception):
                        client.list_research("20250101", "20251231")
                    conn.commit()
                    row = conn.execute("SELECT params_json FROM prism_api_failures").fetchone()
                    self.assertIn('"serviceKey": "***"', row["params_json"])
                    self.assertNotIn("abc", row["params_json"])
                finally:
                    conn.close()
        finally:
            prism_api.request_text = original
            if old_key is None:
                os.environ.pop("PRISM_API_KEY", None)
            else:
                os.environ["PRISM_API_KEY"] = old_key

    def test_backend_detail_normalization_and_download_url(self):
        payload = {
            "status": "OK",
            "resultData": {
                "asmtDetail": {
                    "asmtId": "6260000-202600031",
                    "asmtNm": "Project A",
                    "instNm": "City A",
                    "asmtPicDeptNm": "Dept A",
                    "asmtPicTelno": "01012345678",
                    "rschBgngYmd": "20250226",
                    "rschEndYmd": "20251225",
                    "infoRlsCd": "B0030001",
                    "hghrkFwkClsfSysNm": "Industry",
                    "clsfSysNm": "Innovation",
                    "ctrtAmt": 136364000,
                    "rschInstNm": "Institute A",
                    "rscrNm": "Researcher A",
                    "ctrtSeCd": "Open bid",
                    "koglRlsYn": "Y",
                },
                "reportList": [
                    {
                        "rptpSn": 1,
                        "rptpTtl": "Report A",
                        "rptpDtlCn": "1&nbsp;Intro<BR&nbsp;/>2&nbsp;Body",
                        "thssSmryCn": "Summary&nbsp;A",
                        "kywdCn": "alpha, beta",
                        "pblcnYr": "2025",
                    }
                ],
                "asmtFileList": [
                    {
                        "fileSn": 3,
                        "fileTypeCd": "D0150004",
                        "fileNm": "report.pdf",
                        "asmtId": "6260000-202600031",
                        "fileWkky": "001",
                        "pdfTrsfYn": "Y",
                    }
                ],
            },
        }
        project = prism_api.project_from_backend_detail("6260000-202600031", payload)
        reports = prism_api.reports_from_backend_detail("6260000-202600031", payload)
        contract = prism_api.contract_from_backend_detail(payload)
        files = prism_api.files_from_backend_payload("6260000-202600031", payload)

        self.assertEqual(project["research_name"], "Project A")
        self.assertEqual(project["research_start_date"], "2025-02-26")
        self.assertEqual(project["report_open_yn"], "Y")
        self.assertEqual(reports[0]["table_contents"], "1 Intro\n2 Body")
        self.assertEqual(contract["contract_cost"], "136364000")
        self.assertEqual(files[0]["file_name"], "report.pdf")
        parsed = urllib.parse.urlsplit(files[0]["file_url"])
        params = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(parsed.scheme + "://" + parsed.netloc + parsed.path, prism_api.PRISM_BACKEND_DOWNLOAD_URL)
        self.assertEqual(params["asmtId"], ["6260000-202600031"])
        self.assertEqual(params["fileTypeCd"], ["D0150004"])


if __name__ == "__main__":
    unittest.main()
