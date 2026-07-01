import hashlib
import html
import json
import re
from datetime import datetime


DATE_PATTERNS = [
    re.compile(r"(?P<y>20\d{2})[-./](?P<m>\d{1,2})[-./](?P<d>\d{1,2})"),
    re.compile(r"(?P<y>20\d{2})(?P<m>\d{2})(?P<d>\d{2})"),
]


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def text_value(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def html_to_text(value):
    value = html.unescape(text_value(value))
    value = re.sub(r"(?is)<(script|style).*?</\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            for found in walk_dicts(child):
                yield found
    elif isinstance(value, list):
        for child in value:
            for found in walk_dicts(child):
                yield found


def find_records(payload, explicit_path=None):
    if explicit_path:
        current = payload
        for part in explicit_path:
            if isinstance(current, dict):
                current = current.get(part)
            else:
                current = None
                break
        if isinstance(current, list):
            return [item for item in current if isinstance(item, dict)]
        if isinstance(current, dict):
            return [current]

    best = []
    best_score = -1
    for node in walk_dicts(payload):
        for value in node.values():
            if isinstance(value, list) and value and all(isinstance(x, dict) for x in value):
                score = len(value) * 5
                sample_keys = set()
                for item in value[:5]:
                    sample_keys.update(str(k).lower() for k in item.keys())
                for key in sample_keys:
                    if key in ("title", "subject", "sj", "content", "contents", "date", "regdate"):
                        score += 10
                if score > best_score:
                    best = value
                    best_score = score
    if best:
        return best
    if isinstance(payload, dict):
        return [payload]
    return []


def first_field(record, candidates):
    lower_map = {str(k).lower(): k for k in record.keys()}
    for name in candidates or []:
        if name in record:
            value = text_value(record.get(name))
            if value:
                return value
        key = lower_map.get(str(name).lower())
        if key is not None:
            value = text_value(record.get(key))
            if value:
                return value
    return ""


def attachment_values(record, candidates):
    values = []
    for name in candidates or []:
        if name in record:
            values.extend(as_list(record.get(name)))
    lower_candidates = {str(x).lower() for x in candidates or []}
    for key, value in record.items():
        key_l = str(key).lower()
        if key_l in lower_candidates or "file" in key_l or "attach" in key_l or "down" in key_l:
            values.extend(as_list(value))
    result = []
    seen = set()
    for value in values:
        text = text_value(value)
        if not text or text in seen:
            continue
        result.append(text)
        seen.add(text)
    return result


def parse_date(value):
    value = text_value(value)
    if not value:
        return ""
    for pattern in DATE_PATTERNS:
        match = pattern.search(value)
        if not match:
            continue
        y = int(match.group("y"))
        m = int(match.group("m"))
        d = int(match.group("d"))
        try:
            return datetime(y, m, d).strftime("%Y-%m-%d")
        except ValueError:
            return ""
    return ""


def in_year(date_text, year):
    if not year:
        return True
    parsed = parse_date(date_text)
    return parsed.startswith(str(year) + "-")


def since_year(date_text, from_year):
    if not from_year:
        return True
    parsed = parse_date(date_text)
    if not parsed:
        return False
    return parsed >= "{0}-01-01".format(int(from_year))


def stable_id(source_id, title, date, detail_url, raw_record):
    basis = "|".join(
        [
            text_value(source_id),
            text_value(title),
            text_value(date),
            text_value(detail_url),
            json.dumps(raw_record, ensure_ascii=False, sort_keys=True)[:2000],
        ]
    )
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def normalize_record(source, raw_record):
    mapping = source.get("mapping", {})
    title = first_field(raw_record, mapping.get("title", []))
    date = parse_date(first_field(raw_record, mapping.get("date", [])))
    body = html_to_text(first_field(raw_record, mapping.get("body", [])))
    department = first_field(raw_record, mapping.get("department", []))
    detail_url = first_field(raw_record, mapping.get("detail_url", []))
    attachments = attachment_values(raw_record, mapping.get("attachments", []))
    rec_id = stable_id(source.get("id", ""), title, date, detail_url, raw_record)
    return {
        "id": rec_id,
        "source_id": source.get("id", ""),
        "org": source.get("org", ""),
        "region": source.get("region", ""),
        "title": title,
        "date": date,
        "department": department,
        "body": body,
        "detail_url": detail_url,
        "attachments": attachments,
        "license": source.get("license", ""),
        "portal_url": source.get("portal_url", ""),
        "raw": raw_record,
    }
