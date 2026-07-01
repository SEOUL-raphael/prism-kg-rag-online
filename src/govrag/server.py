import html
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .ollama import generate
from .prism_access import (
    pipeline_guide,
    prism_failures,
    prism_kg_neighbors,
    prism_kg_summary,
    prism_markdown,
    prism_operations_status,
    prism_project,
    prism_project_summary,
    prism_projects,
    prism_query,
    prism_query_stream,
    prism_search_chunks,
    prism_status,
)
from .search import answer_prompt, query
from .storage import connect


class RagHandler(BaseHTTPRequestHandler):
    db_path = "data/govrag.sqlite"
    use_ollama = False
    static_dir = Path.cwd() / "frontend" / "dist"

    def log_message(self, fmt, *args):
        return

    def send_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def send_bytes(self, status, body, content_type):
        self.send_response(status)
        self.send_cors_headers()
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_bytes(status, body, "application/json; charset=utf-8")

    def send_html(self, status, payload):
        self.send_bytes(status, payload.encode("utf-8"), "text/html; charset=utf-8")

    def send_error_json(self, status, message, **extra):
        payload = {"error": message}
        payload.update(extra)
        self.send_json(status, payload)

    def send_sse_headers(self):
        self.send_response(200)
        self.send_cors_headers()
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

    def write_sse(self, event, payload):
        data = json.dumps(payload, ensure_ascii=False)
        body = "event: {0}\ndata: {1}\n\n".format(event, data).encode("utf-8")
        self.wfile.write(body)
        self.wfile.flush()

    def read_json(self):
        length = int(self.headers.get("Content-Length") or "0")
        if not length:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        if not raw.strip():
            return {}
        return json.loads(raw)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        try:
            if self.handle_api_get(parsed):
                return
            if self.handle_legacy_get(parsed):
                return
            if self.handle_static(parsed.path):
                return
            self.send_error_json(404, "not found")
        except ValueError as exc:
            self.send_error_json(400, str(exc))
        except Exception as exc:
            self.send_error_json(500, str(exc))

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/rag/stream":
                body = self.read_json()
                question = str(body.get("question") or "").strip()
                if not question:
                    raise ValueError("question is required")
                limit = int(body.get("limit") or 8)
                use_llm = bool(body.get("use_llm", True))
                self.stream_rag(question, limit=limit, use_llm=use_llm)
                return
            if parsed.path == "/api/rag/query":
                body = self.read_json()
                question = str(body.get("question") or "").strip()
                if not question:
                    raise ValueError("question is required")
                limit = int(body.get("limit") or 8)
                use_llm = bool(body.get("use_llm", True))
                self.send_json(200, prism_query(self.db_path, question, limit=limit, use_llm=use_llm))
                return
            if parsed.path == "/api/search/chunks":
                body = self.read_json()
                query_text = str(body.get("query") or body.get("question") or "").strip()
                if not query_text:
                    raise ValueError("query is required")
                self.send_json(
                    200,
                    {
                        "query": query_text,
                        "hits": prism_search_chunks(
                            self.db_path,
                            query_text,
                            research_ids=body.get("research_ids"),
                            limit=int(body.get("limit") or 8),
                        ),
                    },
                )
                return
            if parsed.path == "/prism/query":
                body = self.read_json()
                question = str(body.get("question") or body.get("q") or "").strip()
                if not question:
                    raise ValueError("question is required")
                self.send_json(200, prism_query(self.db_path, question, limit=int(body.get("limit") or 8), use_llm=not body.get("no_llm", False)))
                return
            self.send_error_json(404, "not found")
        except ValueError as exc:
            self.send_error_json(400, str(exc))
        except json.JSONDecodeError:
            self.send_error_json(400, "invalid JSON body")
        except Exception as exc:
            self.send_error_json(500, str(exc))

    def stream_rag(self, question, limit=8, use_llm=True):
        self.send_sse_headers()
        try:
            for payload in prism_query_stream(self.db_path, question, limit=limit, use_llm=use_llm):
                self.write_sse(payload.get("event", "message"), payload)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception as exc:
            try:
                self.write_sse("error", {"event": "error", "message": str(exc)})
            except Exception:
                return

    def handle_api_get(self, parsed):
        path = parsed.path
        params = parse_qs(parsed.query)
        if path == "/health":
            self.send_json(200, {"status": "ok"})
            return True
        if path == "/api/status":
            self.send_json(200, prism_status(self.db_path))
            return True
        if path == "/api/analytics/kg-summary":
            self.send_json(200, prism_kg_summary(self.db_path, int(_one(params, "limit", "12"))))
            return True
        if path == "/api/analytics/project-summary":
            self.send_json(200, prism_project_summary(self.db_path, int(_one(params, "limit", "12"))))
            return True
        if path == "/api/operations/status":
            self.send_json(200, prism_operations_status(self.db_path))
            return True
        if path == "/api/projects":
            self.send_json(200, prism_projects(self.db_path, _one(params, "q", ""), int(_one(params, "limit", "50"))))
            return True
        if path.startswith("/api/projects/"):
            research_id = unquote(path.split("/api/projects/", 1)[1]).strip("/")
            self.send_json(200, prism_project(self.db_path, research_id))
            return True
        if path.startswith("/api/files/") and path.endswith("/markdown"):
            file_id = unquote(path[len("/api/files/") : -len("/markdown")]).strip("/")
            self.send_json(200, prism_markdown(self.db_path, file_id))
            return True
        if path == "/api/pipeline-guide":
            self.send_json(200, pipeline_guide())
            return True
        if path == "/api/failures":
            self.send_json(200, prism_failures(self.db_path, int(_one(params, "limit", "50"))))
            return True
        if path == "/api/kg/neighbors":
            node_id = _one(params, "node_id", "")
            if not node_id:
                raise ValueError("node_id is required")
            self.send_json(200, prism_kg_neighbors(self.db_path, node_id, int(_one(params, "depth", "1"))))
            return True
        if path == "/api/search/chunks":
            query_text = _one(params, "q", "")
            if not query_text:
                raise ValueError("q is required")
            research_ids = _one(params, "research_ids", "")
            self.send_json(
                200,
                {
                    "query": query_text,
                    "hits": prism_search_chunks(
                        self.db_path,
                        query_text,
                        research_ids=research_ids or None,
                        limit=int(_one(params, "limit", "8")),
                    ),
                },
            )
            return True
        if path == "/api/rag/query":
            question = _one(params, "q", "")
            if not question:
                raise ValueError("q is required")
            no_llm = _one(params, "no_llm", "0").lower() in ("1", "true", "y")
            self.send_json(200, prism_query(self.db_path, question, limit=int(_one(params, "limit", "8")), use_llm=not no_llm))
            return True
        if path == "/api/rag/stream":
            question = _one(params, "q", "")
            if not question:
                raise ValueError("q is required")
            no_llm = _one(params, "no_llm", "0").lower() in ("1", "true", "y")
            self.stream_rag(question, limit=int(_one(params, "limit", "8")), use_llm=not no_llm)
            return True
        return False

    def handle_legacy_get(self, parsed):
        path = parsed.path
        params = parse_qs(parsed.query)
        if path in ("/prism/status",):
            self.send_json(200, prism_status(self.db_path))
            return True
        if path == "/prism/projects":
            self.send_json(200, prism_projects(self.db_path, _one(params, "q", ""), int(_one(params, "limit", "50"))))
            return True
        if path == "/prism/project":
            self.send_json(200, prism_project(self.db_path, _one(params, "id", "")))
            return True
        if path == "/prism/failures":
            self.send_json(200, prism_failures(self.db_path, int(_one(params, "limit", "50"))))
            return True
        if path == "/prism/query":
            question = _one(params, "q", "")
            limit = int(_one(params, "limit", "8"))
            no_llm = _one(params, "no_llm", "0").lower() in ("1", "true", "y")
            self.send_json(200, prism_query(self.db_path, question, limit=limit, use_llm=not no_llm))
            return True
        if path == "/query":
            question = _one(params, "q", "")
            limit = int(_one(params, "limit", "8"))
            conn = connect(self.db_path)
            try:
                hits = query(conn, question, limit=limit)
            finally:
                conn.close()
            payload = {"question": question, "hits": hits}
            if self.use_ollama:
                try:
                    payload["answer"] = generate(answer_prompt(question, hits))
                except Exception as exc:
                    payload["answer_error"] = str(exc)
            self.send_json(200, payload)
            return True
        return False

    def handle_static(self, request_path):
        if not self.static_dir.exists():
            if request_path in ("/", "/prism"):
                self.send_html(200, prism_home_html())
                return True
            return False
        rel = unquote(request_path.lstrip("/"))
        if rel in ("", "prism") or "." not in Path(rel).name:
            rel = "index.html"
        target = (self.static_dir / rel).resolve()
        root = self.static_dir.resolve()
        if root not in target.parents and target != root:
            self.send_error_json(403, "forbidden")
            return True
        if not target.exists() or not target.is_file():
            index = root / "index.html"
            if index.exists():
                body = index.read_bytes()
                self.send_bytes(200, body, "text/html; charset=utf-8")
                return True
            return False
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
            content_type += "; charset=utf-8"
        self.send_bytes(200, target.read_bytes(), content_type)
        return True


