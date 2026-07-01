import json
import os
import urllib.request

from .config import load_runtime_env


DEFAULT_MINIMAX_URL = "https://api.minimaxi.chat/v1/chat/completions"
DEFAULT_MINIMAX_MODEL = "MiniMax-Text-01"


def minimax_configured():
    load_runtime_env()
    return bool(os.environ.get("MINIMAX_API_KEY", "").strip())


def minimax_status():
    load_runtime_env()
    return {
        "configured": bool(os.environ.get("MINIMAX_API_KEY", "").strip()),
        "model": os.environ.get("MINIMAX_MODEL", DEFAULT_MINIMAX_MODEL),
        "api_url_configured": bool(os.environ.get("MINIMAX_API_URL", "").strip()),
        "timeout": int(os.environ.get("MINIMAX_TIMEOUT", "60")),
    }


def chat(messages, model=None, temperature=0.2, max_tokens=1200):
    load_runtime_env()
    api_key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("MINIMAX_API_KEY is not configured.")
    url = os.environ.get("MINIMAX_API_URL", DEFAULT_MINIMAX_URL).strip()
    payload = {
        "model": model or os.environ.get("MINIMAX_MODEL", DEFAULT_MINIMAX_MODEL),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": "Bearer {0}".format(api_key),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=int(os.environ.get("MINIMAX_TIMEOUT", "60"))) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    result = json.loads(raw)
    return extract_content(result)


def stream_chat(messages, model=None, temperature=0.2, max_tokens=1200):
    load_runtime_env()
    api_key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("MINIMAX_API_KEY is not configured.")
    url = os.environ.get("MINIMAX_API_URL", DEFAULT_MINIMAX_URL).strip()
    payload = {
        "model": model or os.environ.get("MINIMAX_MODEL", DEFAULT_MINIMAX_MODEL),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
        "reasoning_split": True,
        "stream_options": {"include_usage": True},
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": "Bearer {0}".format(api_key),
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=int(os.environ.get("MINIMAX_TIMEOUT", "60"))) as resp:
        for raw_line in resp:
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                line = line[5:].strip()
            if not line or line == "[DONE]":
                if line == "[DONE]":
                    break
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                yield {"type": "raw", "text": line}
                continue
            for event in stream_events_from_chunk(chunk):
                yield event
                if event.get("type") == "finish":
                    return


def stream_events_from_chunk(chunk):
    if not isinstance(chunk, dict):
        return
    usage = chunk.get("usage")
    choices = chunk.get("choices") or []
    if usage and not choices:
        yield {"type": "usage", "usage": usage}
        return
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta") or choice.get("message") or {}
        if not isinstance(delta, dict):
            continue
        reasoning = delta.get("reasoning_content")
        if reasoning:
            yield {"type": "reasoning_delta", "text": reasoning}
        details = delta.get("reasoning_details")
        if details:
            yield {"type": "reasoning_details", "details": details}
        content = delta.get("content") or choice.get("text")
        if content:
            yield {"type": "answer_delta", "text": content}
        finish_reason = choice.get("finish_reason")
        if finish_reason:
            yield {"type": "finish", "finish_reason": finish_reason}


def extract_content(result):
    if isinstance(result, dict):
        choices = result.get("choices")
        if choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict) and message.get("content"):
                    return message["content"]
                if first.get("text"):
                    return first["text"]
        for key in ("reply", "text", "content", "output"):
            value = result.get(key)
            if isinstance(value, str) and value:
                return value
    return json.dumps(result, ensure_ascii=False)
