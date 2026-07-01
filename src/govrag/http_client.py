import json
import http.client
import time
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_USER_AGENT = "govrag-portable/0.1"


class HttpError(RuntimeError):
    pass


SENSITIVE_QUERY_KEYS = {"servicekey", "apikey", "api_key", "key", "authkey"}


def redact_url(url):
    try:
        parsed = urllib.parse.urlsplit(url)
        query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        redacted = []
        for key, value in query:
            if key.lower() in SENSITIVE_QUERY_KEYS:
                value = "***"
            redacted.append((key, value))
        return urllib.parse.urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                urllib.parse.urlencode(redacted, doseq=True),
                parsed.fragment,
            )
        )
    except Exception:
        return url


def build_url(url, params=None):
    params = params or {}
    clean = {}
    for key, value in params.items():
        if value is None or value == "":
            continue
        clean[key] = value
    if not clean:
        return url
    sep = "&" if "?" in url else "?"
    return url + sep + urllib.parse.urlencode(clean, doseq=True)


def request_bytes(url, params=None, headers=None, timeout=30, retries=2):
    full_url = build_url(url, params)
    req_headers = {"User-Agent": DEFAULT_USER_AGENT}
    if headers:
        req_headers.update(headers)
    last_error = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(full_url, headers=req_headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read(), dict(resp.headers), resp.geturl()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, http.client.IncompleteRead) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise HttpError("GET failed for {0}: {1}".format(redact_url(full_url), last_error))


def request_bytes_post(url, payload=None, headers=None, timeout=30, retries=2):
    req_headers = {"User-Agent": DEFAULT_USER_AGENT, "Content-Type": "application/json", "Accept": "*/*"}
    if headers:
        req_headers.update(headers)
    body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    last_error = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read(), dict(resp.headers), resp.geturl()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, http.client.IncompleteRead) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise HttpError("POST failed for {0}: {1}".format(redact_url(url), last_error))


def request_text(url, params=None, headers=None, timeout=30, retries=2, encoding=None):
    data, resp_headers, final_url = request_bytes(url, params, headers, timeout, retries)
    enc = encoding
    if not enc:
        content_type = resp_headers.get("Content-Type") or resp_headers.get("content-type") or ""
        if "charset=" in content_type:
            enc = content_type.split("charset=", 1)[1].split(";", 1)[0].strip()
    enc = enc or "utf-8"
    try:
        return data.decode(enc), resp_headers, final_url
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace"), resp_headers, final_url


def request_json(url, params=None, headers=None, timeout=30, retries=2):
    text, resp_headers, final_url = request_text(url, params, headers, timeout, retries)
    return json.loads(text), resp_headers, final_url


def request_json_post(url, payload=None, headers=None, timeout=30, retries=2):
    req_headers = {"User-Agent": DEFAULT_USER_AGENT, "Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    body = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    last_error = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=body, headers=req_headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                text = raw.decode("utf-8", errors="replace")
                return json.loads(text), dict(resp.headers), resp.geturl()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, http.client.IncompleteRead, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise HttpError("POST failed for {0}: {1}".format(redact_url(url), last_error))
