import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone

from .attachments import download_attachment, failed_attachment, guess_extension, safe_part
from .config import load_env_file
from .http_client import request_bytes, request_bytes_post
from .normalizer import parse_date, text_value
from .prism_api import (
    PRISM_BACKEND_DOWNLOAD_URL,
    PRISM_WEB_DETAIL,
    PrismApiClient,
    PrismQuotaExceeded,
    contract_from_backend_detail,
    extract_detail_sections,
    extract_research_rows,
    fetch_backend_detail,
    files_from_backend_payload,
    files_from_detail,
    get_total_count,
    kogl_from_backend_detail,
    project_from_backend_detail,
    project_from_detail,
    project_from_list_row,
    reports_from_backend_detail,
    report_from_detail,
)
from .prism_convert import ConversionError, convert_document
from .prism_rag import index_prism_documents, query_prism, rebuild_prism_kg
from .storage import (
    connect,
    downloaded_prism_files_without_documents,
    init_db,
    insert_document,
    pending_prism_files,
    prism_api_calls_today,
    prism_projects_for_enrichment,
    upsert_attachment,
    upsert_prism_contract,
    upsert_prism_file,
    upsert_prism_kogl,
    upsert_prism_project,
    upsert_prism_report,
    upsert_prism_state,
    upsert_record,
    upsert_source,
)


DEFAULT_DB = os.path.join("data", "prism.sqlite")


def kst_today_compact():
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y%m%d")


def add_common(parser):
    parser.add_argument("--db", default=DEFAULT_DB)
    parser.add_argument("--env", default=os.path.join("configs", "runtime.local.env"))


def prism_source():
    return {
        "id": "prism",
        "name": "PRISM policy research",
        "org": "행정안전부",
        "region": "전국",
        "portal_url": "https://www.prism.go.kr/homepage",
        "license": "공공데이터포털/PRISM 공개 범위",
    }


def project_to_record(project):
    research_id = project.get("research_id", "")
    start = parse_date(project.get("research_start_date") or project.get("research_date"))
    issued_year = re.search(r"20\d{2}", project.get("issued_year", "") or "")
    if not start and issued_year:
        start = issued_year.group(0) + "-01-01"
    body_parts = [
        project.get("research_outline", ""),
        project.get("biz_name", ""),
        project.get("brm_biz_name", ""),
    ]
    return {
        "id": research_id,
        "source_id": "prism",
        "org": project.get("organ_name", ""),
        "region": "전국",
        "title": project.get("research_name", ""),
        "date": start,
        "department": project.get("charge_person_department", ""),
        "body": "\n\n".join(part for part in body_parts if part),
        "detail_url": PRISM_WEB_DETAIL.format(research_id=research_id),
        "attachments": [],
        "license": "PRISM",
        "portal_url": "https://www.prism.go.kr/homepage",
        "raw": project.get("list") or project.get("detail") or project,
    }


def save_project_as_record(conn, project):
    if not project.get("research_id"):
        return
    upsert_record(conn, project_to_record(project))


def upsert_detail_payload(conn, research_id, payload, include_backend=False):
    sections = extract_detail_sections(payload)
    project = project_from_detail(research_id, sections, payload)
    upsert_prism_project(conn, project)
    save_project_as_record(conn, project)

    report = report_from_detail(research_id, sections)
    if any(report.get(key) for key in ("title", "summary", "keyword", "table_contents")):
        upsert_prism_report(conn, report)

    contract = sections.get("contract") if isinstance(sections.get("contract"), dict) else {}
    if contract:
        upsert_prism_contract(conn, research_id, contract)

    kogl = sections.get("kogl") if isinstance(sections.get("kogl"), dict) else {}
    if kogl:
        upsert_prism_kogl(conn, research_id, kogl)

    files = files_from_detail(research_id, sections)
    if include_backend and not any(item.get("file_url") for item in files):
        try:
            backend_payload = fetch_backend_detail(research_id)
            files.extend(files_from_backend_payload(research_id, backend_payload))
        except Exception:
            pass
    for file_info in files:
        upsert_prism_file(conn, file_info)
    return {"files": len(files)}


def upsert_backend_payload(conn, research_id, payload):
    project = project_from_backend_detail(research_id, payload)
    upsert_prism_project(conn, project)
    save_project_as_record(conn, project)

    reports = reports_from_backend_detail(research_id, payload)
    for report in reports:
        upsert_prism_report(conn, report)

    contract = contract_from_backend_detail(payload)
    if any(contract.get(key) for key in ("research_organ_type_name", "researcher_name", "contract_type_name", "contract_cost")):
        upsert_prism_contract(conn, research_id, contract)

    kogl = kogl_from_backend_detail(payload)
    if any(kogl.get(key) for key in ("kogl_open_yn", "kogl_content")):
        upsert_prism_kogl(conn, research_id, kogl)

    files = files_from_backend_payload(research_id, payload)
    for file_info in files:
        upsert_prism_file(conn, file_info)
    return {"files": len(files), "reports": len(reports)}


