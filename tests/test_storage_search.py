import os
import tempfile
import unittest

from govrag.storage import clear_chunks_for_document, connect, init_db, insert_chunk, insert_document
from govrag.search import query


class StorageSearchTests(unittest.TestCase):
    def test_insert_and_query(self):
        with tempfile.TemporaryDirectory() as td:
            db = os.path.join(td, "test.sqlite")
            init_db(db)
            conn = connect(db)
            try:
                insert_document(
                    conn,
                    {
                        "id": "doc1",
                        "record_id": "rec1",
                        "attachment_id": "",
                        "source_format": "api_body",
                        "title": "청년 정책",
                        "text": "파주시는 청년 지원 정책을 발표했다.",
                        "metadata": {"org": "파주시", "date": "2026-01-02", "title": "청년 정책"},
                    },
                )
                clear_chunks_for_document(conn, "doc1")
                insert_chunk(conn, "doc1", 0, "파주시는 청년 지원 정책을 발표했다.", {"org": "파주시"})
                conn.commit()
                hits = query(conn, "청년 지원", limit=5)
                self.assertTrue(hits)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
