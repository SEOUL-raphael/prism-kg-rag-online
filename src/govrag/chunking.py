import re


def normalize_space(text):
    return re.sub(r"\s+", " ", text or "").strip()


def chunk_text(text, max_chars=1200, overlap=160):
    text = normalize_space(text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        cut = text.rfind(". ", start, end)
        if cut < start + int(max_chars * 0.5):
            cut = text.rfind(" ", start, end)
        if cut < start + int(max_chars * 0.5):
            cut = end
        chunk = text[start:cut].strip()
        if chunk:
            chunks.append(chunk)
        if cut >= len(text):
            break
        start = max(0, cut - overlap)
    return chunks
