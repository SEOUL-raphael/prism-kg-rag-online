import argparse
import json
import os
import sys

from .attachments import collect_record_attachment_urls, download_attachment, failed_attachment
from .chunking import chunk_text
from .config import load_env_file, load_sources
from .detail_extract import fetch_detail_body
from .normalizer import text_value
from .ollama import generate
from .pdf_extract import extract_pdf_pages, pdf_document_id, source_format_for_path
from .public_data import enabled_sources, iter_source_records, validate_source_for_harvest
from .search import answer_prompt, query
from .server import serve
from .storage import (
    body_records_without_documents,
    clear_chunks_for_document,
    connect,
    documents,
    init_db,
    insert_chunk,
    insert_document,
    pending_pdf_attachments,
    upsert_attachment,
    upsert_record,
    upsert_source,
)


DEFAULT_DB = os.path.join("data", "govrag.sqlite")


def add_common(parser):
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--env", default=os.path.join("configs", "runtime.local.env"))


def cmd_init_db(args):
    init_db(args.db)
    print("initialized {0}".format(args.db))


def cmd_list_sources(args):
    sources = load_sources(args.config)
    for source in sources:
        status = "enabled" if source.get("enabled") else "disabled"
        print("{0}\t{1}\t{2}\t{3}".format(source.get("id"), status, source.get("org"), source.get("portal_url")))


def cmd_harvest(args):
    load_env_file(args.env)
    init_db(args.db)
    sources = list(enabled_sources(load_sources(args.config), include_disabled=args.include_disabled))
    if args.source_id:
        selected = set(args.source_id)
        sources = [source for source in sources if source.get("id") in selected]
    conn = connect(args.db)
    try:
        for source in sources:
            upsert_source(conn, source)
            problem = validate_source_for_harvest(source)
            if problem:
                print("skip {0}: {1}".format(source.get("id"), problem))
                continue
            count = 0
            attachments = 0
            print("harvest {0}".format(source.get("id")))
            for record in iter_source_records(
                source,
                year=args.year,
                from_year=None if args.year else args.from_year,
                max_pages=args.max_pages,
            ):
                detail_body_rule = source.get("detail_body")
                if detail_body_rule and not record.get("body") and not args.no_detail_fetch:
                    try:
                        record["body"] = fetch_detail_body(record.get("detail_url", ""), detail_body_rule)
                    except Exception as exc:
                        print("  detail body failed {0}: {1}".format(record.get("id", "")[:12], exc))
                upsert_record(conn, record)
                count += 1
                if record.get("body"):
                    insert_api_body_document(conn, record)
                if args.download_attachments:
                    urls = collect_record_attachment_urls(record, follow_detail=not args.no_detail_fetch)
                    for url in urls:
                        try:
                            attachment = download_attachment(record, url, args.data_dir)
                        except Exception as exc:
                            attachment = failed_attachment(record, url, exc)
                        upsert_attachment(conn, attachment)
                        attachments += 1
                if count % 25 == 0:
                    conn.commit()
                    print("  {0} records".format(count))
            conn.commit()
            print("done {0}: records={1}, attachments={2}".format(source.get("id"), count, attachments))
    finally:
        conn.close()


def insert_api_body_document(conn, record):
    doc_id = record["id"] + "-api-body"
    text = "\n\n".join([record.get("title", ""), record.get("body", "")]).strip()
    insert_document(
        conn,
        {
            "id": doc_id,
            "record_id": record["id"],
            "attachment_id": "",
            "source_format": "api_body",
            "title": record.get("title", ""),
            "text": text,
            "metadata": {
                "org": record.get("org", ""),
                "region": record.get("region", ""),
                "date": record.get("date", ""),
                "title": record.get("title", ""),
                "department": record.get("department", ""),
                "detail_url": record.get("detail_url", ""),
                "license": record.get("license", ""),
                "portal_url": record.get("portal_url", ""),
                "format": "api_body",
            },
        },
    )


def cmd_parse_pdfs(args):
    init_db(args.db)
    conn = connect(args.db)
    parsed = 0
    failed = 0
    try:
        for attachment in pending_pdf_attachments(conn):
            path = attachment["local_path"]
            if not path or not os.path.exists(path):
                continue
            record = conn.execute("SELECT * FROM records WHERE id = ?", (attachment["record_id"],)).fetchone()
            try:
                pages = extract_pdf_pages(path)
                for page in pages:
                    text = page.get("text", "")
                    if not text.strip():
                        continue
                    doc_id = pdf_document_id(attachment["id"], page["page"])
                    insert_document(
                        conn,
                        {
                            "id": doc_id,
                            "record_id": attachment["record_id"],
                            "attachment_id": attachment["id"],
                            "source_format": source_format_for_path(path),
                            "title": record["title"] if record else os.path.basename(path),
                            "text": text,
                            "metadata": {
                                "org": record["org"] if record else "",
                                "region": record["region"] if record else "",
                                "date": record["date"] if record else "",
                                "title": record["title"] if record else os.path.basename(path),
                                "department": record["department"] if record else "",
                                "detail_url": record["detail_url"] if record else "",
                                "license": record["license"] if record else "",
                                "attachment_url": attachment["url"],
                                "local_path": path,
                                "page": page["page"],
                                "format": "pdf",
                            },
                        },
                    )
                    parsed += 1
                conn.commit()
            except Exception as exc:
                failed += 1
                print("failed parse {0}: {1}".format(path, exc))
        print("pdf pages parsed={0}, failed_files={1}".format(parsed, failed))
    finally:
        conn.close()


