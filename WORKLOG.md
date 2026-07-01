# Worklog

## 2026-06-26 KST

완료:

- `D:\gov-rag-portable` 패키지 생성
- Docker-free SQLite 기반 RAG 수집/검색 루프 구현
- 공공데이터 보도자료 후보 7개 등록
- 파주시/경상남도/대구 동구/과천시 REST Base URL 및 GET 경로 반영
- PDF 다운로드/파싱 모듈과 HWP/HWPX 외부 추출기 계약 추가
- JSONL export 추가: RAGFlow/AnythingLLM 비교 적재용
- 단위 테스트 통과: 6개
- wheel 빌드 및 `wheelhouse\govrag_portable-0.1.0-py3-none-any.whl` 생성

검증:

```powershell
.\.venv\Scripts\python -m unittest discover -s tests
.\.venv\Scripts\python -m govrag list-sources --config configs\sources.example.json
.\.venv\Scripts\python -m govrag init-db --db data\smoke.sqlite
.\.venv\Scripts\python -m govrag export-jsonl --db data\smoke.sqlite --out exports\smoke.jsonl
```

현재 차단점:

- `DATA_GO_KR_SERVICE_KEY`, `SEOUL_OPEN_DATA_KEY`가 현재 환경에 없음
- 실제 2026년 보도자료 본문 수집은 기관별 활용신청 키가 필요함
- 서울 성북구는 `OA-22998` / `sbPressBoard`로 확정되어 샘플 수집 가능

## 2026-06-29 KST

완료:

- 공공데이터포털 `보도자료` + `dType=API` 검색 결과에서 지방정부 후보 추가 확인
- 신규 설정 추가:
  - 서울특별시 광진구_보도자료
  - 제주특별자치도 서귀포시_경제뉴스보도자료
  - 경기도_뉴스포털_경기뉴스광장
- 경기도 data.gg 서비스 페이지형 URL은 `requires_review: true`로 자동 수집 보호
- NABIS 지자체 정책보도 URL도 즉시 XML 응답이 아니어서 `requires_review: true`로 보호
- XML 본문 정규화 보강:
  - `contents`, `wtime` 필드 대응
  - HTML body를 plain text로 정리
  - Windows 콘솔 UTF-8 출력 보강
- 검증:
  - 단위 테스트 7개 통과
  - 2026 smoke: 광진구 RSS 10건 수집, 단 본문은 RSS에 없음
  - 2025 smoke: 서귀포시 3건 수집, 3개 청크 색인, 검색 출력 확인

추가 완료:

- 상세 HTML 본문 추출 옵션 추가: `detail_body.html_id`, `detail_body.stop_phrases`
- 광진구 `dbData` 본문 추출 설정 반영
- 광진구 2026년 RSS 10건 -> 상세 본문 보강 -> 20개 청크 색인 확인
- 상세 페이지의 HWP `fileDown.do` 첨부 링크 인식 보강
- `harvest --source-id` 옵션 추가
- 단위 테스트 12개 통과
- 파일데이터 자동변환 API 보조 후보 정리:
  - 서울특별시 서초구_홈페이지 보도자료
  - 서울특별시 영등포구_보도자료 정보
  - 인천광역시 미추홀구_보도자료
  - 경상남도 하동군_보도자료

## 2026-06-30 KST

완료:

- 서울특별시 성북구 `OA-22998` / `sbPressBoard` endpoint 확인
- `seongbuk_press`를 서울 열린데이터광장 URL 템플릿 기반 수집원으로 승격
- 샘플 키(`sample`) smoke:
  - 2026년 1페이지 5건 수집
  - 5개 API 본문 문서 생성
  - `성북구 수국길 도서관` 검색 결과 확인
- URL 템플릿 수집기 보강:
  - `{start}/{end}` 방식과 `{page}/{page_size}` 방식 모두 지원
  - XML namespace 태그(`dc:date`)를 일반 필드명(`date`)으로 정규화
  - 목록 항목의 `number` 등으로 상세 API를 호출해 본문/첨부를 병합하는 옵션 추가
- 경기도 뉴스포털 공식 API 가이드 확인:
  - 보도자료 목록: `gnews_rss.do`, `bs_code=S017`
  - 보도자료 상세/첨부: `gnews_bodo_rss.do`, `ca_code=number`
  - `GNEWS_SERVICE_KEY` 환경변수가 있을 때 사용할 수 있도록 `gg_news_plaza` 템플릿 반영
