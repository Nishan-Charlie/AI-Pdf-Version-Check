"""
PDF Text Extraction
───────────────────
Reads text out of regulation PDFs with PyMuPDF, sorting blocks so that
two-column layouts — which every jurisdiction in the corpus uses somewhere —
come out in reading order rather than interleaved.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# PyMuPDF renamed its import from `fitz` to `pymupdf`; the old name still works
# but warns on every start. Prefer the new one and fall back for older installs.
try:
    import pymupdf as fitz
except ImportError:  # PyMuPDF < 1.24
    import fitz

# Blocks within this many points of each other vertically are treated as the
# same visual line, so columns sort left-to-right within a row band.
_ROW_BAND = 10


@dataclass
class ExtractedDocument:
    """Text pulled from a PDF, with the provenance the UI reports back."""

    text: str
    page_count: int
    filename: str

    def __len__(self) -> int:
        return len(self.text)


def _read(document: fitz.Document) -> str:
    parts: list[str] = []

    for page in document:
        # (x0, y0, x1, y1, text, block_no, block_type); type 0 is text.
        blocks = [b for b in page.get_text("blocks") if b[6] == 0]
        blocks.sort(key=lambda b: (round(b[1] / _ROW_BAND) * _ROW_BAND, b[0]))

        page_text = "\n".join(b[4].strip() for b in blocks if b[4].strip())
        if page_text:
            parts.append(page_text)

    return "\n\n".join(parts)


def extract_document(pdf_bytes: bytes, filename: str = "uploaded.pdf") -> ExtractedDocument:
    """
    Extract text from PDF bytes.

    Raises:
        RuntimeError: if the bytes are not a PDF PyMuPDF can open.
    """
    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise RuntimeError(f"Could not read '{filename}' as a PDF: {exc}") from exc

    try:
        return ExtractedDocument(
            text=_read(document),
            page_count=document.page_count,
            filename=filename,
        )
    finally:
        document.close()


def extract_text_from_pdf(file_path: str) -> str:
    """Extract text from a PDF on disk."""
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"PDF not found: {file_path}")

    try:
        document = fitz.open(file_path)
    except Exception as exc:
        raise RuntimeError(f"Could not open PDF '{file_path}': {exc}") from exc

    try:
        return _read(document)
    finally:
        document.close()


def extract_text_from_bytes(pdf_bytes: bytes, filename: str = "uploaded.pdf") -> str:
    """Extract text from PDF bytes held in memory."""
    return extract_document(pdf_bytes, filename).text
