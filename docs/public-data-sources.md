# 공공데이터 보도자료 1차 후보

2026년 이후 지자체 보도자료 RAG의 1차 원천은 공공데이터포털 또는 연계 OpenAPI입니다.
실제 수집에는 기관별 활용신청과 Swagger의 `base_url` 확인이 필요합니다.

| 후보 | 포털 URL | 메모 |
| --- | --- | --- |
| 공공데이터활용지원센터_목록조회서비스 | https://www.data.go.kr/data/15077093/openapi.do?recommendDataYn=Y | 기관명, 데이터명, 설명, 분류, 데이터유형 목록 탐색용 |
| 서울특별시 광진구_보도자료 | https://www.data.go.kr/data/15063658/openapi.do?recommendDataYn=Y | LINK/XML, 광진구 RSS endpoint 직접 제공 |
| 경기도 파주시_보도자료 | https://www.data.go.kr/data/15159546/openapi.do?recommendDataYn=Y | REST/JSON, 2026-05-18 등록, 2026년 조회 파라미터 후보 포함 |
| 경상남도_보도자료 | https://www.data.go.kr/data/15062546/openapi.do | REST/JSON+XML, 시간범위 2026년 1월부터 |
| 서울특별시 성북구_보도자료 조회 서비스 | https://www.data.go.kr/data/15159650/openapi.do | LINK/JSON+XML, 서울 열린데이터광장 연계 |
| 제주특별자치도 서귀포시_경제뉴스보도자료 | https://www.data.go.kr/data/15108427/openapi.do | LINK/XML, 서귀포시 자체 OpenAPI endpoint 제공 |
| 대구광역시 동구_대구 동구청 보도자료 목록 | https://www.data.go.kr/data/15110424/openapi.do | REST/JSON |
| 경기도 과천시_보도자료 | https://www.data.go.kr/data/15159541/openapi.do?recommendDataYn=Y | REST/JSON, 공공저작물 제1유형 |
| 경기도_뉴스포털_경기뉴스광장 | https://www.data.go.kr/data/15113315/openapi.do?recommendDataYn=Y | LINK/XML, 경기도 보도자료/뉴스 API. 시군 활용 대상 설명 있음 |
| 경기도_보도자료 현황 | https://www.data.go.kr/data/15034926/openapi.do?recommendDataYn=Y | LINK/XML, 상세 원문 공공누리 확인 필요 |
| 한국산업기술기획평가원_지역균형발전 지자체 정책보도 | https://www.data.go.kr/data/15106142/openapi.do?recommendDataYn=Y | 전국 지자체 정책보도 보조 원천 |

## 확인된 REST 경로

- 파주시: `https://apis.data.go.kr/4060000/pressrelease/pressRelease`
- 경상남도: `https://apis.data.go.kr/6480000/gyeongnamnewsinfo/gyeongnampressrelease`
- 대구 동구: `https://apis.data.go.kr/3420000/dongguOfficePressReleaseService/getDongguOfficePressRelease`
- 과천시: `https://apis.data.go.kr/3970000/newsList/list`
- 광진구: `https://www.gwangjin.go.kr/portal/bbs/B0000002/rssService.do?viewType=CONTBODY&bbsId=B02`
- 성북구: `http://openapi.seoul.go.kr:8088/{SEOUL_OPEN_DATA_KEY}/json/sbPressBoard/1/100/`
- 서귀포시 경제뉴스: `https://www.seogwipo.go.kr/openapi/sgpEconomicService/`

## 2026-06-30 추가 확인

- 성북구 `OA-22998`는 서울 열린데이터광장 Sheet Open API이며 서비스명은
  `sbPressBoard`입니다. 샘플 키(`sample`)로 2026-06-29 등록 보도자료가
  조회되어 `configs\sources.example.json`의 `seongbuk_press`에 반영했습니다.
- 경기도 뉴스포털 API 가이드는 보도자료 목록 URL을
  `https://gnews.gg.go.kr/rss/gnews_rss.do?servicekey={key}&bs_code=S017&page={page}&pagesize={page_size}&search_flag=1&keyword=`
  로 안내합니다. 상세 본문/첨부는 `number` 값을 `ca_code`로 넘기는
  `gnews_bodo_rss.do` view API에서 받아야 하므로, `gg_news_plaza`는
  `GNEWS_SERVICE_KEY`가 있는 환경에서만 수집하도록 비활성 템플릿으로 넣었습니다.
- `경기도_보도자료 현황`은 목록 자체는 제한 없음으로 표시되지만, 공공데이터포털
  설명상 상세 원문의 이용허락 조건은 보도자료별 공공누리 유형을 확인해야 합니다.

## 추가 검토 후보: 파일데이터 자동변환 API

공공데이터포털은 일부 CSV 파일데이터를 XML/JSON API로 자동변환해 제공합니다.
다만 주기가 연간이거나 기관 자체 다운로드 URL만 있는 경우가 있어, 실시간 RAG
원천보다는 보조/백필 corpus로 분리하는 편이 안전합니다.

| 후보 | 포털 URL | 메모 |
| --- | --- | --- |
| 서울특별시 서초구_홈페이지 보도자료 | https://www.data.go.kr/data/15038599/fileData.do?recommendDataYn=Y | 수시 자동 갱신, 서울 열린데이터 연계 URL |
| 서울특별시 영등포구_보도자료 정보 | https://www.data.go.kr/data/15115735/fileData.do?recommendDataYn=Y | 수시 자동 갱신, 제목/게시물 링크/작성일/부서/본문 |
| 인천광역시 미추홀구_보도자료 | https://www.data.go.kr/data/15095869/fileData.do | 연간 CSV, 공공데이터포털 XML/JSON 자동변환 표시 |
| 경상남도 하동군_보도자료 | https://www.data.go.kr/data/15156201/fileData.do?recommendDataYn=Y | 연간 CSV, 공공데이터포털 XML/JSON 자동변환 표시 |

## 수집 원칙

1. API 응답에 포함된 본문/상세 URL/첨부 URL만 사용합니다.
2. 상세 URL은 PDF/HWP/HWPX 링크 발견을 위한 1-hop만 허용합니다.
3. 기본 기간은 `2026-01-01` 이후입니다. 특정 연도 API는 `year=2026`처럼
   API가 제공하는 파라미터를 쓰고, 기간 API는 `bgngYmd=20260101`부터 조회합니다.
4. 상세 원문 이용허락은 API 목록 라이선스와 다를 수 있으므로 record metadata에
   `license`와 `portal_url`을 보존합니다.
5. 원본 PDF는 SHA-256으로 중복 제거하고, 페이지 단위 문서로 쪼개 근거 인용이
   가능하게 둡니다.
