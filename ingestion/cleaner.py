"""
Text Cleaning & Normalization Module
─────────────────────────────────────
Removes noise from extracted PDF text and standardizes characters
for consistent NLP processing.
"""

import re
import unicodedata


def clean_text(raw_text: str) -> str:
    """
    Full cleaning pipeline for raw PDF-extracted text.

    Steps:
        1. Unicode normalization (NFKD → NFC)
        2. Standardize special characters (smart quotes, dashes, etc.)
        3. Remove non-printable / control characters
        4. Strip common headers, footers, and page numbers
        5. Collapse excessive whitespace and blank lines

    Args:
        raw_text: The raw text extracted from a PDF.

    Returns:
        Cleaned, normalized text ready for clause parsing.
    """
    text = raw_text

    # 1. Unicode normalization
    text = unicodedata.normalize("NFKD", text)
    text = unicodedata.normalize("NFC", text)

    # 2. Standardize special characters
    text = _standardize_characters(text)

    # 3. Remove non-printable / control characters (keep newlines and tabs)
    text = re.sub(r"[^\S\n\t]", " ", text)  # normalize whitespace chars to space
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)

    # 4. Strip headers, footers, page numbers
    text = _strip_headers_footers(text)

    # 5. Collapse whitespace
    text = _collapse_whitespace(text)

    return text.strip()


def _standardize_characters(text: str) -> str:
    """Replace typographic characters with their plain-text equivalents."""
    replacements = {
        "\u2018": "'",   # Left single quotation mark
        "\u2019": "'",   # Right single quotation mark
        "\u201c": '"',   # Left double quotation mark
        "\u201d": '"',   # Right double quotation mark
        "\u2013": "-",   # En dash
        "\u2014": "-",   # Em dash
        "\u2026": "...", # Horizontal ellipsis
        "\u00a0": " ",   # Non-breaking space
        "\u200b": "",    # Zero-width space
        "\u200c": "",    # Zero-width non-joiner
        "\u200d": "",    # Zero-width joiner
        "\ufeff": "",    # BOM / zero-width no-break space
        "\u00ad": "",    # Soft hyphen
        "\u2022": "- ",  # Bullet point → dash
        "\u25cf": "- ",  # Black circle → dash
        "\u25cb": "- ",  # White circle → dash
        "\u25aa": "- ",  # Black small square → dash
        "\u00b7": "- ",  # Middle dot → dash
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _strip_headers_footers(text: str) -> str:
    """
    Remove common header/footer patterns found in Fire Safety documents.
    These include page numbers, document IDs, and repetitive header lines.
    """
    lines = text.split("\n")
    cleaned_lines = []

    for line in lines:
        stripped = line.strip()

        # Skip standalone page numbers: "Page 5", "- 12 -", "5 of 20", just a number
        if re.match(r"^[-—]?\s*\d+\s*[-—]?$", stripped):
            continue
        if re.match(r"^[Pp]age\s+\d+(\s+of\s+\d+)?$", stripped):
            continue
        if re.match(r"^\d+\s+of\s+\d+$", stripped, re.IGNORECASE):
            continue

        # Skip very short lines that look like headers/footers (< 5 chars, no alpha)
        if len(stripped) < 3 and not any(c.isalpha() for c in stripped):
            continue

        cleaned_lines.append(line)

    return "\n".join(cleaned_lines)


def _collapse_whitespace(text: str) -> str:
    """Collapse multiple blank lines and excessive spaces."""
    # Collapse multiple spaces (but not newlines) into single space
    text = re.sub(r"[^\S\n]+", " ", text)
    # Collapse 3+ consecutive newlines into 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip trailing whitespace on each line
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text
