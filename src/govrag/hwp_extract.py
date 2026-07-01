import json
import os
import subprocess


def extract_with_external_command(path, command_template, timeout=120):
    if not command_template:
        raise RuntimeError("No HWP/HWPX extractor command is configured.")
    base = os.path.splitext(path)[0]
    out_json = base + ".parsed.json"
    out_md = base + ".parsed.md"
    command = [
        part.format(input=path, out_json=out_json, out_md=out_md)
        for part in command_template
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "external extractor failed")
    text = ""
    metadata = {}
    if os.path.exists(out_md):
        with open(out_md, "r", encoding="utf-8") as f:
            text = f.read()
    if os.path.exists(out_json):
        with open(out_json, "r", encoding="utf-8") as f:
            metadata = json.load(f)
    return text, metadata
