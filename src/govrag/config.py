import json
import os
from copy import deepcopy


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_env_file(path):
    if not path or not os.path.exists(path):
        return []
    loaded = []
    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
                loaded.append(key)
    return loaded


def runtime_env_candidates(env_path=None):
    candidates = []
    if env_path:
        candidates.append(env_path)
    candidates.extend(
        [
            os.path.join("configs", "runtime.local.env"),
            r"D:\aks_yoksa_pipeline\.env",
        ]
    )
    seen = set()
    unique = []
    for path in candidates:
        abs_path = os.path.abspath(path) if not os.path.isabs(path) else path
        key = abs_path.lower()
        if key not in seen:
            seen.add(key)
            unique.append(abs_path)
    return unique


def load_runtime_env(env_path=None):
    loaded = {}
    for path in runtime_env_candidates(env_path):
        keys = load_env_file(path)
        if keys:
            loaded[path] = keys
    return loaded


def env_presence(names):
    status = {}
    for name in names:
        status[name] = bool(os.environ.get(name, "").strip())
    return status


def merge_defaults(defaults, source):
    merged = deepcopy(defaults or {})
    merged.update(source)
    return merged


def expand_env(value):
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return os.environ.get(value[2:-1], "")
    return value


def load_sources(path):
    data = load_json(path)
    defaults = data.get("defaults", {})
    sources = []
    for source in data.get("sources", []):
        merged = merge_defaults(defaults, source)
        sources.append(merged)
    return sources


def source_service_key(source):
    env_name = source.get("service_key_env")
    if env_name and os.environ.get(env_name):
        return os.environ.get(env_name, "")
    return source.get("sample_key", "")


def project_path(path):
    if os.path.isabs(path):
        return path
    root = os.getcwd()
    return os.path.abspath(os.path.join(root, path))
