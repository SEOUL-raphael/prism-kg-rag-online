# PRISM 2025+ KG-RAG

PRISM support uses the official Public Data Portal API spec:

https://www.data.go.kr/data/15080254/openapi.do#tab_layer_detail_function

Configure secrets in `configs/runtime.local.env` or in the current shell. Do not
put real keys in tracked config files.

```powershell
PRISM_API_KEY=...
MINIMAX_API_KEY=...
```

Typical local flow:

```powershell
python -m govrag.prism_cli harvest --db data\prism.sqlite --start-date 20250101 --daily-limit 900
python -m govrag.prism_cli enrich --db data\prism.sqlite --limit 100
python -m govrag.prism_cli download --db data\prism.sqlite --data-dir data
python -m govrag.prism_cli convert --db data\prism.sqlite --data-dir data
python -m govrag.prism_cli build-kg --db data\prism.sqlite
python -m govrag.prism_cli query "regional economy impact studies" --db data\prism.sqlite --json
python -m govrag.prism_cli serve --db data\prism.sqlite --host 127.0.0.1 --port 8765
```

The same commands are available under `govrag prism ...`.

When the Public Data Portal gateway is rate-limited, remaining detail records can
be enriched from the public PRISM backend without using `PRISM_API_KEY`:

```powershell
python -m govrag.prism_cli enrich --db data\prism.sqlite --limit 1000 --backend-only
```

Backend file records use PRISM's public blob endpoint internally:
`https://api.prism.go.kr/prism-be-asmt/v1/progress/download-file`.
The downloader stores the POST payload in `prism_files.file_url` query
parameters and uses POST when fetching those attachments.

For unattended continuation after the daily API limit resets, run:

```powershell
$env:PRISM_API_KEY="..."
.\scripts\run-prism-continuation.ps1
```

The continuation script enriches remaining projects within the daily limit,
downloads new public attachments, converts them, rebuilds the local KG/FTS
index, and writes timestamped logs/status files under `logs\`.

PDF conversion uses OpenDataLoader PDF when `govrag-portable[prism-pdf]` is
installed and Java 11+ is on `PATH`. The current packaged PyPI range is
`opendataloader-pdf>=1.8,<2`. HWP/HWPX conversion uses the rhwp-based
`rhwp-python` binding, currently packaged as `rhwp-python>=0.1.1,<0.2`.

The RAG path is:

1. MiniMax generates a KG search plan.
2. SQLite KG nodes and edges verify the candidate projects.
3. Markdown chunks for verified projects are searched with FTS5.
4. The response includes project, report, file, and chunk evidence.

Local UI:

```powershell
cd frontend
npm install
npm run build
cd ..
$env:PYTHONPATH="src"
python -m govrag.prism_cli serve --db data\prism.sqlite --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/`. The API is exposed under `/api/*`; legacy
`/prism/*` routes remain available.

MCP requires Python 3.10+:

```powershell
.\scripts\setup-mcp-venv.ps1
.\.venv-mcp\Scripts\python.exe -m govrag.prism_cli mcp --db data\prism.sqlite --transport stdio
.\.venv-mcp\Scripts\python.exe -m govrag.prism_cli mcp --db data\prism.sqlite --transport http --host 127.0.0.1 --port 8877
```

For the GitHub Pages + Supabase sharing path, see `docs/online-sharing.md`.
