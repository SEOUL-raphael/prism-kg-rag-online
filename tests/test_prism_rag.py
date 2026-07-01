import os
import tempfile
import unittest

import govrag.prism_rag as prism_rag
from govrag.prism_rag import index_prism_documents, query_prism, rebuild_prism_kg, stream_query_prism
from govrag.storage import (
    connect,
    init_db,
    insert_document,
    upsert_prism_contract,
    upsert_prism_project,
    upsert_prism_report,
)


class PrismRagTests(unittest.TestCase):
    def test_kg_then_body_search(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "test.sqlite")
            init_db(db)
            conn = connect(db)
            try:
                upsert_prism_project(
                    conn,
                    {
                        "research_id": "123-202500001",
                        "research_name": "지역경제 파급효과 연구",
                        "organ_name": "테스트시",
                        "charge_person_department": "정책과",
                        "brm_biz_name": "지역개발",
                    },
                )
                upsert_prism_contract(
                    conn,
                    "123-202500001",
                    {
                        "researcher_name": "홍길동",
                        "contract_type_name": "일반경쟁입찰",
                        "contract_cost": "1000",
                    },
                )
                upsert_prism_report(
                    conn,
                    {
                        "research_id": "123-202500001",
                        "title": "최종보고서",
                        "keyword": "지역경제, 체육대회",
                    },
                )
                insert_document(
                    conn,
                    {
                        "id": "doc1",
                        "record_id": "123-202500001",
                        "attachment_id": "file1",
                        "source_format": "prism_pdf_markdown",
                        "title": "최종보고서",
                        "text": "체육대회 개최는 숙박업과 음식점 매출에 지역경제 파급효과를 만든다.",
                        "metadata": {
                            "source": "prism",
                            "research_id": "123-202500001",
                            "organ_name": "테스트시",
                            "title": "최종보고서",
                        },
                    },
                )
                kg_stats = rebuild_prism_kg(conn)
                chunks = index_prism_documents(conn, max_chars=200, overlap=20)
                conn.commit()

                result = query_prism(conn, "체육대회 지역경제 파급효과", use_llm=False)
                self.assertGreaterEqual(kg_stats["nodes_touched"], 1)
                self.assertEqual(chunks, 1)
                self.assertIn("123-202500001", result["verified_research_ids"])
                self.assertTrue(result["hits"])
                self.assertEqual(result["hits"][0]["metadata"]["research_id"], "123-202500001")
                self.assertIn("evidence", result)
                self.assertEqual(result["evidence"][0]["research_id"], "123-202500001")
                self.assertEqual(result["evidence"][0]["file_id"], "doc1")
                self.assertIn("timings", result)
                self.assertEqual(result["errors"], [])

                original = prism_rag.minimax_configured
                prism_rag.minimax_configured = lambda: False
                try:
                    events = list(stream_query_prism(conn, "체육대회 지역경제 파급효과", use_llm=True))
                finally:
                    prism_rag.minimax_configured = original
                event_names = [item["event"] for item in events]
                self.assertIn("plan", event_names)
                self.assertIn("kg_results", event_names)
                self.assertIn("hits", event_names)
                self.assertEqual(events[-1]["event"], "done")
                self.assertEqual(events[-1]["evidence"][0]["research_id"], "123-202500001")
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
