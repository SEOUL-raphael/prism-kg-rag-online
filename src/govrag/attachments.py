import html
import hashlib
import os
import re
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlparse

from .http_client import HttpError, request_bytes, request_text


ATTACHMENT_EXTENSIONS = (".pdf", ".hwp", ".hwpx")


class LinkExtractor(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        href = attrs.get("href")
        if href:
            self.links.append(href)


def looks_like_attachment(url):
    parsed = urlparse(url)
    path = parsed.path.lower()
    if path.endswith(ATTACHMENT_EXTENSIONS):
        return True
    lowered = url.lower()
    return (
        any(ext in lowered for ext in ATTACHMENT_EXTENSIONS)
        or "download" in lowered
        or "filedown" in lowered
        or "atchfileid" in lowered
    )


def find_attachment_links(html, base_url):
    parser = LinkExtractor()
    parser.feed(html or "")
    links = []
    seen = set()
    for href in parser.links:
        candidates = []
        href = html_unescape(href)
        if href.lower().startswith("javascript:"):
            candidates.extend(re.findall(r"https?://[^'\"),]+", href))
        else:
            candidates.append(urljoin(base_url, href))
        for absolute in candidates:
            parsed = urlparse(absolute)
            if parsed.scheme not in ("http", "https"):
                continue
            if absolute in seen:
                continue
            if looks_like_attachment(absolute):
                links.append(absolute)
                seen.add(absolute)
    return links


def html_unescape(value):
    return html.unescape(value or "")


def filename_from_content_disposition(content_disposition):
    if not content_disposition:
        return ""
    match = re.search(r"filename\*=UTF-8''([^;]+)", content_disposition, flags=re.I)
    if match:
        return unquote(match.group(1).strip().strip('"'))
    match = re.search(r'filename="?([^";]+)"?', content_disposition, flags=re.I)
    if match:
        return unquote(match.group(1).strip().strip('"'))
    return ""


def guess_extension(url, content_type, content_disposition=""):
    filename = filename_from_content_disposition(content_disposition)
    lowered = (content_type or "").lower() + " " + url.lower() + " " + filename.lower()
    if "pdf" in lowered:
        return ".pdf", "application/pdf"
    if "hwpx" in lowered:
        return ".hwpx", "application/hwpx"
    if "hwp" in lowered:
        return ".hwp", "application/hwp"
    return ".bin", content_type or "application/octet-stream"


def safe_part(value):
    value = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", value or "")
    return value[:80] or "unknown"


def collect_record_attachment_urls(record, follow_detail=True):
    urls = []
    seen = set()
    for url in record.get("attachments", []):
        if url and url not in seen:
            urls.append(url)
            seen.add(url)
    detail_url = record.get("detail_url")
    if follow_detail and detail_url:
        try:
            html, headers, final_url = request_text(detail_url, timeout=20, retries=1)
            for url in find_attachment_links(html, final_url):
                if url not in seen:
                    urls.append(url)
                    seen.add(url)
        except Exception:
            pass
    return urls


def download_attachment(record, url, data_dir):
    raw, headers, final_url = request_bytes(url, timeout=60, retries=2)
    sha = hashlib.sha256(raw).hexdigest()
    ext, media_type = guess_extension(
        final_url,
        headers.get("Content-Type") or headers.get("content-type"),
        headers.get("Content-Disposition") or headers.get("content-disposition"),
    )
    org = safe_part(record.get("org"))
    year = (record.get("date") or "unknown")[:4] or "unknown"
    out_dir = os.path.join(data_dir, "raw", "attachments", org, year)
    os.makedirs(out_dir, exist_ok=True)
    filename = "{0}{1}".format(sha[:24], ext)
    path = os.path.join(out_dir, filename)
    if not os.path.exists(path):
        with open(path, "wb") as f:
            f.write(raw)
    attachment_id = hashlib.sha256((record["id"] + "|" + final_url).encode("utf-8")).hexdigest()
    return {
        "id": attachment_id,
        "record_id": record["id"],
        "url": final_url,
        "local_path": path,
        "media_type": media_type,
        "sha256": sha,
        "size": len(raw),
        "status": "downloaded",
        "error": "",
    }


def failed_attachment(record, url, error):
    attachment_id = hashlib.sha256((record["id"] + "|" + url).encode("utf-8")).hexdigest()
    return {
        "id": attachment_id,
        "record_id": record["id"],
        "url": url,
        "local_path": "",
        "media_type": "",
        "sha256": "",
        "size": 0,
        "status": "failed",
        "error": str(error)[:1000],
    }
