import json
import os
import urllib.request


def post_json(url, payload, timeout=120):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "User-Agent": "govrag-portable/0.1"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def generate(prompt, model=None, base_url=None):
    base_url = (base_url or os.environ.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
    model = model or os.environ.get("OLLAMA_GENERATE_MODEL") or "qwen3:4b"
    payload = {"model": model, "prompt": prompt, "stream": False}
    data = post_json(base_url + "/api/generate", payload)
    return data.get("response", "")
