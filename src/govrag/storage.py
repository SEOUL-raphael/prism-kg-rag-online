import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone


SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  name TEXT,
  org TEXT,
  region TEXT,
  portal_url TEXT,
  license TEXT,
  config_json TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS records (
  id TEXT PRIMARY KEY,
  source_id TEXT,
  org TEXT,
  region TEXT,
  title TEXT,
  date TEXT,
  department TEXT,
  body TEXT,
  detail_url TEXT,
  license TEXT,
  portal_url TEXT,
  raw_json TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS attachments (
  id TEXT PRIMARY KEY,
  record_id TEXT,
  url TEXT,
  local_path TEXT,
  media_type TEXT,
  sha256 TEXT,
  size INTEGER,
  status TEXT,
  error TEXT,
  fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  record_id TEXT,
  attachment_id TEXT,
  source_format TEXT,
  title TEXT,
  text TEXT,
  metadata_json TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  document_id TEXT,
  chunk_index INTEGER,
  text TEXT,
  metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_documents_attachment_id ON documents(attachment_id);
CREATE INDEX IF NOT EXISTS idx_documents_record_id ON documents(record_id);
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks(document_id);
CREATE TABLE IF NOT EXISTS ingest_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT,
  started_at TEXT,
  finished_at TEXT,
  status TEXT,
  stats_json TEXT,
  error TEXT
);
"""


PRISM_SCHEMA = """
CREATE TABLE IF NOT EXISTS prism_projects (
  research_id TEXT PRIMARY KEY,
  report_open_yn TEXT,
  research_name TEXT,
  organ_name TEXT,
  researcher_name TEXT,
  charge_person_department TEXT,
  charge_person_phone_no TEXT,
  biz_name TEXT,
  research_date TEXT,
  research_start_date TEXT,
  research_end_date TEXT,
  brm_biz_id TEXT,
  brm_biz_name TEXT,
  research_outline TEXT,
  issued_year TEXT,
  list_json TEXT,
  detail_json TEXT,
  meta_json TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS prism_reports (
  id TEXT PRIMARY KEY,
  research_id TEXT,
  title TEXT,
  table_contents TEXT,
  summary TEXT,
  keyword TEXT,
  issued_year TEXT,
  raw_json TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS prism_contracts (
  research_id TEXT PRIMARY KEY,
  research_organ_id TEXT,
  research_organ_type_name TEXT,
  researcher_name TEXT,
  contract_date TEXT,
  contract_type_name TEXT,
  contract_cost TEXT,
  raw_json TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS prism_kogl (
  research_id TEXT PRIMARY KEY,
  kogl_open_yn TEXT,
  kogl_content TEXT,
  raw_json TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS prism_files (
  id TEXT PRIMARY KEY,
  research_id TEXT,
  source_section TEXT,
  file_url TEXT,
  file_type TEXT,
  file_name TEXT,
  file_size TEXT,
  local_path TEXT,
  media_type TEXT,
  sha256 TEXT,
  size INTEGER,
  status TEXT,
  error TEXT,
  raw_json TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS prism_api_failures (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  endpoint TEXT,
  params_json TEXT,
  status TEXT,
  error_code TEXT,
  message TEXT,
  response_excerpt TEXT,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS prism_api_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  call_day TEXT,
  endpoint TEXT,
  success INTEGER,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS prism_state (
  key TEXT PRIMARY KEY,
  value_json TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS kg_nodes (
  id TEXT PRIMARY KEY,
  kind TEXT,
  label TEXT,
  data_json TEXT,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS kg_edges (
  id TEXT PRIMARY KEY,
  from_id TEXT,
  to_id TEXT,
  kind TEXT,
  data_json TEXT,
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_prism_files_research_id ON prism_files(research_id);
CREATE INDEX IF NOT EXISTS idx_prism_files_status ON prism_files(status);
CREATE INDEX IF NOT EXISTS idx_kg_nodes_kind_label ON kg_nodes(kind, label);
CREATE INDEX IF NOT EXISTS idx_kg_edges_from ON kg_edges(from_id);
CREATE INDEX IF NOT EXISTS idx_kg_edges_to ON kg_edges(to_id);
"""


FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
  text,
  content='chunks',
  content_rowid='id'
);
"""


def utcnow():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def kst_day():
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")


def stable_hash(*parts):
    import hashlib

    basis = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def connect(db_path):
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path):
    conn = connect(db_path)
    try:
        conn.executescript(SCHEMA)
        conn.executescript(PRISM_SCHEMA)
        try:
            conn.executescript(FTS_SCHEMA)
        except sqlite3.OperationalError:
            pass
        conn.commit()
    finally:
        conn.close()


def upsert_source(conn, source):
    conn.execute(
        """
        INSERT INTO sources(id, name, org, region, portal_url, license, config_json, updated_at)
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          name=excluded.name,
          org=excluded.org,
          region=excluded.region,
          portal_url=excluded.portal_url,
          license=excluded.license,
          config_json=excluded.config_json,
          updated_at=excluded.updated_at
        """,
        (
            source.get("id"),
            source.get("name"),
            source.get("org"),
            source.get("region"),
            source.get("portal_url"),
            source.get("license"),
            json.dumps(source, ensure_ascii=False, sort_keys=True),
            utcnow(),
        ),
    )


def upsert_record(conn, record):
    conn.execute(
        """
        INSERT INTO records(
          id, source_id, org, region, title, date, department, body, detail_url,
          license, portal_url, raw_json, updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          source_id=excluded.source_id,
          org=excluded.org,
          region=excluded.region,
          title=excluded.title,
          date=excluded.date,
          department=excluded.department,
          body=excluded.body,
          detail_url=excluded.detail_url,
          license=excluded.license,
          portal_url=excluded.portal_url,
          raw_json=excluded.raw_json,
          updated_at=excluded.updated_at
        """,
        (
            record["id"],
            record["source_id"],
            record["org"],
            record["region"],
            record["title"],
            record["date"],
            record["department"],
            record["body"],
            record["detail_url"],
            record["license"],
            record["portal_url"],
            json.dumps(record["raw"], ensure_ascii=False, sort_keys=True),
            utcnow(),
        ),
    )


def upsert_attachment(conn, attachment):
    conn.execute(
        """
        INSERT INTO attachments(
          id, record_id, url, local_path, media_type, sha256, size, status, error, fetched_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          local_path=excluded.local_path,
          media_type=excluded.media_type,
          sha256=excluded.sha256,
          size=excluded.size,
          status=excluded.status,
          error=excluded.error,
          fetched_at=excluded.fetched_at
        """,
        (
            attachment["id"],
            attachment["record_id"],
            attachment["url"],
            attachment.get("local_path", ""),
            attachment.get("media_type", ""),
            attachment.get("sha256", ""),
            attachment.get("size", 0),
            attachment.get("status", ""),
            attachment.get("error", ""),
            utcnow(),
        ),
    )


def insert_document(conn, document):
    conn.execute(
        """
        INSERT OR REPLACE INTO documents(
          id, record_id, attachment_id, source_format, title, text, metadata_json, created_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document["id"],
            document.get("record_id", ""),
            document.get("attachment_id", ""),
            document.get("source_format", ""),
            document.get("title", ""),
            document.get("text", ""),
            json.dumps(document.get("metadata", {}), ensure_ascii=False, sort_keys=True),
            utcnow(),
        ),
    )


def clear_chunks_for_document(conn, document_id):
    rows = conn.execute("SELECT id FROM chunks WHERE document_id = ?", (document_id,)).fetchall()
    for row in rows:
        try:
            conn.execute("DELETE FROM chunks_fts WHERE rowid = ?", (row["id"],))
        except sqlite3.OperationalError:
            pass
    conn.execute("DELETE FROM chunks WHERE document_id = ?", (document_id,))


def insert_chunk(conn, document_id, chunk_index, text, metadata):
    cur = conn.execute(
        "INSERT INTO chunks(document_id, chunk_index, text, metadata_json) VALUES(?, ?, ?, ?)",
        (document_id, chunk_index, text, json.dumps(metadata, ensure_ascii=False, sort_keys=True)),
    )
    rowid = cur.lastrowid
    try:
        conn.execute("INSERT INTO chunks_fts(rowid, text) VALUES(?, ?)", (rowid, text))
    except sqlite3.OperationalError:
        pass
    return rowid


def pending_pdf_attachments(conn):
    return conn.execute(
        """
        SELECT * FROM attachments
        WHERE status = 'downloaded'
          AND lower(coalesce(media_type, '') || ' ' || coalesce(local_path, '') || ' ' || coalesce(url, '')) LIKE '%pdf%'
        """
    ).fetchall()


def body_records_without_documents(conn):
    return conn.execute(
        """
        SELECT r.* FROM records r
        LEFT JOIN documents d ON d.record_id = r.id AND d.source_format = 'api_body'
        WHERE length(coalesce(r.body, '')) > 0 AND d.id IS NULL
        """
    ).fetchall()


def documents(conn):
    return conn.execute("SELECT * FROM documents").fetchall()


def record_for_document(conn, document_id):
    return conn.execute(
        """
        SELECT r.* FROM records r
        JOIN documents d ON d.record_id = r.id
        WHERE d.id = ?
        """,
        (document_id,),
    ).fetchone()


def record_prism_api_call(conn, endpoint, success=True, call_day=None):
    conn.execute(
        "INSERT INTO prism_api_calls(call_day, endpoint, success, created_at) VALUES(?, ?, ?, ?)",
        (call_day or kst_day(), endpoint, 1 if success else 0, utcnow()),
    )


def prism_api_calls_today(conn, call_day=None):
    row = conn.execute(
        "SELECT count(*) AS count FROM prism_api_calls WHERE call_day = ?",
        (call_day or kst_day(),),
    ).fetchone()
    return int(row["count"] if row else 0)


def insert_prism_api_failure(conn, endpoint, params, status, error_code="", message="", response_excerpt=""):
    safe_params = dict(params or {})
    for key in list(safe_params.keys()):
        if str(key).lower() in ("servicekey", "apikey", "api_key", "key", "authkey"):
            safe_params[key] = "***"
    conn.execute(
        """
        INSERT INTO prism_api_failures(
          endpoint, params_json, status, error_code, message, response_excerpt, created_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?)
        """,
        (
            endpoint,
            json.dumps(safe_params, ensure_ascii=False, sort_keys=True),
            status,
            error_code,
            message[:1000],
            response_excerpt[:2000],
            utcnow(),
        ),
    )


def upsert_prism_state(conn, key, value):
    conn.execute(
        """
        INSERT INTO prism_state(key, value_json, updated_at)
        VALUES(?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at
        """,
        (key, json.dumps(value, ensure_ascii=False, sort_keys=True), utcnow()),
    )


def get_prism_state(conn, key, default=None):
    row = conn.execute("SELECT value_json FROM prism_state WHERE key = ?", (key,)).fetchone()
    if not row:
        return default
    try:
        return json.loads(row["value_json"] or "null")
    except json.JSONDecodeError:
        return default


def upsert_prism_project(conn, project):
    conn.execute(
        """
        INSERT INTO prism_projects(
          research_id, report_open_yn, research_name, organ_name, researcher_name,
          charge_person_department, charge_person_phone_no, biz_name, research_date,
          research_start_date, research_end_date, brm_biz_id, brm_biz_name,
          research_outline, issued_year, list_json, detail_json, meta_json, updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(research_id) DO UPDATE SET
          report_open_yn=coalesce(excluded.report_open_yn, prism_projects.report_open_yn),
          research_name=coalesce(nullif(excluded.research_name, ''), prism_projects.research_name),
          organ_name=coalesce(nullif(excluded.organ_name, ''), prism_projects.organ_name),
          researcher_name=coalesce(nullif(excluded.researcher_name, ''), prism_projects.researcher_name),
          charge_person_department=coalesce(nullif(excluded.charge_person_department, ''), prism_projects.charge_person_department),
          charge_person_phone_no=coalesce(nullif(excluded.charge_person_phone_no, ''), prism_projects.charge_person_phone_no),
          biz_name=coalesce(nullif(excluded.biz_name, ''), prism_projects.biz_name),
          research_date=coalesce(nullif(excluded.research_date, ''), prism_projects.research_date),
          research_start_date=coalesce(nullif(excluded.research_start_date, ''), prism_projects.research_start_date),
          research_end_date=coalesce(nullif(excluded.research_end_date, ''), prism_projects.research_end_date),
          brm_biz_id=coalesce(nullif(excluded.brm_biz_id, ''), prism_projects.brm_biz_id),
          brm_biz_name=coalesce(nullif(excluded.brm_biz_name, ''), prism_projects.brm_biz_name),
          research_outline=coalesce(nullif(excluded.research_outline, ''), prism_projects.research_outline),
          issued_year=coalesce(nullif(excluded.issued_year, ''), prism_projects.issued_year),
          list_json=coalesce(nullif(excluded.list_json, ''), prism_projects.list_json),
          detail_json=coalesce(nullif(excluded.detail_json, ''), prism_projects.detail_json),
          meta_json=coalesce(nullif(excluded.meta_json, ''), prism_projects.meta_json),
          updated_at=excluded.updated_at
        """,
        (
            project.get("research_id"),
            project.get("report_open_yn", ""),
            project.get("research_name", ""),
            project.get("organ_name", ""),
            project.get("researcher_name", ""),
            project.get("charge_person_department", ""),
            project.get("charge_person_phone_no", ""),
            project.get("biz_name", ""),
            project.get("research_date", ""),
            project.get("research_start_date", ""),
            project.get("research_end_date", ""),
            project.get("brm_biz_id", ""),
            project.get("brm_biz_name", ""),
            project.get("research_outline", ""),
            project.get("issued_year", ""),
            json.dumps(project.get("list", {}), ensure_ascii=False, sort_keys=True) if project.get("list") is not None else "",
            json.dumps(project.get("detail", {}), ensure_ascii=False, sort_keys=True) if project.get("detail") is not None else "",
            json.dumps(project.get("meta", {}), ensure_ascii=False, sort_keys=True) if project.get("meta") is not None else "",
            utcnow(),
        ),
    )


def upsert_prism_report(conn, report):
    report_id = report.get("id") or stable_hash(report.get("research_id"), report.get("title"), "report")
    conn.execute(
        """
        INSERT INTO prism_reports(
          id, research_id, title, table_contents, summary, keyword, issued_year, raw_json, updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          title=excluded.title,
          table_contents=excluded.table_contents,
          summary=excluded.summary,
          keyword=excluded.keyword,
          issued_year=excluded.issued_year,
          raw_json=excluded.raw_json,
          updated_at=excluded.updated_at
        """,
        (
            report_id,
            report.get("research_id", ""),
            report.get("title", ""),
            report.get("table_contents", ""),
            report.get("summary", ""),
            report.get("keyword", ""),
            report.get("issued_year", ""),
            json.dumps(report.get("raw", {}), ensure_ascii=False, sort_keys=True),
            utcnow(),
        ),
    )


def upsert_prism_contract(conn, research_id, contract):
    conn.execute(
        """
        INSERT INTO prism_contracts(
          research_id, research_organ_id, research_organ_type_name, researcher_name,
          contract_date, contract_type_name, contract_cost, raw_json, updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(research_id) DO UPDATE SET
          research_organ_id=excluded.research_organ_id,
          research_organ_type_name=excluded.research_organ_type_name,
          researcher_name=excluded.researcher_name,
          contract_date=excluded.contract_date,
          contract_type_name=excluded.contract_type_name,
          contract_cost=excluded.contract_cost,
          raw_json=excluded.raw_json,
          updated_at=excluded.updated_at
        """,
        (
            research_id,
            contract.get("research_organ_id", ""),
            contract.get("research_organ_type_name", ""),
            contract.get("researcher_name", ""),
            contract.get("contract_date", ""),
            contract.get("contract_type_name", ""),
            contract.get("contract_cost", ""),
            json.dumps(contract, ensure_ascii=False, sort_keys=True),
            utcnow(),
        ),
    )


def upsert_prism_kogl(conn, research_id, kogl):
    conn.execute(
        """
        INSERT INTO prism_kogl(research_id, kogl_open_yn, kogl_content, raw_json, updated_at)
        VALUES(?, ?, ?, ?, ?)
        ON CONFLICT(research_id) DO UPDATE SET
          kogl_open_yn=excluded.kogl_open_yn,
          kogl_content=excluded.kogl_content,
          raw_json=excluded.raw_json,
          updated_at=excluded.updated_at
        """,
        (
            research_id,
            kogl.get("kogl_open_yn", ""),
            kogl.get("kogl_content", ""),
            json.dumps(kogl, ensure_ascii=False, sort_keys=True),
            utcnow(),
        ),
    )


def upsert_prism_file(conn, file_info):
    file_id = file_info.get("id") or stable_hash(
        file_info.get("research_id"), file_info.get("file_url"), file_info.get("file_type"), file_info.get("file_name")
    )
    conn.execute(
        """
        INSERT INTO prism_files(
          id, research_id, source_section, file_url, file_type, file_name, file_size,
          local_path, media_type, sha256, size, status, error, raw_json, updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          file_url=excluded.file_url,
          file_type=coalesce(nullif(excluded.file_type, ''), prism_files.file_type),
          file_name=coalesce(nullif(excluded.file_name, ''), prism_files.file_name),
          file_size=coalesce(nullif(excluded.file_size, ''), prism_files.file_size),
          local_path=coalesce(nullif(excluded.local_path, ''), prism_files.local_path),
          media_type=coalesce(nullif(excluded.media_type, ''), prism_files.media_type),
          sha256=coalesce(nullif(excluded.sha256, ''), prism_files.sha256),
          size=coalesce(nullif(excluded.size, 0), prism_files.size),
          status=coalesce(nullif(excluded.status, ''), prism_files.status),
          error=excluded.error,
          raw_json=excluded.raw_json,
          updated_at=excluded.updated_at
        """,
        (
            file_id,
            file_info.get("research_id", ""),
            file_info.get("source_section", ""),
            file_info.get("file_url", ""),
            file_info.get("file_type", ""),
            file_info.get("file_name", ""),
            file_info.get("file_size", ""),
            file_info.get("local_path", ""),
            file_info.get("media_type", ""),
            file_info.get("sha256", ""),
            int(file_info.get("size") or 0),
            file_info.get("status", "pending"),
            file_info.get("error", ""),
            json.dumps(file_info.get("raw", {}), ensure_ascii=False, sort_keys=True),
            utcnow(),
        ),
    )
    return file_id


def pending_prism_files(conn):
    return conn.execute(
        """
        SELECT f.*, p.research_name, p.organ_name, p.research_start_date, p.issued_year, p.report_open_yn
        FROM prism_files f
        LEFT JOIN prism_projects p ON p.research_id = f.research_id
        WHERE coalesce(f.status, 'pending') IN ('pending', '')
        ORDER BY f.research_id, f.file_name
        """
    ).fetchall()


def downloaded_prism_files_without_documents(conn):
    return conn.execute(
        """
        SELECT f.*, p.research_name, p.organ_name, p.research_start_date, p.issued_year
        FROM prism_files f
        LEFT JOIN documents d ON d.attachment_id = f.id
        LEFT JOIN prism_projects p ON p.research_id = f.research_id
        WHERE f.status = 'downloaded'
          AND length(coalesce(f.local_path, '')) > 0
          AND d.id IS NULL
        ORDER BY f.research_id, f.file_name
        """
    ).fetchall()


def prism_projects_for_enrichment(conn, include_done=False, limit=100):
    where = "" if include_done else "WHERE length(coalesce(detail_json, '')) = 0"
    return conn.execute(
        """
        SELECT * FROM prism_projects
        {0}
        ORDER BY research_id
        LIMIT ?
        """.format(where),
        (int(limit),),
    ).fetchall()


def upsert_kg_node(conn, node_id, kind, label, data=None):
    conn.execute(
        """
        INSERT INTO kg_nodes(id, kind, label, data_json, updated_at)
        VALUES(?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          kind=excluded.kind,
          label=excluded.label,
          data_json=excluded.data_json,
          updated_at=excluded.updated_at
        """,
        (node_id, kind, label, json.dumps(data or {}, ensure_ascii=False, sort_keys=True), utcnow()),
    )


def upsert_kg_edge(conn, from_id, to_id, kind, data=None):
    edge_id = stable_hash(from_id, to_id, kind)
    conn.execute(
        """
        INSERT INTO kg_edges(id, from_id, to_id, kind, data_json, updated_at)
        VALUES(?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          data_json=excluded.data_json,
          updated_at=excluded.updated_at
        """,
        (edge_id, from_id, to_id, kind, json.dumps(data or {}, ensure_ascii=False, sort_keys=True), utcnow()),
    )
