import hashlib
import os


def extract_pdf_pages(path):
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for PDF parsing. Install govrag-portable[pdf].") from exc

    doc = fitz.open(path)
    try:
        pages = []
        for i, page in enumerate(doc, start=1):
            text = page.get_text("text") or ""
            pages.append({"page": i, "text": text.strip()})
        return pages
    finally:
        doc.close()


def pdf_document_id(attachment_id, page_num):
    return hashlib.sha256("{0}|page|{1}".format(attachment_id, page_num).encode("utf-8")).hexdigest()


def source_format_for_path(path):
    ext = os.path.splitext(path or "")[1].lower().lstrip(".")
    return ext or "file"
