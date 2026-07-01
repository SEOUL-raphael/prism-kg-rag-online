import json
import html
import os
import re
import urllib.parse

from .http_client import HttpError, request_json_post, request_text
from .normalizer import as_list, text_value
from .public_data import parse_payload
from .storage import (
    insert_prism_api_failure,
    prism_api_calls_today,
    record_prism_api_call,
)


DEFAULT_BASE_URL = "https://apis.data.go.kr/1741000/prism_v2"
PRISM_WEB_DETAIL = "https://www.prism.go.kr/homepage/asmt/{research_id}"
PRISM_BACKEND_INFO_URL = "https://api.prism.go.kr/prism-be-asmt/v1/entire/info"
PRISM_BACKEND_DOWNLOAD_URL = "https://api.prism.go.kr/prism-be-asmt/v1/progress/download-file"
PRISM_FILE_DOWNLOAD_URL = "https://api.prism.go.kr/prism-be-file/v1/file/downloadFile"


class PrismQuotaExceeded(RuntimeError):
    pass


def redact_params(params):
    redacted = dict(params or {})
    for key in list(redacted.keys()):
        if str(key).lower() in ("servicekey", "apikey", "api_key", "key", "authkey"):
            redacted[key] = "***"
    return redacted


def require_prism_key():
    key = os.environ.get("PRISM_API_KEY", "").strip()
    if not key:
        raise RuntimeError("PRISM_API_KEY is not configured.")
    return key


def normalize_service_key(key):
    # Public Data Portal often displays an already URL-encoded key. urllib will
    # encode query params for us, so decode once to avoid serviceKey=%253D%253D.
    if "%" in key:
        try:
            return urllib.parse.unquote(key)
        except Exception:
            return key
    return key


def find_first_key(value, key_names):
    wanted = {name.lower() for name in key_names}
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in wanted:
                return child
        for child in value.values():
            found = find_first_key(child, key_names)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_first_key(child, key_names)
            if found is not None:
                return found
    return None


def payload_code(payload):
    return text_value(find_first_key(payload, ["resultCode", "returnReasonCode", "code"]))


def payload_message(payload):
    return text_value(find_first_key(payload, ["resultMsg", "returnAuthMsg", "message", "msg"]))


def is_success_payload(payload):
    code = payload_code(payload)
    if not code:
        return True
    return code.upper() in ("0", "00", "0000", "OK", "SUCCESS", "INFO-000")


def normalize_payload(text):
    stripped = text.lstrip()
    fmt = "xml" if stripped.startswith("<") else "json"
    return parse_payload(text, fmt)


def normalize_date_param(value):
    value = str(value or "").strip()
    if not value:
        return ""
    return re.sub(r"[^0-9]", "", value)[:8]


def normalize_backend_date(value):
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    if len(digits) >= 8:
        return "{0}-{1}-{2}".format(digits[:4], digits[4:6], digits[6:8])
    return text_value(value)


def clean_backend_text(value):
    text = html.unescape(text_value(value))
    text = re.sub(r"<\s*br[\s\xa0/]*/?\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\xa0", " ")
    return re.sub(r"[ \t\r\f\v]+", " ", text).strip()


def get_total_count(payload):
    value = find_first_key(payload, ["totalCount", "total_count"])
    try:
        return int(str(value).replace(",", ""))
    except Exception:
        return 0


def extract_research_rows(payload):
    rows = find_first_key(payload, ["research"])
    if isinstance(rows, dict):
        nested = find_first_key(rows, ["item", "items", "research"])
        if nested is not None and nested is not rows:
            rows = nested
    return [row for row in as_list(rows) if isinstance(row, dict)]


def extract_detail_sections(payload):
    return {
        "research": find_first_key(payload, ["research"]) or {},
        "contract": find_first_key(payload, ["contract"]) or {},
        "reportInfo": find_first_key(payload, ["reportInfo", "report_info"]) or {},
        "use": find_first_key(payload, ["use"]) or {},
        "kogl": find_first_key(payload, ["kogl"]) or {},
    }


def first_text(record, *names):
    lower = {str(k).lower(): k for k in (record or {}).keys()}
    for name in names:
        if name in record:
            value = text_value(record.get(name))
            if value:
                return value
        key = lower.get(str(name).lower())
        if key is not None:
            value = text_value(record.get(key))
            if value:
                return value
    return ""


def project_from_list_row(row):
    return {
        "research_id": first_text(row, "research_id", "researchId", "asmtId"),
        "report_open_yn": first_text(row, "report_open_yn", "reportOpenYn"),
        "research_name": first_text(row, "research_name", "researchName", "asmtNm"),
        "organ_name": first_text(row, "organ_name", "organName", "instNm"),
        "researcher_name": first_text(row, "researcher_name", "researcherName", "rscrNm"),
        "charge_person_department": first_text(row, "charge_person_department", "chargePersonDepartment", "asmtPicDeptNm"),
        "biz_name": first_text(row, "biz_name", "bizName", "clsfSysNm"),
        "research_date": first_text(row, "research_date", "researchDate"),
        "issued_year": first_text(row, "issued_year", "issuedYear"),
        "list": row,
    }