def cmd_harvest(args):
    load_env_file(args.env)
    init_db(args.db)
    conn = connect(args.db)
    total_rows = 0
    try:
        upsert_source(conn, prism_source())
        client = PrismApiClient(conn=conn, quota_limit=args.daily_limit, timeout=args.timeout)
        page = int(args.resume_page or 1)
        while True:
            if args.max_pages and page > int(args.max_pages):
                break
            payload, final_url = client.list_research(
                args.start_date,
                args.end_date or kst_today_compact(),
                page_no=page,
                num_of_rows=args.page_size,
                organ_id=args.organ_id,
            )
            rows = extract_research_rows(payload)
            total_count = get_total_count(payload)
            if not rows:
                break
            for row in rows:
                project = project_from_list_row(row)
                if not project.get("research_id"):
                    continue
                upsert_prism_project(conn, project)
                save_project_as_record(conn, project)
                total_rows += 1
            upsert_prism_state(
                conn,
                "harvest",
                {
                    "next_page": page + 1,
                    "start_date": args.start_date,
                    "end_date": args.end_date or kst_today_compact(),
                    "organ_id": args.organ_id,
                    "total_count": total_count,
                },
            )
            conn.commit()
            print("harvest page={0} rows={1} total_rows={2} api_remaining={3}".format(page, len(rows), total_rows, client.remaining_quota()))
            page += 1
            if total_count and page > (total_count + args.page_size - 1) // args.page_size:
                break
    except PrismQuotaExceeded as exc:
        print("quota: {0}".format(exc))
    finally:
        conn.commit()
        conn.close()
    print("prism harvest rows={0}".format(total_rows))


def cmd_enrich(args):
    load_env_file(args.env)
    init_db(args.db)
    conn = connect(args.db)
    done = 0
    failed = 0
    try:
        client = None if args.backend_only else PrismApiClient(conn=conn, quota_limit=args.daily_limit, timeout=args.timeout)
        rows = prism_projects_for_enrichment(conn, include_done=args.include_done, limit=args.limit)
        for row in rows:
            research_id = row["research_id"]
            try:
                if args.backend_only:
                    payload = fetch_backend_detail(research_id)
                    stats = upsert_backend_payload(conn, research_id, payload)
                else:
                    payload, final_url = client.detail(research_id)
                    stats = upsert_detail_payload(conn, research_id, payload, include_backend=not args.no_backend_fallback)
                if args.with_meta and not args.backend_only:
                    meta_payload, meta_url = client.meta(research_id)
                    upsert_prism_project(conn, {"research_id": research_id, "meta": meta_payload})
                done += 1
                if done % 10 == 0:
                    conn.commit()
                remaining = "backend" if args.backend_only else client.remaining_quota()
                print("enrich {0} files={1} remaining={2}".format(research_id, stats.get("files", 0), remaining))
            except PrismQuotaExceeded:
                print("quota reached")
                break
            except Exception as exc:
                failed += 1
                print("enrich failed {0}: {1}".format(research_id, exc))
        conn.commit()
    finally:
        conn.close()
    print("prism enrich done={0} failed={1}".format(done, failed))


def is_public_prism_file(row):
    joined = " ".join(
        text_value(row[key])
        for key in ("file_type", "file_name", "report_open_yn")
        if key in row.keys()
    )
    if any(word in joined for word in ("비공개", "부분공개", "미공개")):
        return False
    open_yn = text_value(row["report_open_yn"] if "report_open_yn" in row.keys() else "")
    if open_yn and open_yn.upper() in ("N", "NO", "0", "FALSE"):
        return False
    return True


