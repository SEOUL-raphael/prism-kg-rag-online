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

SQL Editor에서 `chunks_text_trgm` 생성이 timeout되면 `psql`로 직접 연결해 실행한다. pooler 주소는 Supabase Dashboard의 **Connect** 화면에서 확인하고, 비밀번호에 특수문자가 있으면 URL에 직접 넣지 말고 `PGPASSWORD` 환경변수로 넘긴다.

```powershell
$env:PGPASSWORD="<database-password>"
$db="postgresql://postgres.<project-ref>@aws-1-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require&connect_timeout=10"
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" $db -v ON_ERROR_STOP=1 -f supabase\sql\after-bulk-load.sql
Remove-Item Env:PGPASSWORD
```

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

현재 배포 URL:

```text
https://seoul-raphael.github.io/prism-kg-rag-online/
```

필요한 GitHub Actions 설정:

- Secret `VITE_SUPABASE_URL`
- Secret `VITE_SUPABASE_PUBLISHABLE_KEY`
- Variable `VITE_BASE_PATH`: 저장소 하위 경로 배포 시 `/<repo-name>/`

브라우저에는 publishable key만 들어간다. `SUPABASE_SECRET_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `MINIMAX_API_KEY`는 GitHub Pages나 프론트엔드 번들에 넣지 않는다.

## 현재 상태와 제한

GitHub Pages 배포는 활성화되어 있다. 레포지토리는 Pages 제한을 피하기 위해 public으로 전환했으며, 원본 데이터(`data/`, `exports/`, `logs/`)와 로컬 환경 파일(`.env`, `configs/runtime.local.env`)은 `.gitignore`로 제외한다.

public 레포지토리에 올리면 안 되는 값:

- `SUPABASE_SECRET_KEY`
- `SUPABASE_SERVICE_ROLE_KEY`
- `MINIMAX_API_KEY`
- PRISM 공공데이터 API key
- Database password

현재 남은 제한은 Supabase Edge Function 배포다. `rag-query` 배포와 Edge Function secret 설정에는 Supabase Management Access Token이 필요하다. 이 토큰이 없으면 GitHub Pages UI와 Supabase 데이터 조회/RPC는 가능하지만, 온라인 MiniMax RAG 답변 프록시는 아직 활성화되지 않는다.

## 점검

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check-online-readiness.ps1
```

정상 기준:

- GitHub 인증과 repo 접근 OK
- GitHub frontend secret OK
- Supabase schema OK
- GitHub Pages OK
- Edge Function 배포 전이면 `supabase_management_auth`는 access token 없음으로 표시될 수 있음
