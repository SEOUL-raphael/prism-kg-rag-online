# PRISM KG-RAG 온라인 공유 전환

이 문서는 로컬 SQLite 기반 PRISM KG-RAG를 동료와 공유할 수 있도록 GitHub 프론트엔드와 Supabase 백엔드로 나누어 배포하는 절차를 정리한다.

## 구성

- 프론트엔드: `frontend/` React/Vite 정적 앱
- 백엔드 데이터: Supabase Postgres `projects`, `reports`, `files`, `kg_nodes`, `kg_edges`, `chunks`
- 검색: `pg_trgm` 기반 RPC `search_chunks`, KG RPC `kg_search`
- LLM: Supabase Edge Function `rag-query`에서 MiniMax 호출
- 원본 PDF/HWP: 온라인에는 올리지 않고 메타데이터, KG, Markdown chunk만 공유

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

## Supabase 테이블 적용

Supabase SQL Editor에서 `supabase/migrations/001_prism_kg_rag.sql`을 실행한다. 이미 테이블을 만들었더라도 다시 실행할 수 있게 작성되어 있으며, 함수와 권한 정책을 최신 상태로 맞춘다.

대량 적재 전에 `chunks` 텍스트 검색 인덱스가 있으면 적재가 느려진다. 필요하면 먼저 아래 파일의 SQL을 실행한다.

```text
supabase/sql/before-bulk-load.sql
```

## JSONL 적재

서버용 키는 환경변수로만 넣고 파일에 저장하지 않는다.

```powershell
$env:SUPABASE_URL="https://<project-ref>.supabase.co"
$env:SUPABASE_SECRET_KEY="<server-side-secret-key>"
python scripts\load_supabase_snapshot.py --dir exports\supabase --batch-size 1000 --verify
```

특정 테이블만 이어 적재할 때:

```powershell
python scripts\load_supabase_snapshot.py --dir exports\supabase --tables chunks --skip-rows 73800 --insert-only --verify
```

## 대량 적재 후 처리

`chunks.jsonl` 적재가 끝나면 Supabase SQL Editor에서 아래 파일의 SQL을 실행한다.

```text
supabase/sql/after-bulk-load.sql
```

이 SQL은 다음 작업을 한다.

- `chunks.text` 검색용 trigram 인덱스 복구
- `chunks.file_id`, `files.status` 보조 인덱스 생성
- 통계 갱신
- PostgREST schema reload 알림

## Edge Function

`supabase/functions/rag-query/index.ts`는 로그인 사용자의 JWT를 받아 RLS가 적용된 상태로 `kg_search`, `search_chunks`를 호출한다. MiniMax API 키는 Edge Function secret으로만 읽고 브라우저, 로그, 응답, 번들에는 노출하지 않는다.

배포에는 Supabase Management Access Token이 필요하다. 프로젝트 API 키, anon key, service role JWT, JWT secret만으로는 Functions 배포와 secret 설정을 할 수 없다.

```powershell
$env:SUPABASE_ACCESS_TOKEN="<supabase-management-access-token>"
npx supabase login --token $env:SUPABASE_ACCESS_TOKEN
npx supabase secrets set --project-ref <project-ref> MINIMAX_API_KEY=...
npx supabase secrets set --project-ref <project-ref> MINIMAX_MODEL=MiniMax-Text-01
npx supabase secrets set --project-ref <project-ref> SUPABASE_PUBLISHABLE_KEY=...
npx supabase functions deploy rag-query --project-ref <project-ref> --use-api
```

## GitHub Pages

`.github/workflows/frontend-pages.yml`은 `frontend`를 빌드해 GitHub Pages로 배포한다.

필요한 GitHub Actions 설정:

- Secret `VITE_SUPABASE_URL`
- Secret `VITE_SUPABASE_PUBLISHABLE_KEY`
- Variable `VITE_BASE_PATH`: 저장소 하위 경로 배포 시 `/<repo-name>/`

브라우저에는 publishable key만 들어간다. `SUPABASE_SECRET_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `MINIMAX_API_KEY`는 GitHub Pages나 프론트엔드 번들에 넣지 않는다.

## 현재 제한

Private repository에서 GitHub Pages를 사용하려면 계정 또는 조직의 GitHub plan이 private Pages 배포를 지원해야 한다. 현재 점검 결과 이 private repository는 Pages가 플랜 제한으로 막혀 있다.

선택지는 다음 중 하나다.

- 저장소를 public으로 전환하고 GitHub Pages 사용
- GitHub 유료 플랜으로 private Pages 사용
- GitHub는 코드 저장소로 유지하고 Render, Vercel, Netlify 같은 별도 정적 호스팅 사용

## 점검

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check-online-readiness.ps1
```

정상 기준:

- GitHub 인증과 repo 접근 OK
- GitHub frontend secret OK
- Supabase schema OK
- Edge Function 배포 전이면 `supabase_management_auth`는 access token 없음으로 표시될 수 있음
- private repo Pages 제한이 있으면 `github_pages`는 false로 표시됨