def download_prism_file(row, data_dir):
    if not row["file_url"]:
        raise RuntimeError("file_url is empty")
    if str(row["file_url"]).startswith(PRISM_BACKEND_DOWNLOAD_URL):
        parsed = urllib.parse.urlsplit(row["file_url"])
        params = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
        payload = {
            "asmtId": params.get("asmtId", row["research_id"]),
            "fileTypeCd": params.get("fileTypeCd", row["file_type"] or ""),
            "fileSn": params.get("fileSn", ""),
            "fileWkky": params.get("fileWkky", ""),
            "pdfTrsfYn": params.get("pdfTrsfYn", ""),
        }
        raw, headers, final_url = request_bytes_post(PRISM_BACKEND_DOWNLOAD_URL, payload=payload, timeout=90, retries=2)
        final_url = row["file_url"]
    else:
        raw, headers, final_url = request_bytes(row["file_url"], timeout=90, retries=2)
    sha = hashlib.sha256(raw).hexdigest()
    content_disposition = headers.get("Content-Disposition") or headers.get("content-disposition") or ""
    content_type = headers.get("Content-Type") or headers.get("content-type") or ""
    ext, media_type = guess_extension(final_url + " " + (row["file_name"] or ""), content_type, content_disposition)
    org = safe_part(row["organ_name"] or "PRISM")
    year = "unknown"
    match = re.search(r"20\d{2}", row["research_start_date"] or row["issued_year"] or "")
    if match:
        year = match.group(0)
    out_dir = os.path.join(data_dir, "raw", "prism", org, year)
    os.makedirs(out_dir, exist_ok=True)
    filename = "{0}{1}".format(sha[:24], ext)
    path = os.path.join(out_dir, filename)
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(raw)
    return {
        "id": row["id"],
        "record_id": row["research_id"],
        "url": final_url,
        "local_path": path,
        "media_type": media_type,
        "sha256": sha,
        "size": len(raw),
        "status": "downloaded",
        "error": "",
    }


def cmd_download(args):
    load_env_file(args.env)
    init_db(args.db)
    conn = connect(args.db)
    done = 0
    skipped = 0
    failed = 0
    try:
        for row in pending_prism_files(conn):
            if args.limit and done >= args.limit:
                break
            if not args.include_restricted and not is_public_prism_file(row):
                upsert_prism_file(conn, {"id": row["id"], "research_id": row["research_id"], "status": "metadata_only", "error": "restricted or partial disclosure"})
                skipped += 1
                continue
            try:
                attachment = download_prism_file(row, args.data_dir)
                upsert_attachment(conn, attachment)
                upsert_prism_file(conn, dict(attachment, research_id=row["research_id"], file_url=attachment["url"], status="downloaded"))
                done += 1
                print("download {0} {1}".format(row["research_id"], attachment["local_path"]))
            except Exception as exc:
                attachment = failed_attachment({"id": row["research_id"]}, row["file_url"], exc)
                upsert_attachment(conn, dict(attachment, id=row["id"]))
                upsert_prism_file(conn, {"id": row["id"], "research_id": row["research_id"], "status": "failed", "error": str(exc)[:1000]})
                failed += 1
            if (done + failed + skipped) % 10 == 0:
                conn.commit()
        conn.commit()
    finally:
        conn.close()
    print("prism download done={0} skipped={1} failed={2}".format(done, skipped, failed))


def clean_surrogates(value):
    if isinstance(value, str):
        return value.encode("utf-8", errors="replace").decode("utf-8")
    if isinstance(value, list):
        return [clean_surrogates(item) for item in value]
    if isinstance(value, tuple):
        return tuple(clean_surrogates(item) for item in value)
    if isinstance(value, dict):
        return {clean_surrogates(key): clean_surrogates(item) for key, item in value.items()}
    return value


def cmd_convert(args):
    init_db(args.db)
    conn = connect(args.db)
    done = 0
    failed = 0
    try:
        for row in downloaded_prism_files_without_documents(conn):
            if args.limit and done >= args.limit:
                break
            path = row["local_path"]
            if not path or not os.path.exists(path):
                upsert_prism_file(conn, {"id": row["id"], "research_id": row["research_id"], "status": "convert_failed", "error": "local file missing"})
                failed += 1
                continue
            out_dir = os.path.join(args.data_dir, "converted", "prism", row["id"])
            try:
                text, metadata = convert_document(path, out_dir, allow_pymupdf_fallback=args.allow_pymupdf_fallback)
                text = clean_surrogates(text)
                metadata = clean_surrogates(metadata)
                doc_id = "prism-doc-" + row["id"]
                title = row["research_name"] or row["file_name"] or os.path.basename(path)
                ext = os.path.splitext(path)[1].lower().lstrip(".")
                insert_document(
                    conn,
                    {
                        "id": doc_id,
                        "record_id": row["research_id"],
                        "attachment_id": row["id"],
                        "source_format": "prism_{0}_markdown".format(ext or "file"),
                        "title": title,
                        "text": text,
                        "metadata": {
                            "source": "prism",
                            "research_id": row["research_id"],
                            "organ_name": row["organ_name"],
                            "title": title,
                            "file_name": row["file_name"],
                            "file_url": row["file_url"],
                            "local_path": path,
                            "format": ext,
                            "converter_metadata": metadata,
                        },
                    },
                )
                upsert_prism_file(conn, {"id": row["id"], "research_id": row["research_id"], "status": "converted", "error": ""})
                done += 1
                print("convert {0} {1}".format(row["research_id"], path))
            except Exception as exc:
                failed += 1
                upsert_prism_file(conn, {"id": row["id"], "research_id": row["research_id"], "status": "convert_failed", "error": str(exc)[:1000]})
                print("convert failed {0}: {1}".format(path, exc))
            conn.commit()
        conn.commit()
    finally:
        conn.close()
    print("prism convert done={0} failed={1}".format(done, failed))


