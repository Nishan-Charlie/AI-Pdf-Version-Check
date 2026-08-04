"""
Ingestion Pipeline
──────────────────
One call from uploaded bytes to stored-ready clauses: extract, clean, work out
which regulator wrote it, then parse with that regulator's numbering grammar.

The jurisdiction can be stated by the uploader or left to the detector. When
it is stated, that choice wins — a user who says this is a Scottish handbook
knows something the text may not say on page one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from config import (
    AUTO_JURISDICTION,
    DEFAULT_JURISDICTION,
    JURISDICTIONS,
    parser_profile_for,
)
from ingestion.cleaner import clean_text
from ingestion.clause_parser import parse_clauses
from ingestion.extractor import extract_document
from ingestion.profiles import detect_profile, get_profile

# Reverse of config.JURISDICTIONS: which jurisdiction a detected grammar implies.
_JURISDICTION_BY_PROFILE = {
    j["parser_profile"]: j["code"]
    for j in JURISDICTIONS
    if j["parser_profile"] != "generic"
}


@dataclass
class IngestResult:
    """Everything the ingest endpoint needs to report and store."""

    clauses: list[dict]
    country_code: str
    country_detected: bool
    profile_name: str
    profile_label: str
    confidence: float
    page_count: int
    characters: int
    text: str

    def as_dict(self) -> dict:
        """Report shape — the parsed text itself is far too big to return."""
        return {
            "clause_count": len(self.clauses),
            "country_code": self.country_code,
            "country_detected": self.country_detected,
            "profile_name": self.profile_name,
            "profile_label": self.profile_label,
            "confidence": self.confidence,
            "page_count": self.page_count,
            "characters": self.characters,
        }


def ingest_pdf(
    pdf_bytes: bytes,
    filename: str = "uploaded.pdf",
    country_code: str = AUTO_JURISDICTION,
) -> IngestResult:
    """
    Read an uploaded PDF into clause records.

    Args:
        pdf_bytes: Raw PDF bytes.
        filename: Original name, used in error messages.
        country_code: A jurisdiction code, or "AUTO" to detect it.

    Returns:
        The parsed clauses plus how they were derived.

    Raises:
        RuntimeError: if the file cannot be read as a PDF.
        ValueError: if no readable text came out of it.
    """
    extracted = extract_document(pdf_bytes, filename)
    cleaned = clean_text(extracted.text)

    if not cleaned.strip():
        raise ValueError(
            f"No text could be read from '{filename}'. Scanned PDFs need OCR first."
        )

    return ingest_text(
        cleaned,
        country_code=country_code,
        page_count=extracted.page_count,
        pre_cleaned=True,
    )


def ingest_text(
    text: str,
    country_code: str = AUTO_JURISDICTION,
    page_count: int = 0,
    pre_cleaned: bool = False,
) -> IngestResult:
    """
    Parse regulation text that is already out of its PDF.

    Used by `ingest_pdf`, and directly by the corpus tooling, which extracts
    text ahead of time.
    """
    cleaned = text if pre_cleaned else clean_text(text)

    requested = (country_code or AUTO_JURISDICTION).upper()
    detected_profile, confidence = detect_profile(cleaned)

    if requested == AUTO_JURISDICTION:
        profile = detected_profile
        resolved_country = _JURISDICTION_BY_PROFILE.get(
            profile.name, DEFAULT_JURISDICTION
        )
        country_detected = True
    else:
        profile = get_profile(parser_profile_for(requested))
        resolved_country = requested
        country_detected = False
        # The detector still ran, and its confidence is reported either way so
        # a mislabelled upload is visible rather than silent.
        confidence = confidence if detected_profile.name == profile.name else 0.0

    clauses = parse_clauses(cleaned, profile)

    return IngestResult(
        clauses=clauses,
        country_code=resolved_country,
        country_detected=country_detected,
        profile_name=profile.name,
        profile_label=profile.label,
        confidence=confidence,
        page_count=page_count,
        characters=len(cleaned),
        text=cleaned,
    )


def profile_summary(clauses: list[dict]) -> dict:
    """Quick shape of a parse: how deep it went and how big the clauses are."""
    if not clauses:
        return {"clauses": 0, "sections": 0, "median_chars": 0}

    lengths = sorted(len(c["content"]) for c in clauses)
    sections = {c.get("section") for c in clauses if c.get("section")}

    return {
        "clauses": len(clauses),
        "sections": len(sections),
        "median_chars": lengths[len(lengths) // 2],
    }


def detected_country(text: str) -> Optional[str]:
    """Jurisdiction implied by a document's own text, if the grammar is known."""
    profile, _ = detect_profile(text)
    return _JURISDICTION_BY_PROFILE.get(profile.name)