def cmd_index(args):
    init_db(args.db)
    conn = connect(args.db)
    chunks = 0
    try:
        for record in body_records_without_documents(conn):
            insert_api_body_document(conn, dict(record))
        conn.commit()
        for doc in documents(conn):
            clear_chunks_for_document(conn, doc["id"])
            metadata = json.loads(doc["metadata_json"] or "{}")
            for i, chunk in enumerate(chunk_text(doc["text"], args.max_chars, args.overlap)):
                insert_chunk(conn, doc["id"], i, chunk, metadata)
                chunks += 1
        conn.commit()
        print("indexed chunks={0}".format(chunks))
    finally:
        conn.close()


def cmd_query(args):
    load_env_file(args.env)
    conn = connect(args.db)
    try:
        hits = query(conn, args.question, args.limit)
    finally:
        conn.close()
    if args.json:
        payload = {"question": args.question, "hits": hits}
        if args.ollama:
            payload["answer"] = generate(answer_prompt(args.question, hits))
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for i, hit in enumerate(hits, start=1):
        meta = hit.get("metadata", {})
        print("#{0} {1} {2} {3}".format(i, meta.get("org", ""), meta.get("date", ""), meta.get("title", "")))
        print(hit.get("text", "")[:700])
        print()
    if args.ollama:
        print(generate(answer_prompt(args.question, hits)))


def cmd_export_jsonl(args):
    init_db(args.db)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    conn = connect(args.db)
    count = 0
    try:
        rows = conn.execute(
            """
            SELECT d.*, r.org, r.region, r.date, r.department, r.detail_url, r.license, r.portal_url
            FROM documents d
            LEFT JOIN records r ON r.id = d.record_id
            """
        ).fetchall()
        with open(args.out, "w", encoding="utf-8") as f:
            for row in rows:
                metadata = json.loads(row["metadata_json"] or "{}")
                item = {
                    "id": row["id"],
                    "title": row["title"],
                    "text": row["text"],
                    "metadata": metadata,
                    "source": {
                        "org": row["org"],
                        "region": row["region"],
                        "date": row["date"],
                        "department": row["department"],
                        "detail_url": row["detail_url"],
                        "license": row["license"],
                        "portal_url": row["portal_url"],
                    },
                }
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
                count += 1
    finally:
        conn.close()
    print("exported {0} documents to {1}".format(count, args.out))


def cmd_serve(args):
    load_env_file(args.env)
    serve(args.db, host=args.host, port=args.port, use_ollama=args.ollama)


def cmd_prism(args):
    from .prism_cli import main as prism_main

    return prism_main(args.prism_args)


def build_parser():
    parser = argparse.ArgumentParser(prog="govrag")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init-db")
    add_common(p)
    p.set_defaults(func=cmd_init_db)

    p = sub.add_parser("list-sources")
    p.add_argument("--config", default=os.path.join("configs", "sources.example.json"))
    p.set_defaults(func=cmd_list_sources)

    p = sub.add_parser("harvest")
    add_common(p)
    p.add_argument("--config", default=os.path.join("configs", "sources.local.json"))
    p.add_argument("--year", type=int, default=None, help="Harvest only one exact year, for example 2026.")
    p.add_argument("--from-year", type=int, default=2026, help="Harvest records dated on or after this year.")
    p.add_argument("--max-pages", type=int, default=2)
    p.add_argument("--data-dir", default="data")
    p.add_argument("--download-attachments", action="store_true")
    p.add_argument("--no-detail-fetch", action="store_true")
    p.add_argument("--include-disabled", action="store_true")
    p.add_argument("--source-id", action="append", help="Harvest only the given source id. Repeat for multiple sources.")
    p.set_defaults(func=cmd_harvest)

    p = sub.add_parser("parse-pdfs")
    add_common(p)
    p.set_defaults(func=cmd_parse_pdfs)

    p = sub.add_parser("index")
    add_common(p)
    p.add_argument("--max-chars", type=int, default=1200)
    p.add_argument("--overlap", type=int, default=160)
    p.set_defaults(func=cmd_index)

    p = sub.add_parser("query")
    add_common(p)
    p.add_argument("question")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--json", action="store_true")
    p.add_argument("--ollama", action="store_true")
    p.set_defaults(func=cmd_query)

    p = sub.add_parser("export-jsonl")
    add_common(p)
    p.add_argument("--out", default=os.path.join("exports", "ragflow-import.jsonl"))
    p.set_defaults(func=cmd_export_jsonl)

    p = sub.add_parser("serve")
    add_common(p)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--ollama", action="store_true")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("prism", help="Run PRISM 2025+ research KG-RAG commands.")
    p.add_argument("prism_args", nargs=argparse.REMAINDER)
    p.set_defaults(func=cmd_prism)

    return parser


def main(argv=None):
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
        if isinstance(result, int):
            return result
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print("ERROR: {0}".format(exc), file=sys.stderr)
        return 1
    return 0
