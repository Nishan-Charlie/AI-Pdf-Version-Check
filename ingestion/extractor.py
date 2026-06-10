"""
PDF Text Extraction Module
──────────────────────────
Uses PyMuPDF (fitz) to extract text from Fire Safety PDF documents,
preserving paragraph structure and handling multi-column layouts.
"""

import fitz  # PyMuPDF
import os


def extract_text_from_pdf(file_path: str) -> str:
    """
    Extract all text from a PDF file, page by page.

    Text blocks are sorted by their vertical then horizontal position
    to handle multi-column layouts correctly.

    Args:
        file_path: Absolute or relative path to the PDF file.

    Returns:
        The full extracted text as a single string.

    Raises:
        FileNotFoundError: If the PDF file does not exist.
        RuntimeError: If PyMuPDF fails to parse the document.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"PDF not found: {file_path}")

    try:
        doc = fitz.open(file_path)
    except Exception as e:
        raise RuntimeError(f"Failed to open PDF '{file_path}': {e}")

    full_text_parts: list[str] = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        # Extract text blocks: (x0, y0, x1, y1, "text", block_no, block_type)
        blocks = page.get_text("blocks")

        # Filter to text blocks only (block_type == 0) and sort by
        # vertical position (y0) first, then horizontal (x0) for columns.
        text_blocks = [b for b in blocks if b[6] == 0]  # type 0 = text
        text_blocks.sort(key=lambda b: (round(b[1] / 10) * 10, b[0]))

        page_text = "\n".join(block[4].strip() for block in text_blocks if block[4].strip())

        if page_text:
            full_text_parts.append(page_text)

    doc.close()
    return "\n\n".join(full_text_parts)


def extract_text_from_bytes(pdf_bytes: bytes, filename: str = "uploaded.pdf") -> str:
    """
    Extract text from in-memory PDF bytes (e.g., from Streamlit file uploader).

    Args:
        pdf_bytes: Raw bytes of the PDF file.
        filename: Display name for error messages.

    Returns:
        The full extracted text as a single string.
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise RuntimeError(f"Failed to parse PDF '{filename}': {e}")

    full_text_parts: list[str] = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        blocks = page.get_text("blocks")
        text_blocks = [b for b in blocks if b[6] == 0]
        text_blocks.sort(key=lambda b: (round(b[1] / 10) * 10, b[0]))

        page_text = "\n".join(block[4].strip() for block in text_blocks if block[4].strip())
        if page_text:
            full_text_parts.append(page_text)

    doc.close()
    return "\n\n".join(full_text_parts)