def project_from_detail(research_id, sections, payload):
    research = sections.get("research") if isinstance(sections.get("research"), dict) else {}
    return {
        "research_id": research_id,
        "research_name": first_text(research, "research_name", "researchName"),
        "organ_name": first_text(research, "organ_name", "organName"),
        "charge_person_department": first_text(research, "charge_person_department", "chargePersonDepartment"),
        "charge_person_phone_no": first_text(research, "charge_person_phoneNo", "charge_person_phone_no", "chargePersonPhoneNo"),
        "research_start_date": first_text(research, "research_start_date", "researchStartDate"),
        "research_end_date": first_text(research, "research_end_date", "researchEndDate"),
        "brm_biz_id": first_text(research, "brm_biz_id", "brmBizId"),
        "brm_biz_name": first_text(research, "brm_biz_name", "brmBizName"),
        "research_outline": first_text(research, "research_outline", "researchOutline"),
        "detail": payload,
    }


def report_from_detail(research_id, sections):
    report = sections.get("reportInfo") if isinstance(sections.get("reportInfo"), dict) else {}
    return {
        "research_id": research_id,
        "title": first_text(report, "title"),
        "table_contents": first_text(report, "tableContents", "table_contents"),
        "summary": first_text(report, "summary"),
        "keyword": first_text(report, "keyword"),
        "issued_year": first_text(report, "issuedYear", "issued_year"),
        "raw": report,
    }


def normalize_file_url(raw):
    url = first_text(raw, "file_url", "fileUrl", "url", "downloadUrl", "atchFileUrl")
    if url:
        return url
    if first_text(raw, "asmtId") and first_text(raw, "fileTypeCd") and first_text(raw, "fileSn"):
        params = {
            "asmtId": first_text(raw, "asmtId"),
            "fileTypeCd": first_text(raw, "fileTypeCd"),
            "fileSn": first_text(raw, "fileSn"),
            "fileWkky": first_text(raw, "fileWkky"),
            "pdfTrsfYn": first_text(raw, "pdfTrsfYn"),
            "fileNm": first_text(raw, "fileNm", "fileName", "orgnlAtchFileNm"),
        }
        return PRISM_BACKEND_DOWNLOAD_URL + "?" + urllib.parse.urlencode(params)
    path = first_text(raw, "atchFilePathNm", "filePath")
    if not path:
        return ""
    params = {
        "atchFilePathNm": path,
        "atchFileSz": first_text(raw, "atchFileSz", "file_size", "fileSize"),
        "orgnlAtchFileNm": first_text(raw, "orgnlAtchFileNm", "file_name", "fileName"),
    }
    ext_hint = os.path.splitext(params["orgnlAtchFileNm"])[1].lower().lstrip(".")
    if ext_hint:
        params["type"] = ext_hint
    return PRISM_FILE_DOWNLOAD_URL + "?" + urllib.parse.urlencode(params)


def files_from_detail(research_id, sections):
    files = []
    report = sections.get("reportInfo") if isinstance(sections.get("reportInfo"), dict) else {}
    for raw in as_list(report.get("url") if isinstance(report, dict) else None):
        if isinstance(raw, dict):
            files.append(file_from_raw(research_id, "report", raw))
    for raw in as_list(sections.get("use")):
        if isinstance(raw, dict):
            files.append(file_from_raw(research_id, "use", raw))
    return [item for item in files if item.get("file_url") or item.get("file_name")]


def file_from_raw(research_id, source_section, raw):
    return {
        "research_id": research_id,
        "source_section": source_section,
        "file_url": normalize_file_url(raw),
        "file_type": first_text(raw, "file_type", "fileType", "type", "fileTypeCd"),
        "file_name": first_text(raw, "file_name", "fileName", "orgnlAtchFileNm", "fileNm"),
        "file_size": first_text(raw, "file_size", "fileSize", "atchFileSz"),
        "status": "pending",
        "raw": raw,
    }