def _one(params, name, default):
    return (params.get(name) or [default])[0]


def serve(db_path, host="127.0.0.1", port=8765, use_ollama=False):
    RagHandler.db_path = db_path
    RagHandler.use_ollama = use_ollama
    RagHandler.static_dir = Path.cwd() / "frontend" / "dist"
    server = ThreadingHTTPServer((host, port), RagHandler)
    server.daemon_threads = True
    print("Serving Gov RAG on http://{0}:{1}".format(host, port))
    server.serve_forever()


def prism_home_html():
    safe_title = html.escape("PRISM 2025+ KG-RAG")
    return """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{0}</title>
  <style>
    body {{ margin: 0; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #1f2933; background: #f6f8fa; }}
    main {{ max-width: 900px; margin: 0 auto; padding: 40px 20px; }}
    h1 {{ font-size: 24px; margin: 0 0 12px; }}
    p {{ line-height: 1.7; }}
    code {{ background: #eaeef2; padding: 2px 5px; border-radius: 4px; }}
  </style>
</head>
<body>
  <main>
    <h1>{0}</h1>
    <p>API 서버가 실행 중입니다. React UI를 사용하려면 <code>frontend</code>에서 빌드하거나 Vite 개발 서버를 실행하세요.</p>
    <p>상태 API: <code>/api/status</code>, RAG 질의 API: <code>/api/rag/query</code></p>
  </main>
</body>
</html>""".format(safe_title)
