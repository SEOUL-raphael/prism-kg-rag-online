import argparse
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


LOAD_ORDER = ("projects", "reports", "files", "kg_nodes", "kg_edges", "chunks")
TABLE_COLUMNS = {
    "projects": {
        "research_id",
        "research_name",
        "organ_name",
        "researcher_name",
        "charge_person_department",
        "charge_person_phone_no",
        "biz_name",
        "research_start_date",
        "research_end_date",
        "brm_biz_name",
        "research_outline",
        "issued_year",
        "updated_at",
    },
    "reports": {"id", "research_id", "title", "table_contents", "summary", "keyword", "issued_year", "updated_at"},
    "files": {
        "id",
        "research_id",
        "source_section",
        "file_type",
        "file_name",
        "file_size",
        "media_type",
        "sha256",
        "size",
        "status",
        "markdown_chars",
        "updated_at",
    },
    "kg_nodes": {"id", "kind", "label", "data", "updated_at"},
    "kg_edges": {"id", "from_id", "to_id", "kind", "data", "updated_at"},
    "chunks": {
        "id",
        "document_id",
        "chunk_index",
        "research_id",
        "file_id",
        "title",
        "organ_name",
        "file_name",
        "text",
        "metadata",
        "updated_at",
    },
}


class RequestFailure(RuntimeError):
    def __init__(self, code, body):
        super().__init__("HTTP {0}: {1}".format(code, body))
        self.code = code
        self.body = body


def require_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError("{0} is not configured".format(name))
    return value


def admin_keys():
    keys = []
    for name in ("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
        value = os.environ.get(name, "").strip()
        if value:
            keys.append((name, value))
    jwt_secret = os.environ.get("SUPABASE_JWT_SECRET", "").strip()
    if jwt_secret:
        keys.append(("SUPABASE_JWT_SECRET/service_role", mint_legacy_jwt(jwt_secret, "service_role")))
    return keys


def api_key_for_request(admin_key):
    return (
        os.environ.get("SUPABASE_PUBLISHABLE_KEY", "").strip()
        or os.environ.get("VITE_SUPABASE_PUBLISHABLE_KEY", "").strip()
        or os.environ.get("SUPABASE_ANON_KEY", "").strip()
        or admin_key
    )


def b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def mint_legacy_jwt(secret, role, ttl_seconds=3600):
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": "supabase",
        "role": role,
        "iat": now,
        "exp": now + int(ttl_seconds),
    }
    ref = os.environ.get("SUPABASE_PROJECT_REF", "").strip()
    if not ref:
        url = os.environ.get("SUPABASE_URL", "").strip()
        if "://" in url:
            ref = url.split("://", 1)[1].split(".", 1)[0]
    if ref:
        payload["ref"] = ref
    signing_input = "{0}.{1}".format(
        b64url(json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")),
        b64url(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")),
    ).encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return signing_input.decode("ascii") + "." + b64url(signature)


def read_jsonl(path):
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def skip_items(items, count):
    remaining = max(0, int(count or 0))
    for item in items:
        if remaining > 0:
            remaining -= 1
            continue
        yield item


def batches(items, batch_size):
    batch = []
    for item in items:
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def normalize_row(table, row):
    allowed = TABLE_COLUMNS.get(table)
    if not allowed:
        return row
    return {key: value for key, value in row.items() if key in allowed}


def request_json(url, key, rows, retries=4, upsert=True):
    data = json.dumps(rows, ensure_ascii=False).encode("utf-8")
    prefer = "return=minimal"
    if upsert:
        prefer = "resolution=merge-duplicates," + prefer
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "apikey": api_key_for_request(key),
            "Authorization": "Bearer {0}".format(key),
            "Content-Type": "application/json",
            "Prefer": prefer,
        },
    )
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                resp.read()
                return
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:1000]
            if exc.code in (429, 500, 502, 503, 504) and attempt + 1 < retries:
                time.sleep(2 ** attempt)
                continue
            raise RequestFailure(exc.code, body) from exc
        except urllib.error.URLError:
            if attempt + 1 < retries:
                time.sleep(2 ** attempt)
                continue
            raise


def count_remote(supabase_url, key, table):
    endpoint = urllib.parse.urljoin(supabase_url.rstrip("/") + "/", "rest/v1/{0}?select=count".format(table))
    req = urllib.request.Request(
        endpoint,
        method="HEAD",
        headers={
            "apikey": api_key_for_request(key),
            "Authorization": "Bearer {0}".format(key),
            "Prefer": "count=exact",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            value = resp.headers.get("content-range", "")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1000]
        raise RequestFailure(exc.code, body) from exc
    if "/" in value:
        return int(value.rsplit("/", 1)[1])
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=os.path.join("exports", "supabase"))
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--tables", nargs="*", choices=LOAD_ORDER, default=list(LOAD_ORDER))
    parser.add_argument("--skip-rows", type=int, default=0)
    parser.add_argument("--insert-only", action="store_true")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    supabase_url = require_env("SUPABASE_URL")
    keys = admin_keys()
    if not keys:
        raise RuntimeError("SUPABASE_SECRET_KEY, SUPABASE_SERVICE_ROLE_KEY, or SUPABASE_JWT_SECRET is not configured")
    key_index = 0

    def with_admin_key(func):
        nonlocal key_index
        while True:
            try:
                return func(keys[key_index][1])
            except RequestFailure as exc:
                if exc.code in (401, 403) and key_index + 1 < len(keys):
                    key_index += 1
                    print("primary admin key rejected; retrying with fallback key", flush=True)
                    continue
                raise

    base = Path(args.dir)
    counts = {}
    rest_base = urllib.parse.urljoin(supabase_url.rstrip("/") + "/", "rest/v1/")
    for table in args.tables:
        path = base / "{0}.jsonl".format(table)
        if not path.exists():
            continue
        total = 0
        endpoint = urllib.parse.urljoin(rest_base, table)
        rows = (normalize_row(table, row) for row in read_jsonl(path))
        if len(args.tables) == 1 and args.skip_rows:
            rows = skip_items(rows, args.skip_rows)
        for batch in batches(rows, max(1, args.batch_size)):
            with_admin_key(lambda key: request_json(endpoint, key, batch, upsert=not args.insert_only))
            total += len(batch)
            print("{0} upserted {1}".format(table, total), flush=True)
        counts[table] = total

    if args.verify:
        remote = {table: with_admin_key(lambda key, table=table: count_remote(supabase_url, key, table)) for table in counts}
    else:
        remote = {}
    print(json.dumps({"loaded": counts, "remote": remote}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
