import json
from collections import deque

from .config import env_presence, load_runtime_env
from .minimax import minimax_status
from .prism_rag import prism_body_search, query_prism, stream_query_prism
from .storage import connect, prism_api_calls_today


def _json_loads(value, default=None):
    if default is None:
        default = {}
    try:
        return json.loads(value or "null") or default
    except (TypeError, json.JSONDecodeError):
        return default


def _dict(row):
    return dict(row) if row else None


def _count(conn, sql, params=()):
    return int(conn.execute(sql, params).fetchone()["c"])


def prism_status(db_path):
    load_runtime_env()
    conn = connect(db_path)
    try:
        stats = {
            "projects": _count(conn, "SELECT count(*) AS c FROM prism_projects"),
            "detail_done": _count(conn, "SELECT count(*) AS c FROM prism_projects WHERE length(coalesce(detail_json, '')) > 0"),
            "detail_remaining": _count(conn, "SELECT count(*) AS c FROM prism_projects WHERE length(coalesce(detail_json, '')) = 0"),
            "files": _count(conn, "SELECT count(*) AS c FROM prism_files"),
            "downloaded_files": _count(conn, "SELECT count(*) AS c FROM prism_files WHERE status = 'downloaded'"),
            "converted_files": _count(conn, "SELECT count(*) AS c FROM prism_files WHERE status = 'converted'"),
            "convert_failed_files": _count(conn, "SELECT count(*) AS c FROM prism_files WHERE status = 'convert_failed'"),
            "metadata_only_files": _count(conn, "SELECT count(*) AS c FROM prism_files WHERE status = 'metadata_only'"),
            "api_failures": _count(conn, "SELECT count(*) AS c FROM prism_api_failures"),
            "prism_documents": _count(conn, "SELECT count(*) AS c FROM documents WHERE source_format LIKE 'prism_%'"),
            "prism_chunks": _count(
                conn,
                """
                SELECT count(*) AS c
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE d.source_format LIKE 'prism_%'
                """,
            ),
            "kg_nodes": _count(conn, "SELECT count(*) AS c FROM kg_nodes"),
            "kg_edges": _count(conn, "SELECT count(*) AS c FROM kg_edges"),
            "api_calls_today": prism_api_calls_today(conn),
            "downloaded_waiting_conversion": _count(
                conn,
                """
                SELECT count(*) AS c
                FROM prism_files f
                LEFT JOIN documents d ON d.attachment_id = f.id
                WHERE f.status = 'downloaded'
                  AND length(coalesce(f.local_path, '')) > 0
                  AND d.id IS NULL
                """,
            ),
        }
        stats["conversion_rate"] = round((stats["converted_files"] / max(stats["files"], 1)) * 100, 2)
        return {
            **stats,
            "minimax": minimax_status(),
            "environment": env_presence(
                [
                    "MINIMAX_API_KEY",
                    "SUPABASE_URL",
                    "SUPABASE_ANON_KEY",
                    "SUPABASE_SERVICE_ROLE_KEY",
                    "GITHUB_TOKEN",
                ]
            ),
        }
    finally:
        conn.close()


def _grouped(conn, sql, params=()):
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def prism_kg_summary(db_path, limit=12):
    conn = connect(db_path)
    try:
        return {
            "node_kinds": _grouped(
                conn,
                """
                SELECT coalesce(kind, 'unknown') AS label, count(*) AS value
                FROM kg_nodes
                GROUP BY coalesce(kind, 'unknown')
                ORDER BY value DESC, label
                LIMIT ?
                """,
                (int(limit),),
            ),
            "edge_kinds": _grouped(
                conn,
                """
                SELECT coalesce(kind, 'unknown') AS label, count(*) AS value
                FROM kg_edges
                GROUP BY coalesce(kind, 'unknown')
                ORDER BY value DESC, label
                LIMIT ?
                """,
                (int(limit),),
            ),
            "top_connected_nodes": _grouped(
                conn,
                """
                SELECT n.id, n.kind, n.label, count(e.id) AS degree
                FROM kg_nodes n
                LEFT JOIN kg_edges e ON e.from_id = n.id OR e.to_id = n.id
                GROUP BY n.id, n.kind, n.label
                ORDER BY degree DESC, n.kind, n.label
                LIMIT ?
                """,
                (int(limit),),
            ),
        }
    finally:
        conn.close()


