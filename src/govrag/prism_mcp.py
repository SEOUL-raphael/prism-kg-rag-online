import json
import sys

from .prism_access import (
    prism_kg_neighbors as _prism_kg_neighbors,
    prism_markdown as _prism_markdown,
    prism_project as _prism_project,
    prism_query as _prism_query,
    prism_search_chunks as _prism_search_chunks,
    prism_status as _prism_status,
)


def _sdk_class():
    if sys.version_info < (3, 10):
        raise RuntimeError("PRISM MCP 서버는 Python 3.10+가 필요합니다. 기존 Python 3.9 변환 환경과 별도 venv를 만들어 실행하세요.")
    try:
        from mcp.server import MCPServer

        return MCPServer
    except Exception:
        try:
            from mcp.server.fastmcp import FastMCP

            return FastMCP
        except Exception as exc:
            raise RuntimeError("MCP SDK가 설치되어 있지 않습니다. Python 3.10+ 환경에서 govrag-portable[mcp]를 설치하세요.") from exc


def _json(data):
    return json.dumps(data, ensure_ascii=False, indent=2)


def create_mcp(db_path):
    ServerClass = _sdk_class()
    mcp = ServerClass("PRISM KG-RAG")

    @mcp.tool()
    def prism_status() -> dict:
        """Return PRISM collection, conversion, KG, chunk, and redacted runtime status."""
        return _prism_status(db_path)

    @mcp.tool()
    def prism_query(question: str, limit: int = 8, use_llm: bool = True) -> dict:
        """Run the PRISM KG-first RAG pipeline and return answer, plan, KG results, hits, and evidence."""
        return _prism_query(db_path, question, limit=limit, use_llm=use_llm)

    @mcp.tool()
    def prism_search_chunks(query: str, research_ids: list[str] | None = None, limit: int = 8) -> dict:
        """Search converted Markdown chunks, optionally restricted to PRISM research IDs."""
        return {
            "query": query,
            "research_ids": research_ids or [],
            "hits": _prism_search_chunks(db_path, query, research_ids=research_ids, limit=limit),
        }

    @mcp.tool()
    def prism_get_project(research_id: str) -> dict:
        """Return structured PRISM project metadata, reports, contract, Kogl, and files."""
        return _prism_project(db_path, research_id)

    @mcp.tool()
    def prism_get_markdown(file_id: str) -> dict:
        """Return converted Markdown text and metadata for a PRISM file ID."""
        return _prism_markdown(db_path, file_id)

    @mcp.tool()
    def prism_kg_neighbors(node_id: str, depth: int = 1) -> dict:
        """Return KG nodes and edges around a KG node ID."""
        return _prism_kg_neighbors(db_path, node_id, depth=depth)

    @mcp.resource("prism://project/{research_id}")
    def prism_project_resource(research_id: str) -> str:
        """PRISM project resource as JSON."""
        return _json(_prism_project(db_path, research_id))

    @mcp.resource("prism://file/{file_id}/markdown")
    def prism_markdown_resource(file_id: str) -> str:
        """PRISM converted Markdown resource as JSON."""
        return _json(_prism_markdown(db_path, file_id))

    @mcp.resource("prism://kg/node/{node_id}")
    def prism_kg_node_resource(node_id: str) -> str:
        """PRISM KG node neighborhood resource as JSON."""
        return _json(_prism_kg_neighbors(db_path, node_id, depth=1))

    return mcp


def run_mcp(db_path, transport="stdio", host="127.0.0.1", port=8877):
    mcp = create_mcp(db_path)
    normalized = (transport or "stdio").strip().lower()
    if normalized == "http":
        normalized = "streamable-http"
    if normalized in ("stdio",):
        return mcp.run(transport="stdio")
    if normalized not in ("streamable-http", "streamable_http"):
        raise ValueError("transport must be stdio or http")

    if hasattr(mcp, "settings"):
        try:
            mcp.settings.host = host
            mcp.settings.port = int(port)
        except Exception:
            pass

    attempts = [
        {"transport": "streamable-http", "host": host, "port": int(port), "stateless_http": True, "json_response": True},
        {"transport": "streamable-http", "host": host, "port": int(port)},
        {"transport": "streamable-http", "stateless_http": True, "json_response": True},
        {"transport": "streamable-http"},
    ]
    last_error = None
    for kwargs in attempts:
        try:
            return mcp.run(**kwargs)
        except TypeError as exc:
            last_error = exc
            continue
    raise RuntimeError("MCP Streamable HTTP 실행 인자를 SDK가 받지 못했습니다: {0}".format(last_error))
