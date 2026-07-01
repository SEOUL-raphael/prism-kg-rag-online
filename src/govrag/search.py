import json
import re
import sqlite3


TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")


def fts_query(text):
    tokens = TOKEN_RE.findall(text or "")
    if not tokens:
        return ""
    return " OR ".join(tokens[:12])


def query(conn, text, limit=8):
    q = fts_query(text)
    if q:
        try:
            rows = conn.execute(
                """
                SELECT
                  c.id AS chunk_id,
                  c.document_id,
                  c.chunk_index,
                  c.text,
                  c.metadata_json,
                  bm25(chunks_fts) AS score
                FROM chunks_fts
                JOIN chunks c ON chunks_fts.rowid = c.id
                WHERE chunks_fts MATCH ?
                ORDER BY score
                LIMIT ?
                """,
                (q, limit),
            ).fetchall()
            return [row_to_hit(row) for row in rows]
        except sqlite3.OperationalError:
            pass

    like = "%{0}%".format((text or "").strip())
    rows = conn.execute(
        """
        SELECT id AS chunk_id, document_id, chunk_index, text, metadata_json, 0.0 AS score
        FROM chunks
        WHERE text LIKE ?
        LIMIT ?
        """,
        (like, limit),
    ).fetchall()
    return [row_to_hit(row) for row in rows]


def row_to_hit(row):
    metadata = {}
    try:
        metadata = json.loads(row["metadata_json"] or "{}")
    except json.JSONDecodeError:
        metadata = {}
    return {
        "chunk_id": row["chunk_id"],
        "document_id": row["document_id"],
        "chunk_index": row["chunk_index"],
        "text": row["text"],
        "metadata": metadata,
        "score": row["score"],
    }


def answer_prompt(question, hits):
    lines = [
        "아래 근거만 사용해 한국어로 답하세요.",
        "근거에 없는 내용은 모른다고 말하세요.",
        "",
        "[질문]",
        question,
        "",
        "[근거]",
    ]
    for i, hit in enumerate(hits, start=1):
        meta = hit.get("metadata", {})
        citation = "{0} {1} {2}".format(meta.get("org", ""), meta.get("date", ""), meta.get("title", "")).strip()
        lines.append("{0}. {1}\n{2}".format(i, citation, hit.get("text", "")[:1600]))
    return "\n".join(lines)
