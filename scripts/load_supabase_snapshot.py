import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


LOAD_ORDER = ("projects", "reports", "files", "kg_nodes", "kg_edges", "chunks")


def require_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError("{0} is not configured".format(name))
    return value


def admin_key():
    return os.environ.get("SUPABASE_SECRET_KEY", "").strip() or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()


def read_jsonl(path):
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def batches(items, batch_size):
    batch = []
    for item in items:
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def request_json(url, key, rows, retries=4):
    data = json.dumps(rows, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "apikey": key,
            "Authorization": "Bearer {0}".format(key),
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
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
            raise RuntimeError("HTTP {0}: {1}".format(exc.code, body)) from exc
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
            "apikey": key,
            "Authorization": "Bearer {0}".format(key),
            "Prefer": "count=exact",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        value = resp.headers.get("content-range", "")
    if "/" in value:
        return int(value.rsplit("/", 1)[1])
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=os.path.join("exports", "supabase"))
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()

    supabase_url = require_env("SUPABASE_URL")
    key = admin_key()
    if not key:
        raise RuntimeError("SUPABASE_SECRET_KEY or SUPABASE_SERVICE_ROLE_KEY is not configured")

    base = Path(args.dir)
    counts = {}
    rest_base = urllib.parse.urljoin(supabase_url.rstrip("/") + "/", "rest/v1/")
    for table in LOAD_ORDER:
        path = base / "{0}.jsonl".format(table)
        if not path.exists():
            continue
        total = 0
        endpoint = urllib.parse.urljoin(rest_base, table)
        for batch in batches(read_jsonl(path), max(1, args.batch_size)):
            request_json(endpoint, key, batch)
            total += len(batch)
            print("{0} upserted {1}".format(table, total), flush=True)
        counts[table] = total

    if args.verify:
        remote = {table: count_remote(supabase_url, key, table) for table in counts}
    else:
        remote = {}
    print(json.dumps({"loaded": counts, "remote": remote}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