- 오픈소스 RAG 후보 비교 문서화:
  - RAGFlow, AnythingLLM, Haystack, LlamaIndex는 비교/확장 후보로 두고,
    기본 배포형은 SQLite 기반 최소 의존 코어로 유지

현재 차단점:

- `DATA_GO_KR_SERVICE_KEY`는 이번 실행 환경에만 주입했고 `runtime.local.env`에는 저장하지 않음
- `SEOUL_OPEN_DATA_KEY`, `GNEWS_SERVICE_KEY` 실키 없음
- GNews는 시군별 키가 있어야 실제 2026년 보도자료 smoke를 돌릴 수 있음
- 경기도 보도자료 상세 원문의 공공누리 유형은 항목별 확인이 필요함

추가 진행:

- 사용자가 제공한 공공데이터포털 키를 실행 환경 변수로만 주입해 API probe 수행
- 응답 가능 원천:
  - 서울특별시 광진구_보도자료: 2026년 10건 수집, 상세 본문 추출
  - 서울특별시 성북구_보도자료 조회 서비스: 샘플 endpoint 5건 수집
  - 제주특별자치도 서귀포시_경제뉴스보도자료: API 응답은 정상이나 2026년 필터 결과 0건
- 응답 실패 원천:
  - 경기도 파주시_보도자료: HTTP 403 Forbidden
  - 대구광역시 동구_대구 동구청 보도자료 목록: HTTP 403 Forbidden
  - 경기도 과천시_보도자료: HTTP 403 Forbidden
  - 경상남도_보도자료: HTTP 404 API not found
  - 경기도_뉴스포털_경기뉴스광장: 별도 `GNEWS_SERVICE_KEY` 필요
- RAG 전 단계 산출:
  - DB: `data\publicdata_2026_pre_rag.sqlite`
  - JSONL: `exports\publicdata_2026_pre_rag.jsonl`
  - 보고서: `exports\publicdata_2026_pre_rag_report.json`
  - records 15건, documents 15건, chunks 26건
  - 광진구 HWP 첨부 8건 다운로드, 대용량 HWP 2건은 서버 `IncompleteRead` 반복 실패
- 사용자 확인에 따라 대상 기간을 `2026년 이후 지자체 보도자료`로 명시:
  - CLI 기본 수집 기준을 `--from-year 2026`으로 변경
  - 특정 단년 수집이 필요할 때만 `--year 2026` 사용
  - 현재 DB의 실제 수집 레코드는 모두 2026년 날짜라 대상 조건에 부합

## 2026-06-29 09:00 KST 이후 이어갈 순서

1. 공공데이터포털/서울 열린데이터/경기도 뉴스포털 키를 `configs\runtime.local.env`에 입력
2. `configs\sources.local.json`에서 파주시, 경상남도, 대구 동구, 과천시, 성북구, 경기도 뉴스포털을 필요한 범위만 `enabled: true`로 전환
3. 먼저 첨부 다운로드 없이 2026년 이후 본문 수집:

   ```powershell
   .\.venv\Scripts\python -m govrag harvest --config configs\sources.local.json --from-year 2026 --max-pages 2
   .\.venv\Scripts\python -m govrag index
   .\.venv\Scripts\python -m govrag query "2026년 청년 정책 보도자료" --limit 5
   ```

4. 응답 필드가 맞으면 첨부 다운로드/파싱 포함 재실행:

   ```powershell
   .\scripts\run-public-data-harvest.ps1 -Config .\configs\sources.local.json -FromYear 2026 -MaxPages 5 -DownloadAttachments
   ```

5. 장시간 방치 수집이 필요하면 종료 시각을 지정해 반복 실행:

   ```powershell
   .\scripts\run-harvest-loop.ps1 -Config .\configs\sources.local.json -FromYear 2026 -MaxPages 5 -IntervalMinutes 120 -DownloadAttachments
   ```

6. `exports\ragflow-import.jsonl` 생성 후 RAGFlow/AnythingLLM 동일 corpus 비교

   ```powershell
   .\.venv\Scripts\python -m govrag export-jsonl --out exports\ragflow-import.jsonl
   ```
