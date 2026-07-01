import json
import re
import time

from .chunking import chunk_text
from .minimax import chat as minimax_chat
from .minimax import minimax_configured
from .minimax import stream_chat as minimax_stream_chat
from .search import fts_query, row_to_hit
from .storage import (
    clear_chunks_for_document,
    documents,
    insert_chunk,
    stable_hash,
    upsert_kg_edge,
    upsert_kg_node,
)


TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]{2,}")


def tokens(text):
    return TOKEN_RE.findall(text or "")[:12]


def node_id(kind, label):
    return "prism:{0}:{1}".format(kind, stable_hash(label)[:24])


def project_node_id(research_id):
    return "prism:project:{0}".format(research_id)


def split_keywords(value):
    if not value:
        return []
    parts = re.split(r"[,;/|#\n]+", value)
    return [part.strip() for part in parts if part.strip()]


def rebuild_prism_kg(conn):
    rows = conn.execute(
        """
        SELECT p.*, c.research_organ_type_name, c.researcher_name AS contract_researcher,
               c.contract_type_name, c.contract_cost,
               r.title AS report_title, r.keyword, r.issued_year AS report_issued_year
        FROM prism_projects p
        LEFT JOIN prism_contracts c ON c.research_id = p.research_id
        LEFT JOIN prism_reports r ON r.research_id = p.research_id
        """
    ).fetchall()
    nodes = 0
    edges = 0
    for row in rows:
        research_id = row["research_id"]
        if not research_id:
            continue
        p_id = project_node_id(research_id)
        upsert_kg_node(
            conn,
            p_id,
            "project",
            row["research_name"] or research_id,
            {
                "research_id": research_id,
                "organ_name": row["organ_name"],
                "research_start_date": row["research_start_date"],
                "issued_year": row["issued_year"],
            },
        )
        nodes += 1
        for kind, label, edge_kind in (
            ("institution", row["organ_name"], "ORDERED_BY"),
            ("department", row["charge_person_department"], "MANAGED_BY"),
            ("field", row["brm_biz_name"] or row["biz_name"], "CLASSIFIED_AS"),
            ("researcher", row["researcher_name"] or row["contract_researcher"], "RESEARCHED_BY"),
            ("contract_type", row["contract_type_name"], "CONTRACTED_AS"),
        ):
            if not label:
                continue
            n_id = node_id(kind, label)
            upsert_kg_node(conn, n_id, kind, label, {"label": label})
            upsert_kg_edge(conn, p_id, n_id, edge_kind, {"research_id": research_id})
            nodes += 1
            edges += 1
        if row["report_title"]:
            r_id = node_id("report", "{0}|{1}".format(research_id, row["report_title"]))
            upsert_kg_node(conn, r_id, "report", row["report_title"], {"research_id": research_id})
            upsert_kg_edge(conn, p_id, r_id, "HAS_REPORT", {"research_id": research_id})
            nodes += 1
            edges += 1
        for keyword in split_keywords(row["keyword"]):
            k_id = node_id("keyword", keyword)
            upsert_kg_node(conn, k_id, "keyword", keyword, {"label": keyword})
            upsert_kg_edge(conn, p_id, k_id, "HAS_KEYWORD", {"research_id": research_id})
            nodes += 1
            edges += 1
    return {"projects": len(rows), "nodes_touched": nodes, "edges_touched": edges}


def index_prism_documents(conn, max_chars=1200, overlap=160):
    count = 0
    for doc in documents(conn):
        if not str(doc["source_format"] or "").startswith("prism_"):
            continue
        clear_chunks_for_document(conn, doc["id"])
        metadata = slim_chunk_metadata(json.loads(doc["metadata_json"] or "{}"))
        for i, chunk in enumerate(chunk_text(doc["text"], max_chars, overlap)):
            insert_chunk(conn, doc["id"], i, chunk, metadata)
            count += 1
    return count