def cmd_build_kg(args):
    init_db(args.db)
    conn = connect(args.db)
    try:
        kg_stats = rebuild_prism_kg(conn)
        chunks = index_prism_documents(conn, max_chars=args.max_chars, overlap=args.overlap)
        conn.commit()
    finally:
        conn.close()
    print("prism kg projects={0} nodes_touched={1} edges_touched={2} chunks={3}".format(
        kg_stats["projects"], kg_stats["nodes_touched"], kg_stats["edges_touched"], chunks
    ))


def cmd_query(args):
    load_env_file(args.env)
    conn = connect(args.db)
    try:
        result = query_prism(conn, args.question, limit=args.limit, use_llm=not args.no_llm)
    finally:
        conn.close()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if result.get("answer"):
        print(result["answer"])
        print()
    print("KG terms: {0}".format(", ".join(result.get("plan", {}).get("terms", []))))
    for item in result.get("kg_results", [])[:8]:
        print("[KG] {0}: {1}".format(item.get("kind"), item.get("label")))
    for i, hit in enumerate(result.get("hits", []), start=1):
        meta = hit.get("metadata", {})
        print("#{0} {1} {2}".format(i, meta.get("research_id", ""), meta.get("title", "")))
        print(hit.get("text", "")[:700])
        print()


def cmd_status(args):
    load_env_file(args.env)
    init_db(args.db)
    from .prism_access import prism_status

    stats = prism_status(args.db)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


def cmd_serve(args):
    load_env_file(args.env)
    init_db(args.db)
    from .server import serve

    serve(args.db, host=args.host, port=args.port, use_ollama=False)


def cmd_mcp(args):
    load_env_file(args.env)
    init_db(args.db)
    from .prism_mcp import run_mcp

    run_mcp(args.db, transport=args.transport, host=args.host, port=args.port)


def build_parser(prog="prism"):
    parser = argparse.ArgumentParser(prog=prog)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("harvest")
    add_common(p)
    p.add_argument("--start-date", default="20250101")
    p.add_argument("--end-date", default="")
    p.add_argument("--organ-id", default="")
    p.add_argument("--page-size", type=int, default=100)
    p.add_argument("--max-pages", type=int, default=0)
    p.add_argument("--resume-page", type=int, default=1)
    p.add_argument("--daily-limit", type=int, default=900)
    p.add_argument("--timeout", type=int, default=30)
    p.set_defaults(func=cmd_harvest)

    p = sub.add_parser("enrich")
    add_common(p)
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--daily-limit", type=int, default=900)
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--include-done", action="store_true")
    p.add_argument("--with-meta", action="store_true")
    p.add_argument("--no-backend-fallback", action="store_true")
    p.add_argument("--backend-only", action="store_true")
    p.set_defaults(func=cmd_enrich)

    p = sub.add_parser("download")
    add_common(p)
    p.add_argument("--data-dir", default="data")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--include-restricted", action="store_true")
    p.set_defaults(func=cmd_download)

    p = sub.add_parser("convert")
    add_common(p)
    p.add_argument("--data-dir", default="data")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--allow-pymupdf-fallback", action="store_true")
    p.set_defaults(func=cmd_convert)

    p = sub.add_parser("build-kg")
    add_common(p)
    p.add_argument("--max-chars", type=int, default=1200)
    p.add_argument("--overlap", type=int, default=160)
    p.set_defaults(func=cmd_build_kg)

    p = sub.add_parser("query")
    add_common(p)
    p.add_argument("question")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-llm", action="store_true")
    p.set_defaults(func=cmd_query)

    p = sub.add_parser("status")
    add_common(p)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("serve")
    add_common(p)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("mcp")
    add_common(p)
    p.add_argument("--transport", choices=("stdio", "http"), default="stdio")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8877)
    p.set_defaults(func=cmd_mcp)

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
        args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print("ERROR: {0}".format(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
