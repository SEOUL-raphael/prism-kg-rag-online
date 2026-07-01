import argparse
import json
import os
import sqlite3
from pathlib import Path


TABLES = {
    "projects": """
        SELECT research_id, research_name, organ_name, researcher_name,
               charge_person_department, charge_person_phone_no, biz_name,
               research_start_date, research_end_date, brm_biz_name,
               research_outline, issued_year, updated_at
        FROM prism_projects
        ORDER BY research_id
    """,
    "reports": """
        SELECT id, research_id, title, table_contents, summary, keyword, issued_year, updated_at
        FROM prism_reports
        ORDER BY id
    """,
    "files": """
        SELECT f.id, f.research_id, f.source_section, f.file_type, f.file_name, f.file_size,
               f.media_type, f.sha256, f.size, f.status,
               length(coalesce(d.text, '')) AS markdown_chars,
               f.updated_at
        FROM prism_files f
        LEFT JOIN documents d ON d.attachment_id = f.id
        ORDER BY f.id
    """,
}


def parse_json(value):
    try:
        return json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}


def rows(conn, sql):
    for row in conn.execute(sql):
        yield dict(row)


def write_jsonl(path, items):
    count = 0
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def export_kg_nodes(conn, path):
    def items():
        for row in conn.execute("SELECT id, kind, label, data_json, updated_at FROM kg_nodes ORDER BY id"):
            item = dict(row)
            item["data"] = parse_json(item.pop("data_json", "{}"))
            yield item

    return write_jsonl(path, items())


def export_kg_edges(conn, path):
    def items():
        for row in conn.execute("SELECT id, from_id, to_id, kind, data_json, updated_at FROM kg_edges ORDER BY id"):
            item = dict(row)
            item["data"] = parse_json(item.pop("data_json", "{}"))
            yield item

    return write_jsonl(path, items())


def export_chunks(conn, path):
    def items():
        sql = """
            SELECT c.id, c.document_id, c.chunk_index, c.text, c.metadata_json,
                   d.record_id AS research_id, d.attachment_id AS file_id, d.title AS document_title
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE d.source_format LIKE 'prism_%'
            ORDER BY c.id
        """
        for row in conn.execute(sql):
            item = dict(row)
            metadata = parse_json(item.pop("metadata_json", "{}"))
            item["metadata"] = metadata
            item["title"] = metadata.get("title") or item.pop("document_title", "")
            item["organ_name"] = metadata.get("organ_name", "")
            item["file_name"] = metadata.get("file_name", "")
            yield item

    return write_jsonl(path, items())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=os.path.join("data", "prism.sqlite"))
    parser.add_argument("--out", default=os.path.join("exports", "supabase"))
    args = parser.parse_args()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        counts = {}
        for name, sql in TABLES.items():
            counts[name] = write_jsonl(out_dir / f"{name}.jsonl", rows(conn, sql))
        counts["kg_nodes"] = export_kg_nodes(conn, out_dir / "kg_nodes.jsonl")
        counts["kg_edges"] = export_kg_edges(conn, out_dir / "kg_edges.jsonl")
        counts["chunks"] = export_chunks(conn, out_dir / "chunks.jsonl")
    finally:
        conn.close()
    print(json.dumps({"out": str(out_dir), "counts": counts}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
