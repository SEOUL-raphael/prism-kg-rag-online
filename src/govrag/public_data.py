import json
import os
import xml.etree.ElementTree as ET
from datetime import date

from .config import source_service_key
from .http_client import HttpError, request_json, request_text
from .normalizer import find_records, first_field, in_year, normalize_record, since_year


def clean_xml_tag(tag):
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    if ":" in tag:
        return tag.split(":", 1)[1]
    return tag


def xml_to_data(element):
    children = list(element)
    if not children:
        return element.text or ""
    groups = {}
    for child in children:
        groups.setdefault(clean_xml_tag(child.tag), []).append(xml_to_data(child))
    result = {}
    for key, values in groups.items():
        result[key] = values if len(values) > 1 else values[0]
    return result


def parse_payload(text, response_format):
    fmt = (response_format or "").lower()
    if fmt == "xml" or text.lstrip().startswith("<"):
        root = ET.fromstring(text)
        return {clean_xml_tag(root.tag): xml_to_data(root)}
    return json.loads(text)


def base_params(source, year, page, page_size):
    params = {}
    key = source_service_key(source)
    if key:
        params["serviceKey"] = key
    response_type_param = source.get("response_type_param")
    if response_type_param and source.get("response_type_value"):
        params[response_type_param] = source.get("response_type_value")
    page_param = source.get("page_param")
    size_param = source.get("size_param")
    if page_param:
        params[page_param] = page
    if size_param:
        params[size_param] = page_size

    date_query = source.get("date_query") or {}
    if date_query.get("year_param"):
        params[date_query["year_param"]] = year
    if date_query.get("begin_param"):
        params[date_query["begin_param"]] = "{0}0101".format(year)
    if date_query.get("end_param"):
        params[date_query["end_param"]] = "{0}1231".format(year)

    for key, value in (source.get("params") or {}).items():
        params[key] = value
    return params


def format_template_url(source, template, year, page, page_size, detail_key=""):
    key = source_service_key(source)
    start = (page - 1) * page_size + 1
    end = page * page_size
    if not template:
        raise ValueError("url template is not configured for source {0}".format(source.get("id")))
    return template.format(
        key=key,
        type=source.get("response_type_value") or "json",
        service=source.get("service_name", ""),
        start=start,
        end=end,
        page=page,
        page_size=page_size,
        year=year,
        detail_key=detail_key,
        bs_code=source.get("bs_code", ""),
        keyword=source.get("keyword", ""),
    )


def fetch_template_page(source, year, page, page_size):
    template = source.get("url_template")
    url = format_template_url(source, template, year, page, page_size)
    response_format = source.get("response_format")
    if not response_format:
        response_format = "xml" if "/xml/" in url.lower() else "json"
    text, headers, final_url = request_text(url, timeout=int(source.get("timeout", 30)))
    payload = parse_payload(text, response_format)
    return payload, final_url


def fetch_detail_record(source, raw_record, year, page, page_size):
    template = source.get("detail_url_template")
    if not template:
        return raw_record
    detail_key = first_field(raw_record, source.get("detail_key_fields", ["id", "number", "seq"]))
    if not detail_key:
        return raw_record
    url = format_template_url(source, template, year, page, page_size, detail_key=detail_key)
    response_format = source.get("detail_response_format") or source.get("response_format")
    if not response_format:
        response_format = "xml" if "/xml/" in url.lower() else "json"
    text, headers, final_url = request_text(url, timeout=int(source.get("timeout", 30)))
    payload = parse_payload(text, response_format)
    detail_records = find_records(payload, source.get("detail_items_path"))
    if not detail_records:
        return raw_record
    merged = dict(raw_record)
    merged.update(detail_records[0])
    return merged


def fetch_page(source, year, page, page_size):
    if source.get("url_template"):
        return fetch_template_page(source, year, page, page_size)
    url = source.get("base_url")
    if not url or url.startswith("TODO_"):
        raise ValueError("base_url is not configured for source {0}".format(source.get("id")))
    params = base_params(source, year, page, page_size)
    response_format = source.get("response_format")
    if not response_format:
        response_format = "xml" if (source.get("kind") or "").endswith("xml") else "json"
    text, headers, final_url = request_text(url, params=params, timeout=int(source.get("timeout", 30)))
    payload = parse_payload(text, response_format)
    return payload, final_url


def source_has_year_query(source):
    date_query = source.get("date_query") or {}
    if date_query.get("year_param") or date_query.get("begin_param") or date_query.get("end_param"):
        return True
    template = source.get("url_template") or ""
    return "{year}" in template


def query_years_for_source(source, year=None, from_year=None):
    if year:
        return [int(year)]
    if from_year and source_has_year_query(source):
        current_year = date.today().year
        return list(range(int(from_year), current_year + 1))
    return [int(from_year or source.get("year") or 2026)]


def iter_source_records(source, year=None, from_year=None, max_pages=None):
    page_size = int(source.get("page_size") or 100)
    max_pages = int(max_pages or source.get("max_pages") or 1)
    explicit_path = source.get("items_path")
    seen = set()
    for query_year in query_years_for_source(source, year=year, from_year=from_year):
        for page in range(1, max_pages + 1):
            payload, final_url = fetch_page(source, query_year, page, page_size)
            records = find_records(payload, explicit_path)
            if not records:
                break
            yielded = 0
            for raw in records:
                if source.get("detail_url_template"):
                    try:
                        raw = fetch_detail_record(source, raw, query_year, page, page_size)
                    except Exception:
                        pass
                normalized = normalize_record(source, raw)
                if normalized["date"]:
                    if year and not in_year(normalized["date"], year):
                        continue
                    if from_year and not since_year(normalized["date"], from_year):
                        continue
                if normalized["id"] in seen:
                    continue
                seen.add(normalized["id"])
                normalized["fetch_url"] = final_url
                yielded += 1
                yield normalized
            if yielded == 0 and page > 1:
                break


def enabled_sources(sources, include_disabled=False):
    for source in sources:
        if include_disabled or source.get("enabled"):
            yield source


def validate_source_for_harvest(source):
    if source.get("requires_review"):
        return "source requires endpoint review before harvest"
    if source.get("url_template"):
        if not source_service_key(source):
            return "service key is empty and no sample_key is configured"
        return ""
    if not source.get("base_url") or str(source.get("base_url")).startswith("TODO_"):
        return "base_url is not configured"
    env_name = source.get("service_key_env")
    if env_name and not os.environ.get(env_name) and not source.get("sample_key"):
        return "environment variable {0} is empty".format(env_name)
    return ""
