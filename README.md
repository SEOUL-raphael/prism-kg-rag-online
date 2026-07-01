# Gov RAG Portable

공공 폐쇄망에 들고 들어가기 쉬운 Docker-free RAG 패키지 초안입니다.
첫 목표는 지방정부 보도자료 API를 2026년 이후 기준으로 수집하고, 첨부 PDF를
페이지 단위로 읽어 SQLite 기반 검색/RAG 근거로 만드는 것입니다.

## 방향

- 외부 의존 서비스 없음: 기본 저장소는 SQLite 파일 하나입니다.
- 선택 의존만 사용: PDF 파싱은 PyMuPDF, 생성/임베딩은 로컬 Ollama가 있으면 사용합니다.
- 수집 원천은 공공데이터포털/지자체 OpenAPI 중심이며 광범위 웹 크롤링은 하지 않습니다.
- RAGFlow/AnythingLLM 성능 비교를 위해 JSONL 내보내기를 제공합니다.

## 빠른 시작

```powershell
cd D:\gov-rag-portable
.\scripts\setup-venv.ps1
.\scripts\run-public-data-harvest.ps1 -Config .\configs\sources.local.json
.\scripts\start-search-server.ps1
```

`configs\sources.example.json`을 `configs\sources.local.json`으로 복사한 뒤
공공데이터포털 활용신청으로 받은 `base_url`, `serviceKey` 환경변수를 채우면 됩니다.

## 주요 명령

```powershell
.\.venv\Scripts\python -m govrag init-db
.\.venv\Scripts\python -m govrag harvest --config .\configs\sources.local.json --from-year 2026 --download-attachments
.\.venv\Scripts\python -m govrag parse-pdfs
.\.venv\Scripts\python -m govrag index
.\.venv\Scripts\python -m govrag query "파주시 청년 정책 보도자료"
.\.venv\Scripts\python -m govrag export-jsonl --out .\exports\ragflow-import.jsonl
```

원천 하나만 빠르게 검증할 때는 다음처럼 실행합니다.

```powershell
.\.venv\Scripts\python -m govrag harvest --config .\configs\sources.example.json --include-disabled --source-id gwangjin_press_rss --from-year 2026
```

서울 열린데이터광장 샘플 키로 성북구 보도자료 smoke를 돌릴 수 있습니다.

```powershell
.\.venv\Scripts\python -m govrag harvest --config .\configs\sources.example.json --include-disabled --source-id seongbuk_press --from-year 2026 --max-pages 1
.\.venv\Scripts\python -m govrag index
.\.venv\Scripts\python -m govrag query "성북구 수국길 도서관" --limit 3
```

경기도 뉴스포털 보도자료는 `GNEWS_SERVICE_KEY`가 있을 때 `gg_news_plaza`를
켜서 목록 API와 상세 API를 함께 수집합니다.

장시간 무인 수집은 다음처럼 로그를 남기며 반복 실행할 수 있습니다.

```powershell
.\scripts\run-harvest-loop.ps1 -Config .\configs\sources.local.json -FromYear 2026 -MaxPages 5 -DownloadAttachments
```

## 현재 포함 범위

- 공공데이터 OpenAPI JSON/XML 수집기
- 보도자료 필드 정규화
- 상세 URL 안의 PDF/HWP/HWPX 링크 제한 추출
- PDF 다운로드 및 SHA-256 중복 확인
- PyMuPDF 기반 페이지 텍스트 추출
- HWP/HWPX 외부 추출기 계약 래퍼
- SQLite FTS5 기반 검색 API
- 선택적 Ollama 생성 답변
- 폐쇄망 반입용 wheelhouse 생성 스크립트

## 한계와 다음 작업

- 실제 기관별 API `base_url`과 응답 필드는 활용신청 뒤 Swagger에서 확정해야 합니다.
- HWP/HWPX는 Java `hwplib/hwpxlib` CLI 추출기를 별도 빌드한 뒤 연결하는 설계입니다.
- 스캔 PDF OCR은 선택 프로파일로 남겨 두었습니다. 폐쇄망에서는 Tesseract/상용 OCR 승인 여부가 먼저입니다.
