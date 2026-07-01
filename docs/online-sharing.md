# PRISM KG-RAG 온라인 공유 전환

이 문서는 로컬 SQLite 기반 PRISM KG-RAG를 동료들과 공유하기 위해 프론트는 GitHub Pages, 백엔드는 Supabase로 나누는 절차를 정리한다.

## 구성

- 프론트: `frontend/` React/Vite 정적 앱
- 백엔드 데이터: Supabase Postgres `projects`, `reports`, `files`, `kg_nodes`, `kg_edges`, `chunks`
- 검색: 초기 버전은 `pg_trgm` 기반 RPC `search_chunks`, `kg_search`
- LLM: Supabase Edge Function `rag-query`에서 MiniMax 호출
- 원본 PDF/HWP: 온라인에는 올리지 않고 메타데이터와 Markdown chunk만 공유

## 로컬 데이터 내보내기

```powershell
.\scripts\export-prism-supabase.ps1 -Db data\prism.sqlite -Out exports\supabase
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
2. `supabase/migrations/001_prism_kg_rag.sql`을 SQL Editor나 Supabase CLI migration으로 적용한다.
3. JSONL 파일을 테이블별로 적재한다. 대용량 `chunks.jsonl`은 배치로 나눠 넣는 것이 좋다.
4. Auth는 초대 이메일 기반으로 제한한다.
5. Edge Function secret을 설정한다.

```powershell
supabase secrets set MINIMAX_API_KEY=...
supabase secrets set MINIMAX_MODEL=MiniMax-Text-01
supabase secrets set SUPABASE_PUBLISHABLE_KEY=...
```

## Edge Function

`supabase/functions/rag-query/index.ts`는 사용자 JWT를 받아 RLS가 적용된 상태로 `kg_search`, `search_chunks`를 호출하고, MiniMax 답변을 생성한다. MiniMax 키는 브라우저와 응답에 노출하지 않는다.

## GitHub Pages

`.github/workflows/frontend-pages.yml`은 `frontend`를 빌드해 Pages에 배포한다.

필요한 저장소 변수/시크릿:

- `VITE_BASE_PATH`: Pages 경로가 저장소 하위 경로이면 `/<repo-name>/`
- `VITE_API_BASE`: 로컬 API가 아닌 별도 API를 둘 때 사용
- `VITE_SUPABASE_URL`
- `VITE_SUPABASE_PUBLISHABLE_KEY`

현재 UI는 로컬 `/api/*` 호출을 우선 지원한다. Supabase 직접 로그인과 Edge Function 호출 모드는 후속 확장에서 같은 화면 구조에 붙이면 된다.
