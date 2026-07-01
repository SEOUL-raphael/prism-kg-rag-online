import os
import tempfile
import unittest

from govrag.prism_access import (
    pipeline_guide,
    prism_kg_summary,
    prism_kg_neighbors,
    prism_markdown,
    prism_operations_status,
    prism_project,
    prism_project_summary,
    prism_projects,
    prism_search_chunks,
    prism_status,
)
from govrag.prism_rag import index_prism_documents, project_node_id, rebuild_prism_kg
from govrag.storage import connect, init_db, insert_document, upsert_prism_file, upsert_prism_project


class PrismAccessTests(unittest.TestCase):
    def test_access_helpers(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "test.sqlite")
            init_db(db)
            conn = connect(db)
            try:
                upsert_prism_project(
                    conn,
                    {
                        "research_id": "123-202500001",
                        "research_name": "지역경제 분석 연구",
                        "organ_name": "테스트시",
                        "charge_person_department": "정책과",
                        "research_outline": "지역경제 파급효과 분석",
                    },
                )
                upsert_prism_file(
                    conn,
                    {
                        "id": "file1",
                        "research_id": "123-202500001",
                        "file_name": "보고서.pdf",
                        "status": "converted",
                    },
                )
                insert_document(
                    conn,
                    {
                        "id": "prism-doc-file1",
                        "record_id": "123-202500001",
                        "attachment_id": "file1",
                        "source_format": "prism_pdf_markdown",
                        "title": "보고서",
                        "text": "지역경제와 일자리 효과를 정리한 본문입니다.",
                        "metadata": {
                            "source": "prism",
                            "research_id": "123-202500001",
                            "organ_name": "테스트시",
                            "title": "보고서",
                            "file_name": "보고서.pdf",
                        },
                    },
                )
                rebuild_prism_kg(conn)
                index_prism_documents(conn, max_chars=200, overlap=20)
                conn.commit()
            finally:
                conn.close()

            status = prism_status(db)
            self.assertEqual(status["projects"], 1)
            self.assertEqual(status["converted_files"], 1)
            self.assertEqual(status["downloaded_waiting_conversion"], 0)
            self.assertIn("conversion_rate", status)
            self.assertIn("minimax", status)
            self.assertNotIn("MINIMAX_API_KEY", str(status.get("minimax", {})))

            projects = prism_projects(db, "지역경제", 10)
            self.assertEqual(projects[0]["research_id"], "123-202500001")

            project = prism_project(db, "123-202500001")
            self.assertEqual(project["files"][0]["document_id"], "prism-doc-file1")

            markdown = prism_markdown(db, "file1")
            self.assertIn("일자리", markdown["text"])

            hits = prism_search_chunks(db, "일자리", limit=3)
            self.assertTrue(hits)
            self.assertEqual(hits[0]["metadata"]["research_id"], "123-202500001")

            neighbors = prism_kg_neighbors(db, project_node_id("123-202500001"), depth=1)
            self.assertGreaterEqual(len(neighbors["nodes"]), 1)

            guide = pipeline_guide()
            self.assertTrue(guide["sections"])

            kg_summary = prism_kg_summary(db)
            self.assertTrue(kg_summary["node_kinds"])
            self.assertTrue(kg_summary["edge_kinds"])

            project_summary = prism_project_summary(db)
            self.assertTrue(project_summary["top_orgs"])
            self.assertTrue(project_summary["file_status"])

            operations = prism_operations_status(db)
            self.assertEqual(operations["converted_files"], 1)
            self.assertIn("recent_failures", operations)


if __name__ == "__main__":
    unittest.main()
