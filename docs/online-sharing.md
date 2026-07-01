# PRISM KG-RAG 온라인 공유 전환

이 문서는 로컬 SQLite 기반 PRISM KG-RAG를 동료와 공유할 수 있도록 GitHub Pages 프론트엔드와 Supabase 백엔드로 나누어 배포하는 절차를 정리한다.

## 구성

- 프론트엔드: `frontend/` React/Vite 정적 앱
- 백엔드 데이터: Supabase Postgres `projects`, `reports`, `files`, `kg_nodes`, `kg_edges`, `chunks`
- 검색: 초기 버전은 `pg_trgm` 기반 RPC `search_chunks`, `kg_search`
- LLM: Supabase Edge Function `rag-query`에서 MiniMax 호출
- 원본 PDF/HWP: 온라인에는 올리지 않고, 메타데이터/KG/Markdown chunk만 공유

## 로컬 데이터 내보내기

```powershell
.\scripts\export-prism-supabase.ps1 -DbPath data\prism.sqlite -OutDir exports\supabase
```

결과 파일:

- `exports/supabase/projects.jsonl`
- `exports/supabase/reports.jsonl`
- `exports/supabase/files.jsonl`
- `exports/supabase/kg_nodes.jsonl`
- `exports/supabase/kg_edges.jsonl`
- `exports/supabase/chunks.jsonl`

## Supabase 적용

1. Supabase 프로젝트를 만든다.
2. `supabase/migrations/001_prism_kg_rag.sql`을 Supabase SQL Editor 또는 Supabase CLI migration으로 적용한다.
3. Edge Function secret을 설정한다.

```powershell
supabase secrets set MINIMAX_API_KEY=...
supabase secrets set MINIMAX_MODEL=MiniMax-Text-01
supabase secrets set SUPABASE_PUBLISHABLE_KEY=...
```

4. JSONL snapshot을 적재한다. 적재에는 서버용 `SUPABASE_SECRET_KEY` 또는 fallback `SUPABASE_SERVICE_ROLE_KEY`를 현재 셸 환경변수로만 둔다.

```powershell
$env:SUPABASE_URL="https://<project-ref>.supabase.co"
$env:SUPABASE_SECRET_KEY="..."
.\scripts\load-supabase-snapshot.ps1 -InputDir exports\supabase -Verify
```

5. Auth는 초대 이메일 또는 magic link 기반으로 제한하고, 필요하면 Supabase Dashboard에서 Site URL과 Redirect URL을 GitHub Pages 주소로 맞춘다.

## Edge Function

`supabase/functions/rag-query/index.ts`는 로그인 사용자의 JWT를 받아 Supabase RLS가 적용된 상태로 `kg_search`, `search_chunks`를 호출한다. MiniMax API 키는 Edge Function secret으로만 읽으며 브라우저 응답, 로그, 번들에는 노출하지 않는다.

## GitHub Pages

`.github/workflows/frontend-pages.yml`은 `frontend`를 빌드해 GitHub Pages로 배포한다.

필요한 GitHub Actions 설정:

- Secret `VITE_SUPABASE_URL`
- Secret `VITE_SUPABASE_PUBLISHABLE_KEY`
- Variable `VITE_BASE_PATH`: 저장소 하위 경로 배포 시 `/<repo-name>/`

브라우저에는 publishable key만 들어간다. `SUPABASE_SECRET_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `MINIMAX_API_KEY`는 GitHub Pages나 프론트엔드 번들에 넣지 않는다.

## 현재 제한

Private repository에서 GitHub Pages를 사용하려면 계정 또는 조직의 GitHub plan이 Pages private 배포를 지원해야 한다. 지원되지 않는 경우에는 저장소를 public으로 전환하거나, GitHub Pages 대신 별도 정적 호스팅을 사용해야 한다.