def slim_chunk_metadata(metadata):
    allowed = (
        "source",
        "research_id",
        "organ_name",
        "title",
        "file_name",
        "file_url",
        "local_path",
        "format",
    )
    slim = {key: metadata.get(key, "") for key in allowed if metadata.get(key, "")}
    converter = metadata.get("converter_metadata") or {}
    if isinstance(converter, dict):
        od = converter.get("_opendataloader")
        if isinstance(od, dict):
            for key in ("markdown_path", "json_path"):
                if od.get(key):
                    slim["opendataloader_" + key] = od.get(key)
        for key in ("converter", "rhwp_version", "rhwp_core_version", "fallback", "pages"):
            if converter.get(key) not in (None, ""):
                slim["converter_" + key] = converter.get(key)
    return slim


def plan_with_llm(question):
    if not minimax_configured():
        return {"terms": tokens(question), "source": "fallback"}
    prompt = (
        "다음 질문을 PRISM 정책연구 지식그래프 검색 계획으로 바꿔 주세요. "
        "JSON만 출력하세요. 형식: {\"terms\":[\"검색어\"],\"kinds\":[\"project|institution|department|field|keyword|researcher|report\"]}."
    )
    content = minimax_chat(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": question},
        ],
        temperature=0.1,
        max_tokens=500,
    )
    try:
        data = json.loads(content)
        terms = [str(x).strip() for x in data.get("terms", []) if str(x).strip()]
        kinds = [str(x).strip() for x in data.get("kinds", []) if str(x).strip()]
        return {"terms": terms or tokens(question), "kinds": kinds, "source": "minimax"}
    except Exception:
        return {"terms": tokens(question), "source": "minimax_text", "raw": content[:1000]}


def kg_search(conn, terms, kinds=None, limit=20):
    terms = [term for term in terms if term]
    if not terms:
        return []
    clauses = []
    params = []
    for term in terms[:8]:
        clauses.append("label LIKE ?")
        params.append("%{0}%".format(term))
    kind_clause = ""
    if kinds:
        placeholders = ",".join("?" for _ in kinds)
        kind_clause = " AND kind IN ({0})".format(placeholders)
        params.extend(kinds)
    params.append(limit)
    rows = conn.execute(
        """
        SELECT * FROM kg_nodes
        WHERE ({0}) {1}
        ORDER BY kind, label
        LIMIT ?
        """.format(" OR ".join(clauses), kind_clause),
        params,
    ).fetchall()
    results = []
    for row in rows:
        data = {}
        try:
            data = json.loads(row["data_json"] or "{}")
        except json.JSONDecodeError:
            pass
        results.append({"id": row["id"], "kind": row["kind"], "label": row["label"], "data": data})
    return results


def research_ids_from_kg(conn, kg_nodes):
    ids = set()
    for node in kg_nodes:
        data = node.get("data") or {}
        if data.get("research_id"):
            ids.add(data["research_id"])
        node_id_value = node.get("id")
        for row in conn.execute(
            """
            SELECT from_id, to_id, data_json FROM kg_edges
            WHERE from_id = ? OR to_id = ?
            LIMIT 200
            """,
            (node_id_value, node_id_value),
        ).fetchall():
            try:
                edge_data = json.loads(row["data_json"] or "{}")
                if edge_data.get("research_id"):
                    ids.add(edge_data["research_id"])
            except json.JSONDecodeError:
                pass
            for endpoint in (row["from_id"], row["to_id"]):
                if str(endpoint).startswith("prism:project:"):
                    ids.add(str(endpoint).split("prism:project:", 1)[1])
    return sorted(ids)