def prism_project_summary(db_path, limit=12):
    conn = connect(db_path)
    try:
        return {
            "top_orgs": _grouped(
                conn,
                """
                SELECT coalesce(nullif(organ_name, ''), '미분류') AS label, count(*) AS value
                FROM prism_projects
                GROUP BY coalesce(nullif(organ_name, ''), '미분류')
                ORDER BY value DESC, label
                LIMIT ?
                """,
                (int(limit),),
            ),
            "top_fields": _grouped(
                conn,
                """
                SELECT coalesce(nullif(brm_biz_name, ''), nullif(biz_name, ''), '미분류') AS label, count(*) AS value
                FROM prism_projects
                GROUP BY coalesce(nullif(brm_biz_name, ''), nullif(biz_name, ''), '미분류')
                ORDER BY value DESC, label
                LIMIT ?
                """,
                (int(limit),),
            ),
            "years": _grouped(
                conn,
                """
                SELECT coalesce(nullif(issued_year, ''), substr(research_start_date, 1, 4), '미상') AS label, count(*) AS value
                FROM prism_projects
                GROUP BY coalesce(nullif(issued_year, ''), substr(research_start_date, 1, 4), '미상')
                ORDER BY label DESC
                LIMIT ?
                """,
                (int(limit),),
            ),
            "file_status": _grouped(
                conn,
                """
                SELECT coalesce(nullif(status, ''), 'pending') AS label, count(*) AS value
                FROM prism_files
                GROUP BY coalesce(nullif(status, ''), 'pending')
                ORDER BY value DESC, label
                """,
            ),
        }
    finally:
        conn.close()


def prism_operations_status(db_path):
    status = prism_status(db_path)
    return {
        "downloaded_files": status["downloaded_files"],
        "downloaded_waiting_conversion": status["downloaded_waiting_conversion"],
        "converted_files": status["converted_files"],
        "convert_failed_files": status["convert_failed_files"],
        "metadata_only_files": status["metadata_only_files"],
        "files": status["files"],
        "conversion_rate": status["conversion_rate"],
        "api_calls_today": status["api_calls_today"],
        "api_failures": status["api_failures"],
        "recent_failures": prism_failures(db_path, limit=20),
    }


