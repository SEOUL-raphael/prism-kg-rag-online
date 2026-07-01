# 아키텍처

## 1차 배포형 구조

```text
공공데이터 API
  -> govrag harvest
  -> SQLite(raw records, attachments, documents, chunks, FTS5)
  -> govrag query / govrag serve
  -> 선택: Ollama 로컬 모델로 답변 생성
```

기본 패키지는 API 서버, DB 서버, 벡터 DB, 큐를 요구하지 않습니다. Windows 기관 PC나
소형 서버에서 Python venv + SQLite 파일로 시작하고, 성능 비교가 필요할 때만 같은
JSONL을 RAGFlow 또는 AnythingLLM에 넣습니다.

## 왜 RAGFlow를 바로 패키지화하지 않는가

RAGFlow는 문서 파싱/운영 UI가 강하지만 MySQL, Redis/Valkey, MinIO,
Elasticsearch/Infinity 등 운영 서비스가 많습니다. Docker 사용이 어려운 기관에는
설치 승인과 장애 대응 비용이 커집니다. 그래서 이번 패키지는 수집/정규화/근거
보존을 독립 모듈로 만들고, RAGFlow는 평가 기준선으로 분리합니다.

## 오픈소스 후보 검토

| 후보 | 장점 | 폐쇄망 설치형 판단 |
| --- | --- | --- |
| RAGFlow `infiniflow/ragflow` | 문서 파싱, 운영 UI, 인용형 QA가 강함 | 의존 서비스가 많아 Docker 어려운 기관의 1차 기본안으로는 무거움 |
| AnythingLLM `Mintplex-Labs/anything-llm` | 데스크톱/로컬 우선 UX, 운영 UI가 좋음 | 비교 평가용 UI로 적합. 표준 JSONL export를 통해 같은 corpus 적재 |
| Haystack `deepset-ai/haystack` | Python 파이프라인 구성력이 좋음 | 기관별 커스텀 RAG 로직 후보. 기본 패키지에는 의존성으로 넣지 않음 |
| LlamaIndex `run-llama/llama_index` | 커넥터와 인덱싱 추상화가 풍부함 | 빠른 PoC에는 좋지만 폐쇄망 최소 의존 기본안에는 과함 |

현재 패키지는 위 프로젝트의 “전체 운영 스택”을 재포장하지 않고, 공공데이터 수집,
문서 보존, SQLite FTS5 검색, JSONL 내보내기만 최소 코어로 고정합니다. 이렇게 두면
기관 PC 1대에서도 시작할 수 있고, 성능 비교가 필요할 때 같은 원천 DB를 RAGFlow,
AnythingLLM, Haystack 실험으로 넘길 수 있습니다.

## 데이터 모델

- `sources`: API 원천과 라이선스/설정
- `records`: 보도자료 1건의 정규화 결과
- `attachments`: PDF/HWP/HWPX 원문 파일과 해시
- `documents`: 본문 또는 첨부에서 추출한 텍스트
- `chunks`: RAG 검색 단위
- `chunks_fts`: SQLite FTS5 전문 검색 인덱스
- `ingest_runs`: 실행 이력과 오류

## HWP/HWPX 확장점

HWP/HWPX는 Python 내부 구현에 고정하지 않고 외부 추출기 계약으로 둡니다.

```text
hwp-extractor.exe --input raw.hwp --out-json parsed.json --out-md parsed.md
```

기본 후보는 Java 기반 `neolord0/hwplib` + `neolord0/hwpxlib`입니다. 계약만
유지하면 Rust/JS 구현체로 교체해도 수집 파이프라인은 그대로 유지됩니다.

## 폐쇄망 반입 단위

- Python wheelhouse
- 이 패키지 wheel
- 선택: PyMuPDF wheel
- 선택: Ollama Windows installer와 모델 blob
- 선택: HWP/HWPX extractor JAR 또는 exe
- `data/govrag.sqlite` 초기 빈 DB 또는 사전 수집 DB