def prism_body_search(conn, question, research_ids=None, limit=8):
    q = fts_query(question)
    params = []
    filter_sql = "d.source_format LIKE 'prism_%'"
    if research_ids:
        placeholders = ",".join("?" for _ in research_ids)
        filter_sql += " AND d.record_id IN ({0})".format(placeholders)
        params.extend(research_ids)
    if q:
        try:
            rows = conn.execute(
                """
                SELECT
                  c.id AS chunk_id, c.document_id, c.chunk_index, c.text, c.metadata_json,
                  bm25(chunks_fts) AS score
                FROM chunks_fts
                JOIN chunks c ON chunks_fts.rowid = c.id
                JOIN documents d ON d.id = c.document_id
                WHERE chunks_fts MATCH ? AND {0}
                ORDER BY score
                LIMIT ?
                """.format(filter_sql),
                [q] + params + [limit],
            ).fetchall()
            return [row_to_hit(row) for row in rows]
        except Exception:
            pass
    like = "%{0}%".format((question or "").strip())
    rows = conn.execute(
        """
        SELECT c.id AS chunk_id, c.document_id, c.chunk_index, c.text, c.metadata_json, 0.0 AS score
        FROM chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.text LIKE ? AND {0}
        LIMIT ?
        """.format(filter_sql),
        [like] + params + [limit],
    ).fetchall()
    return [row_to_hit(row) for row in rows]


def answer_with_llm(question, kg_results, hits):
    if not minimax_configured():
        return ""
    messages = answer_messages(question, kg_results, hits)
    return minimax_chat(messages, temperature=0.2, max_tokens=1600)


def answer_messages(question, kg_results, hits):
    evidence = []
    for item in kg_results[:10]:
        evidence.append("[KG] {0} {1}".format(item.get("kind"), item.get("label")))
    for i, hit in enumerate(hits[:8], start=1):
        meta = hit.get("metadata", {})
        citation = "{0} {1} {2}".format(meta.get("organ_name", ""), meta.get("research_id", ""), meta.get("title", "")).strip()
        evidence.append("[본문 {0}] {1}\n{2}".format(i, citation, hit.get("text", "")[:1400]))
    prompt = "아래 검증된 KG 결과와 본문 근거만 사용해 한국어로 답하세요. 모르면 모른다고 답하세요."
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": "질문: {0}\n\n근거:\n{1}".format(question, "\n\n".join(evidence))},
    ]


def evidence_from_hits(hits):
    evidence = []
    for hit in hits or []:
        meta = hit.get("metadata", {}) or {}
        file_id = str(hit.get("document_id") or "")
        if file_id.startswith("prism-doc-"):
            file_id = file_id[len("prism-doc-") :]
        evidence.append(
            {
                "chunk_id": hit.get("chunk_id"),
                "document_id": hit.get("document_id"),
                "file_id": file_id,
                "chunk_index": hit.get("chunk_index"),
                "research_id": meta.get("research_id", ""),
                "title": meta.get("title", ""),
                "organ_name": meta.get("organ_name", ""),
                "file_name": meta.get("file_name", ""),
                "file_url": meta.get("file_url", ""),
                "markdown_path": meta.get("opendataloader_markdown_path", ""),
                "local_path": meta.get("local_path", ""),
                "score": hit.get("score"),
                "excerpt": (hit.get("text") or "")[:900],
            }
        )
    return evidence