def prism_projects(db_path, q="", limit=50):
    conn = connect(db_path)
    try:
        params = []
        where = ""
        if q:
            where = "WHERE research_name LIKE ? OR organ_name LIKE ? OR research_outline LIKE ? OR brm_biz_name LIKE ?"
            params.extend(["%{0}%".format(q)] * 4)
        params.append(max(1, min(int(limit or 50), 500)))
        rows = conn.execute(
            """
            SELECT p.research_id, p.research_name, p.organ_name, p.researcher_name,
                   p.charge_person_department, p.charge_person_phone_no, p.biz_name,
                   p.research_start_date, p.research_end_date, p.brm_biz_name,
                   p.research_outline, p.issued_year,
                   count(f.id) AS file_count,
                   sum(CASE WHEN f.status = 'converted' THEN 1 ELSE 0 END) AS converted_file_count
            FROM prism_projects p
            LEFT JOIN prism_files f ON f.research_id = p.research_id
            {0}
            GROUP BY p.research_id
            ORDER BY coalesce(p.research_start_date, p.issued_year, '') DESC, p.research_id
            LIMIT ?
            """.format(where),
            params,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def prism_project(db_path, research_id):
    conn = connect(db_path)
    try:
        project = conn.execute("SELECT * FROM prism_projects WHERE research_id = ?", (research_id,)).fetchone()
        if not project:
            return {"error": "not found", "research_id": research_id}
        reports = conn.execute("SELECT * FROM prism_reports WHERE research_id = ? ORDER BY id", (research_id,)).fetchall()
        contract = conn.execute("SELECT * FROM prism_contracts WHERE research_id = ?", (research_id,)).fetchone()
        kogl = conn.execute("SELECT * FROM prism_kogl WHERE research_id = ?", (research_id,)).fetchone()
        files = conn.execute(
            """
            SELECT f.*,
                   d.id AS document_id,
                   d.source_format AS document_format,
                   length(coalesce(d.text, '')) AS markdown_chars,
                   d.created_at AS document_created_at
            FROM prism_files f
            LEFT JOIN documents d ON d.attachment_id = f.id
            WHERE f.research_id = ?
            ORDER BY f.file_type, f.file_name, f.id
            """,
            (research_id,),
        ).fetchall()
        return {
            "project": dict(project),
            "reports": [dict(row) for row in reports],
            "contract": _dict(contract),
            "kogl": _dict(kogl),
            "files": [dict(row) for row in files],
        }
    finally:
        conn.close()


def prism_failures(db_path, limit=50):
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT id, endpoint, params_json, status, error_code, message, created_at
            FROM prism_api_failures
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, min(int(limit or 50), 500)),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def prism_markdown(db_path, file_id):
    conn = connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT d.id AS document_id, d.record_id AS research_id, d.attachment_id AS file_id,
                   d.source_format, d.title, d.text, d.metadata_json, d.created_at,
                   f.file_name, f.file_type, f.local_path, f.status AS file_status,
                   p.research_name, p.organ_name
            FROM documents d
            LEFT JOIN prism_files f ON f.id = d.attachment_id
            LEFT JOIN prism_projects p ON p.research_id = d.record_id
            WHERE d.attachment_id = ?
            ORDER BY d.created_at DESC
            LIMIT 1
            """,
            (file_id,),
        ).fetchone()
        if row:
            data = dict(row)
            data["metadata"] = _json_loads(data.pop("metadata_json", "{}"), {})
            return data
        file_row = conn.execute(
            """
            SELECT f.*, p.research_name, p.organ_name
            FROM prism_files f
            LEFT JOIN prism_projects p ON p.research_id = f.research_id
            WHERE f.id = ?
            """,
            (file_id,),
        ).fetchone()
        if not file_row:
            return {"error": "not found", "file_id": file_id}
        data = dict(file_row)
        data.update({"text": "", "metadata": {}, "message": "아직 Markdown으로 변환된 문서가 없습니다."})
        return data
    finally:
        conn.close()


def prism_search_chunks(db_path, query, research_ids=None, limit=8):
    conn = connect(db_path)
    try:
        if isinstance(research_ids, str):
            research_ids = [item.strip() for item in research_ids.split(",") if item.strip()]
        return prism_body_search(conn, query, research_ids=research_ids, limit=max(1, min(int(limit or 8), 50)))
    finally:
        conn.close()


def prism_query(db_path, question, limit=8, use_llm=True):
    conn = connect(db_path)
    try:
        return query_prism(conn, question, limit=max(1, min(int(limit or 8), 50)), use_llm=bool(use_llm))
    finally:
        conn.close()


def prism_query_stream(db_path, question, limit=8, use_llm=True):
    conn = connect(db_path)
    try:
        for event in stream_query_prism(conn, question, limit=max(1, min(int(limit or 8), 50)), use_llm=bool(use_llm)):
            yield event
    finally:
        conn.close()


def prism_kg_neighbors(db_path, node_id, depth=1):
    max_depth = max(0, min(int(depth or 1), 3))
    conn = connect(db_path)
    try:
        start = conn.execute("SELECT * FROM kg_nodes WHERE id = ?", (node_id,)).fetchone()
        if not start:
            return {"error": "not found", "node_id": node_id, "nodes": [], "edges": []}
        seen_nodes = {node_id}
        seen_edges = set()
        queue = deque([(node_id, 0)])
        while queue:
            current, current_depth = queue.popleft()
            if current_depth >= max_depth:
                continue
            edges = conn.execute(
                """
                SELECT * FROM kg_edges
                WHERE from_id = ? OR to_id = ?
                LIMIT 500
                """,
                (current, current),
            ).fetchall()
            for edge in edges:
                seen_edges.add(edge["id"])
                other = edge["to_id"] if edge["from_id"] == current else edge["from_id"]
                if other not in seen_nodes:
                    seen_nodes.add(other)
                    queue.append((other, current_depth + 1))
        node_rows = []
        for nid in sorted(seen_nodes):
            row = conn.execute("SELECT * FROM kg_nodes WHERE id = ?", (nid,)).fetchone()
            if row:
                item = dict(row)
                item["data"] = _json_loads(item.pop("data_json", "{}"), {})
                node_rows.append(item)
        edge_rows = []
        for eid in sorted(seen_edges):
            row = conn.execute("SELECT * FROM kg_edges WHERE id = ?", (eid,)).fetchone()
            if row:
                item = dict(row)
                item["data"] = _json_loads(item.pop("data_json", "{}"), {})
                edge_rows.append(item)
        return {"node_id": node_id, "depth": max_depth, "nodes": node_rows, "edges": edge_rows}
    finally:
        conn.close()


def pipeline_guide():
    return {
        "title": "PRISM KG-RAG 파이프라인",
        "summary": "PRISM 정책연구 과제를 수집해 파일을 Markdown으로 바꾸고, SQLite 안에 지식그래프와 본문 검색 인덱스를 함께 만들어 LLM이 근거를 확인하며 답하도록 구성합니다.",
        "sections": [
            {
                "title": "1. 수집",
                "body": "공공데이터포털 PRISM API로 2025년 이후 과제 목록을 받고, 공식 상세 API와 PRISM 공개 백엔드 상세 응답을 함께 사용해 과제명, 기관, 부서, 연구기간, 보고서, 계약, 공공누리, 첨부파일 정보를 저장합니다.",
            },
            {
                "title": "2. 저장",
                "body": "모든 원천 메타데이터는 로컬 SQLite의 prism_projects, prism_reports, prism_contracts, prism_files 테이블에 들어갑니다. API 실패와 일일 호출량도 같이 남겨 다음 실행에서 이어받을 수 있습니다.",
            },
            {
                "title": "3. 다운로드와 변환",
                "body": "공개 가능한 PDF/HWP/HWPX만 내려받습니다. PDF는 OpenDataLoader PDF, HWP/HWPX는 rhwp 기반 변환기를 사용해 Markdown 텍스트와 변환 메타데이터를 documents 테이블에 저장합니다.",
            },
            {
                "title": "4. KG와 본문 인덱스",
                "body": "과제, 기관, 부서, 연구분야, 연구자, 보고서, 주제어를 노드로 만들고 관계를 kg_edges에 저장합니다. Markdown 본문은 chunk로 나누어 FTS 검색 인덱스에 올립니다.",
            },
            {
                "title": "5. RAG 질의",
                "body": "질문이 들어오면 MiniMax가 KG 검색 계획을 만들고, SQLite KG에서 후보 과제를 검증한 뒤, 관련 Markdown chunk를 검색합니다. 답변에는 과제 ID, 기관, 파일, chunk ID와 원문 일부가 함께 붙습니다.",
            },
            {
                "title": "6. MCP 접근",
                "body": "같은 기능을 MCP 도구와 리소스로 열어 LLM 클라이언트가 prism_query, prism_search_chunks, prism_get_project, prism_get_markdown 같은 도구를 호출할 수 있게 합니다. 로컬 폐쇄망에는 stdio, 내부망 공유에는 Streamable HTTP가 맞습니다.",
            },
            {
                "title": "7. 온라인 공유",
                "body": "후속 단계에서는 React/Vite 프론트를 GitHub Pages로 배포하고, Supabase에는 메타데이터, KG, chunk만 동기화합니다. MiniMax 키는 브라우저에 두지 않고 Supabase Edge Function에서만 사용합니다.",
            },
        ],
    }
