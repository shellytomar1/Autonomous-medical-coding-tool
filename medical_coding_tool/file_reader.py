from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def read_text_from_file(file_path: str, *, max_chars: Optional[int] = None) -> str:
    """
    Read unstructured clinical text from a .txt/.pdf input.
    """
    path = Path(file_path).expanduser().resolve()
    suffix = path.suffix.lower()

    if suffix in {".txt", ".text", ".md"}:
        # Using errors='ignore' makes the tool resilient to OCR artifacts / odd encodings.
        text = path.read_text(encoding="utf-8", errors="ignore")
    elif suffix == ".pdf":
        text = _read_pdf_text(path, max_chars=max_chars)
    else:
        raise ValueError(f"Unsupported file type: {suffix}. Use .txt or .pdf.")

    text = text.replace("\x00", " ")
    text = " ".join(text.split())  # normalize whitespace

    if max_chars is not None:
        text = text[:max_chars]
    return text


def _read_pdf_text(path: Path, *, max_chars: Optional[int] = None) -> str:
    # Prefer pdfplumber; fall back to PyPDF2.
    try:
        import pdfplumber  # type: ignore

        chunks: list[str] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if page_text:
                    chunks.append(page_text)
        text = "\n".join(chunks).strip()
    except Exception:
        # Fallback: PyPDF2 (less accurate for some PDFs but better than failing completely).
        from PyPDF2 import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        chunks = []
        for p in reader.pages:
            try:
                chunks.append(p.extract_text() or "")
            except Exception:
                chunks.append("")
        text = "\n".join(chunks).strip()

    if not text:
        # Leave a clear message for downstream steps.
        text = ""

    if max_chars is not None:
        text = text[:max_chars]
    return text

