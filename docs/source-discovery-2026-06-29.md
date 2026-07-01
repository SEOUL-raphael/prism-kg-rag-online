# Source Discovery: 2026-06-29

## 탐색 방법

- 공공데이터포털 검색어: `보도자료`
- 필터: `dType=API`
- 확인 URL: `https://www.data.go.kr/tcs/dss/selectDataSetList.do?keyword=보도자료&conditionType=search&dType=API`
- 검색 결과 수: 포털 HTML 기준 오픈 API 4,045건

## 지방정부/RAG 1차 후보로 분류한 API

| 우선순위 | 데이터명 | 포털 URL | 유형 | 상태 |
| --- | --- | --- | --- | --- |
| 1 | 서울특별시 광진구_보도자료 | https://www.data.go.kr/data/15063658/openapi.do?recommendDataYn=Y | LINK/XML | RSS endpoint 확인, 설정 반영 |
| 1 | 경기도 파주시_보도자료 | https://www.data.go.kr/data/15159546/openapi.do?recommendDataYn=Y | REST/JSON | 2026년 기간 파라미터 확인, 설정 반영 |
| 1 | 경상남도_보도자료 | https://www.data.go.kr/data/15062546/openapi.do | REST/JSON+XML | 시간범위 2026년 1월부터, 설정 반영 |
| 1 | 대구광역시 동구_대구 동구청 보도자료 목록 | https://www.data.go.kr/data/15110424/openapi.do | REST/JSON | 설정 반영 |
| 1 | 경기도 과천시_보도자료 | https://www.data.go.kr/data/15159541/openapi.do?recommendDataYn=Y | REST/JSON | 2026-05-18 등록, 설정 반영 |
| 1 | 서울특별시 성북구_보도자료 조회 서비스 | https://www.data.go.kr/data/15159650/openapi.do | LINK/JSON+XML | `OA-22998` / `sbPressBoard` endpoint 확인, 설정 반영 |
| 2 | 제주특별자치도 서귀포시_경제뉴스보도자료 | https://www.data.go.kr/data/15108427/openapi.do | LINK/XML | 자체 endpoint 확인, 설정 반영. 2026-06-29 응답은 2025년 자료 위주 |
| 2 | 경기도_뉴스포털_경기뉴스광장 | https://www.data.go.kr/data/15113315/openapi.do?recommendDataYn=Y | LINK/XML | GNews 공식 목록/상세 API 확인, `GNEWS_SERVICE_KEY` 필요 |
| 2 | 경기도_보도자료 현황 | https://www.data.go.kr/data/15034926/openapi.do?recommendDataYn=Y | LINK/XML | 경기도 뉴스포털 상세 원문 공공누리 확인 필요 |
| 3 | 한국산업기술기획평가원_지역균형발전 지자체 정책보도 | https://www.data.go.kr/data/15106142/openapi.do?recommendDataYn=Y | LINK/XML | 17개 시도 정책보도 보조 원천, 상세 파라미터 재확인 필요 |

## 제외 또는 보조 후보

- 중앙부처 보도자료: 과기정통부, 통일부, 외교부, 문체부 등은 지방정부 1차 대상이 아니므로 평가 corpus에서는 분리합니다.
- 공공기관 보도자료: 한국문학번역원, 한국체육산업개발 등은 지방행정 RAG 범위 밖입니다.
- 파일데이터 자동변환: 서초구, 영등포구, 미추홀구, 하동군 등은 백필용으로 검토합니다.

## 다음 확인 작업

1. 공공데이터포털 활용신청 후 Swagger에서 REST 상세 path/response schema 확인
2. 경기도 `GNEWS_SERVICE_KEY` 확보 후 `gg_news_plaza` 실제 2026년 smoke
3. 경기도 보도자료별 상세 원문 공공누리 유형 저장 방식 확정
4. NABIS 지자체 정책보도 활용가이드의 필수 파라미터 확인
5. 파일데이터 자동변환 API 호출 방식 모듈 추가 여부 결정
6. 광진구 RSS는 제목/링크/일자만 제공하므로 상세 페이지 본문 추출 규칙 별도 작성
