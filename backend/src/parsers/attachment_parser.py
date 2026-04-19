"""Extract text from PDF and DOCX attachments."""

import os
import logging
import tempfile
import requests

logger = logging.getLogger(__name__)


def extract_text_from_pdf(file_path):
    """Extract text from a PDF file."""
    try:
        from PyPDF2 import PdfReader
        reader = PdfReader(file_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() or ""
        return text.strip()
    except Exception as e:
        logger.error(f"PDF extraction failed for {file_path}: {e}")
        return ""


def extract_text_from_docx(file_path):
    """Extract text from a DOCX file."""
    try:
        from docx import Document
        doc = Document(file_path)
        return "\n".join(p.text for p in doc.paragraphs).strip()
    except Exception as e:
        logger.error(f"DOCX extraction failed for {file_path}: {e}")
        return ""


def download_and_extract(url):
    """Download an attachment URL and extract text."""
    try:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to download {url}: {e}")
        return ""

    suffix = ".pdf" if "pdf" in url.lower() else ".docx" if "doc" in url.lower() else ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(resp.content)
        tmp_path = f.name

    try:
        if suffix == ".pdf":
            return extract_text_from_pdf(tmp_path)
        elif suffix == ".docx":
            return extract_text_from_docx(tmp_path)
        else:
            return ""
    finally:
        os.unlink(tmp_path)


def extract_attachment_texts(attachments):
    """Given a list of URLs, return combined extracted text."""
    texts = []
    for url in attachments[:5]:  # Limit to 5 attachments
        text = download_and_extract(url)
        if text:
            texts.append(text)
    return "\n\n---\n\n".join(texts)