def query_prism(conn, question, limit=8, use_llm=True):
    started = time.perf_counter()
    timings = {}
    errors = []
    t0 = time.perf_counter()
    plan = plan_with_llm(question) if use_llm else {"terms": tokens(question), "source": "fallback"}
    timings["plan_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    t0 = time.perf_counter()
    kg_results = kg_search(conn, plan.get("terms", []), plan.get("kinds"), limit=20)
    research_ids = research_ids_from_kg(conn, kg_results)
    timings["kg_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    t0 = time.perf_counter()
    hits = prism_body_search(conn, question, research_ids=research_ids, limit=limit)
    if not hits and research_ids:
        hits = prism_body_search(conn, question, research_ids=None, limit=limit)
    timings["body_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    evidence = evidence_from_hits(hits)
    answer = ""
    if use_llm:
        t0 = time.perf_counter()
        try:
            answer = answer_with_llm(question, kg_results, hits)
        except Exception as exc:
            answer = ""
            errors.append({"stage": "answer", "message": str(exc)})
        timings["answer_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    timings["total_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return {
        "question": question,
        "answer": answer,
        "plan": plan,
        "kg_results": kg_results,
        "verified_research_ids": research_ids,
        "hits": hits,
        "evidence": evidence,
        "timings": timings,
        "errors": errors,
    }


def stream_query_prism(conn, question, limit=8, use_llm=True):
    started = time.perf_counter()
    timings = {}
    errors = []

    yield {"event": "stage", "stage": "plan", "status": "running", "message": "KG 검색 계획을 생성합니다."}
    t0 = time.perf_counter()
    plan = plan_with_llm(question) if use_llm else {"terms": tokens(question), "source": "fallback"}
    timings["plan_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    yield {"event": "plan", "plan": plan}
    yield {"event": "stage", "stage": "plan", "status": "complete", "message": "KG 검색 계획이 준비되었습니다."}

    yield {"event": "stage", "stage": "kg", "status": "running", "message": "SQLite KG에서 후보 과제를 검증합니다."}
    t0 = time.perf_counter()
    kg_results = kg_search(conn, plan.get("terms", []), plan.get("kinds"), limit=20)
    research_ids = research_ids_from_kg(conn, kg_results)
    timings["kg_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    yield {"event": "kg_results", "kg_results": kg_results, "verified_research_ids": research_ids}
    yield {"event": "stage", "stage": "kg", "status": "complete", "message": "KG 후보 검증을 완료했습니다."}

    yield {"event": "stage", "stage": "body", "status": "running", "message": "검증된 과제의 Markdown chunk를 검색합니다."}
    t0 = time.perf_counter()
    hits = prism_body_search(conn, question, research_ids=research_ids, limit=limit)
    if not hits and research_ids:
        hits = prism_body_search(conn, question, research_ids=None, limit=limit)
    timings["body_ms"] = round((time.perf_counter() - t0) * 1000, 2)
    evidence = evidence_from_hits(hits)
    yield {"event": "hits", "hits": hits, "evidence": evidence}
    yield {"event": "stage", "stage": "body", "status": "complete", "message": "본문 근거 검색을 완료했습니다."}

    answer_parts = []
    reasoning_parts = []
    if use_llm and minimax_configured():
        yield {"event": "stage", "stage": "llm", "status": "running", "message": "MiniMax가 근거 기반 답변을 생성합니다."}
        t0 = time.perf_counter()
        try:
            for item in minimax_stream_chat(answer_messages(question, kg_results, hits), temperature=0.2, max_tokens=1600):
                item_type = item.get("type")
                if item_type == "answer_delta":
                    text = item.get("text", "")
                    answer_parts.append(text)
                    yield {"event": "answer_delta", "text": text}
                elif item_type == "reasoning_delta":
                    text = item.get("text", "")
                    reasoning_parts.append(text)
                    yield {"event": "reasoning_delta", "text": text}
                elif item_type == "reasoning_details":
                    yield {"event": "reasoning_details", "details": item.get("details")}
                elif item_type == "usage":
                    yield {"event": "usage", "usage": item.get("usage")}
                elif item_type == "finish":
                    yield {"event": "finish", "finish_reason": item.get("finish_reason")}
        except Exception as exc:
            errors.append({"stage": "answer", "message": str(exc)})
            yield {"event": "error", "stage": "answer", "message": str(exc)}
        timings["answer_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        yield {"event": "stage", "stage": "llm", "status": "complete", "message": "MiniMax 답변 생성을 마쳤습니다."}
    else:
        yield {
            "event": "stage",
            "stage": "llm",
            "status": "skipped",
            "message": "MiniMax가 비활성화되어 KG와 본문 근거만 반환합니다.",
        }

    timings["total_ms"] = round((time.perf_counter() - started) * 1000, 2)
    yield {
        "event": "done",
        "question": question,
        "answer": "".join(answer_parts),
        "reasoning": "".join(reasoning_parts),
        "plan": plan,
        "kg_results": kg_results,
        "verified_research_ids": research_ids,
        "hits": hits,
        "evidence": evidence,
        "timings": timings,
        "errors": errors,
    }
