import json
import os
import shutil
import subprocess

from .pdf_extract import extract_pdf_pages


class ConversionError(RuntimeError):
    pass


def ensure_java_available():
    java = shutil.which("java")
    if not java:
        raise ConversionError("Java 11+ is required for OpenDataLoader PDF, but java was not found on PATH.")
    try:
        result = subprocess.run([java, "-version"], capture_output=True, text=True, timeout=10)
    except Exception as exc:
        raise ConversionError("Failed to run java -version: {0}".format(exc))
    output = (result.stderr or result.stdout or "").strip()
    if result.returncode != 0:
        raise ConversionError("java -version failed: {0}".format(output))
    return output


def find_generated_file(output_dir, input_path, extensions):
    stem = os.path.splitext(os.path.basename(input_path))[0]
    candidates = []
    for root, dirs, files in os.walk(output_dir):
        for name in files:
            lowered = name.lower()
            if not any(lowered.endswith(ext) for ext in extensions):
                continue
            score = 0
            if os.path.splitext(name)[0] == stem:
                score += 10
            if stem in name:
                score += 5
            candidates.append((score, os.path.join(root, name)))
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    return candidates[0][1]


def read_text_file(path):
    if not path or not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def read_json_file(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {"raw": f.read()}


def convert_pdf_opendataloader(input_path, output_dir):
    ensure_java_available()
    try:
        import opendataloader_pdf
    except ImportError as exc:
        raise ConversionError("opendataloader-pdf is not installed. Install govrag-portable[prism-pdf].") from exc

    os.makedirs(output_dir, exist_ok=True)
    try:
        opendataloader_pdf.convert(
            input_path=[input_path],
            output_dir=output_dir,
            format="markdown,json",
        )
    except TypeError:
        opendataloader_pdf.convert(input_path=input_path, output_dir=output_dir, format="markdown,json")
    except Exception as exc:
        raise ConversionError("OpenDataLoader PDF conversion failed: {0}".format(exc)) from exc

    md_path = find_generated_file(output_dir, input_path, (".md", ".markdown"))
    json_path = find_generated_file(output_dir, input_path, (".json",))
    text = read_text_file(md_path)
    metadata = read_json_file(json_path)
    if not text.strip():
        raise ConversionError("OpenDataLoader PDF produced no Markdown text.")
    metadata["_opendataloader"] = {"markdown_path": md_path, "json_path": json_path}
    return text, metadata


def convert_pdf_pymupdf_fallback(input_path):
    pages = extract_pdf_pages(input_path)
    lines = []
    for page in pages:
        if page.get("text"):
            lines.append("# Page {0}\n\n{1}".format(page.get("page"), page.get("text")))
    return "\n\n".join(lines).strip(), {"fallback": "pymupdf", "pages": len(pages)}


def convert_hwp_rhwp(input_path):
    try:
        import rhwp
    except ImportError as exc:
        raise ConversionError("rhwp-python is not installed. Install govrag-portable[prism-hwp].") from exc

    try:
        doc = rhwp.parse(input_path)
    except Exception as exc:
        raise ConversionError("rhwp failed to parse document: {0}".format(exc)) from exc

    def attr_value(name):
        value = getattr(rhwp, name, "")
        if callable(value):
            try:
                return value()
            except Exception:
                return ""
        return value

    metadata = {
        "converter": "rhwp",
        "rhwp_version": attr_value("version"),
        "rhwp_core_version": attr_value("rhwp_core_version"),
    }
    for attr in ("section_count", "paragraph_count", "page_count"):
        try:
            metadata[attr] = getattr(doc, attr)
        except Exception:
            pass

    try:
        ir = doc.to_ir()
        if hasattr(ir, "to_markdown"):
            text = ir.to_markdown()
        elif hasattr(doc, "to_markdown"):
            text = doc.to_markdown()
        else:
            text = doc.extract_text()
        if hasattr(doc, "to_ir_json"):
            metadata["ir_json"] = json.loads(doc.to_ir_json())
    except Exception:
        try:
            text = doc.extract_text()
        except Exception as exc:
            raise ConversionError("rhwp produced neither Markdown nor text: {0}".format(exc)) from exc

    if not (text or "").strip():
        raise ConversionError("rhwp produced no text.")
    return text, metadata


def extension_for_path(path):
    return os.path.splitext(path or "")[1].lower()


def convert_document(input_path, output_dir, allow_pymupdf_fallback=False):
    ext = extension_for_path(input_path)
    if ext == ".pdf":
        try:
            return convert_pdf_opendataloader(input_path, output_dir)
        except Exception:
            if allow_pymupdf_fallback:
                return convert_pdf_pymupdf_fallback(input_path)
            raise
    if ext in (".hwp", ".hwpx"):
        return convert_hwp_rhwp(input_path)
    raise ConversionError("Unsupported PRISM document format: {0}".format(ext or input_path))