def files_from_backend_payload(research_id, payload):
    files = []
    stack = [payload]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            if normalize_file_url(current) or first_text(current, "file_name", "fileName", "orgnlAtchFileNm"):
                files.append(file_from_raw(research_id, "backend", current))
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
    seen = set()
    unique = []
    for item in files:
        key = (item.get("file_url"), item.get("file_name"), item.get("file_type"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def backend_result_data(payload):
    if isinstance(payload, dict) and isinstance(payload.get("resultData"), dict):
        return payload["resultData"]
    return payload if isinstance(payload, dict) else {}


def project_from_backend_detail(research_id, payload):
    data = backend_result_data(payload)
    detail = data.get("asmtDetail") if isinstance(data.get("asmtDetail"), dict) else {}
    info_code = first_text(detail, "infoRlsCd")
    start = normalize_backend_date(first_text(detail, "rschBgngYmd"))
    return {
        "research_id": research_id,
        "report_open_yn": "Y" if info_code == "B0030001" else "N" if info_code else "",
        "research_name": first_text(detail, "asmtNm"),
        "organ_name": first_text(detail, "instNm"),
        "researcher_name": first_text(detail, "rscrNm"),
        "charge_person_department": first_text(detail, "asmtPicDeptNm"),
        "charge_person_phone_no": first_text(detail, "asmtPicTelno"),
        "research_start_date": start,
        "research_end_date": normalize_backend_date(first_text(detail, "rschEndYmd")),
        "brm_biz_name": " > ".join(
            part for part in (first_text(detail, "hghrkFwkClsfSysNm"), first_text(detail, "clsfSysNm")) if part
        ),
        "issued_year": start[:4] if start else "",
        "detail": payload,
    }


def reports_from_backend_detail(research_id, payload):
    data = backend_result_data(payload)
    reports = []
    for raw in as_list(data.get("reportList")):
        if not isinstance(raw, dict):
            continue
        reports.append(
            {
                "id": "{0}-backend-report-{1}".format(research_id, first_text(raw, "rptpSn") or len(reports) + 1),
                "research_id": research_id,
                "title": clean_backend_text(first_text(raw, "rptpTtl")),
                "table_contents": clean_backend_text(first_text(raw, "rptpDtlCn")),
                "summary": clean_backend_text(first_text(raw, "thssSmryCn")),
                "keyword": clean_backend_text(first_text(raw, "kywdCn")),
                "issued_year": first_text(raw, "pblcnYr"),
                "raw": raw,
            }
        )
    return reports


def contract_from_backend_detail(payload):
    data = backend_result_data(payload)
    detail = data.get("asmtDetail") if isinstance(data.get("asmtDetail"), dict) else {}
    return {
        "research_organ_id": "",
        "research_organ_type_name": first_text(detail, "rschInstNm"),
        "researcher_name": first_text(detail, "rscrNm"),
        "contract_date": normalize_backend_date(first_text(detail, "ctrtDt")),
        "contract_type_name": first_text(detail, "ctrtSeCd"),
        "contract_cost": first_text(detail, "ctrtAmt"),
        "raw": detail,
    }


def kogl_from_backend_detail(payload):
    data = backend_result_data(payload)
    detail = data.get("asmtDetail") if isinstance(data.get("asmtDetail"), dict) else {}
    content = {
        "koglRlsYn": first_text(detail, "koglRlsYn"),
        "koglCmrcUtztnYn": first_text(detail, "koglCmrcUtztnYn"),
        "koglWrgsChgYn": first_text(detail, "koglWrgsChgYn"),
        "koglPrvtRsn": first_text(detail, "koglPrvtRsn"),
    }
    return {
        "kogl_open_yn": first_text(detail, "koglRlsYn"),
        "kogl_content": json.dumps(content, ensure_ascii=False, sort_keys=True),
        "raw": detail,
    }


class PrismApiClient:
    def __init__(self, conn=None, base_url=DEFAULT_BASE_URL, quota_limit=900, timeout=30):
        self.conn = conn
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.service_key = normalize_service_key(require_prism_key())
        self.quota_limit = int(quota_limit or 900)
        self.timeout = int(timeout or 30)

    def remaining_quota(self):
        if not self.conn:
            return self.quota_limit
        return max(0, self.quota_limit - prism_api_calls_today(self.conn))

    def call(self, endpoint, params):
        if self.conn and prism_api_calls_today(self.conn) >= self.quota_limit:
            raise PrismQuotaExceeded("PRISM daily API limit reached ({0}).".format(self.quota_limit))
        clean = dict(params or {})
        clean["serviceKey"] = self.service_key
        url = self.base_url + "/" + endpoint.lstrip("/")
        recorded_failure = False
        try:
            text, headers, final_url = request_text(url, params=clean, timeout=self.timeout, retries=2)
            payload = normalize_payload(text)
            success = is_success_payload(payload)
            if self.conn:
                record_prism_api_call(self.conn, endpoint, success=success)
                if not success:
                    insert_prism_api_failure(
                        self.conn,
                        endpoint,
                        clean,
                        "api_error",
                        payload_code(payload),
                        payload_message(payload),
                        text[:2000],
                    )
                    recorded_failure = True
            if not success:
                raise HttpError("{0} returned {1}: {2}".format(endpoint, payload_code(payload), payload_message(payload)))
            return payload, final_url
        except Exception as exc:
            if self.conn and not recorded_failure:
                record_prism_api_call(self.conn, endpoint, success=False)
                insert_prism_api_failure(self.conn, endpoint, clean, "exception", "", str(exc), "")
            raise

    def list_research(self, start_date, end_date, page_no=1, num_of_rows=100, organ_id=""):
        params = {
            "organ_id": organ_id,
            "start_date": normalize_date_param(start_date),
            "end_date": normalize_date_param(end_date),
            "numOfRows": str(num_of_rows),
            "pageNo": str(page_no),
        }
        return self.call("getResearchList_v2", params)

    def detail(self, research_id):
        return self.call("getResearchDetail_v2", {"research_id": research_id})

    def meta(self, research_id):
        return self.call("pnnMetaData_v2", {"research_id": research_id})


def fetch_backend_detail(research_id):
    payload, headers, final_url = request_json_post(PRISM_BACKEND_INFO_URL, {"asmtId": research_id}, timeout=30, retries=1)
    return payload
