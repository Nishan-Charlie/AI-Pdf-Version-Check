"""
Reference Corpus Registry
─────────────────────────
The official fire safety standards this project validates against, with the
publisher's own download location for each one.

Access levels
    open      — published free by the regulator; `fetch.py` downloads it.
    licensed  — sold by the publisher under copyright. The URL is the purchase
                page, not a file. Nothing is downloaded; drop your own licensed
                copy into corpus/raw/ under `filename` and the checklist picks
                it up.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from config import CORPUS_RAW_DIR


@dataclass(frozen=True)
class CorpusEntry:
    """One document in the reference collection."""

    key: str
    title: str
    jurisdiction: str          # jurisdiction code from config.JURISDICTIONS
    publisher: str
    edition: str
    url: str
    filename: str
    access: str = "open"       # "open" | "licensed"
    kind: str = "base"         # "base" | "amendment" | "circular"
    parent: Optional[str] = None   # key of the base document an amendment revises
    notes: str = ""

    @property
    def path(self) -> str:
        return os.path.join(CORPUS_RAW_DIR, self.filename)

    @property
    def present(self) -> bool:
        return os.path.isfile(self.path) and os.path.getsize(self.path) > 0

    @property
    def size_bytes(self) -> int:
        return os.path.getsize(self.path) if self.present else 0


_GOVUK = "https://assets.publishing.service.gov.uk/media"
_GOVSCOT = (
    "https://www.gov.scot/binaries/content/documents/govscot/publications/"
    "advice-and-guidance/2022/06"
)


ENTRIES: list[CorpusEntry] = [
    # ── England & Wales — Approved Document B ────────────────────────
    CorpusEntry(
        key="adb-2019-v1",
        title="Approved Document B (fire safety) — Volume 1: Dwellings",
        jurisdiction="EW",
        publisher="MHCLG",
        edition="2019 edition (as first published)",
        url=f"{_GOVUK}/677fa35a99c93b7286a3982b/Approved_Document_B__fire_safety__volume_1_-_Dwellings__2019_edition.pdf",
        filename="EW_ADB_2019_vol1_dwellings.pdf",
        notes="Baseline 2019 text, before any amendment booklet was folded in.",
    ),
    CorpusEntry(
        key="adb-2022-v1",
        title="Approved Document B — Volume 1: Dwellings (incl. 2020 + 2022 amendments)",
        jurisdiction="EW",
        publisher="MHCLG",
        edition="2019 edition incorporating 2020 and 2022 amendments",
        url=f"{_GOVUK}/67d02386f5aaff610c9f5f06/Approved_Document_B__fire_safety__volume_1_-_Dwellings__2019_edition_incorporating_2020_and_2022_amendments.pdf",
        filename="EW_ADB_2022_vol1_dwellings.pdf",
    ),
    CorpusEntry(
        key="adb-2022-v2",
        title="Approved Document B — Volume 2: Buildings other than dwellings (incl. 2020 + 2022 amendments)",
        jurisdiction="EW",
        publisher="MHCLG",
        edition="2019 edition incorporating 2020 and 2022 amendments",
        url=f"{_GOVUK}/67d02361d5ec5ed9e09f5f07/Approved_Document_B__fire_safety__volume_2_-_Buildings_other_than_dwellings__2019_edition_incorporating_2020_and_2022_amendments.pdf",
        filename="EW_ADB_2022_vol2_other.pdf",
    ),
    CorpusEntry(
        key="adb-2025-v1",
        title="Approved Document B — Volume 1: Dwellings (collated to 2029)",
        jurisdiction="EW",
        publisher="MHCLG",
        edition="2019 edition incl. 2020, 2022, 2025 amendments, collated with 2026 and 2029",
        url=f"{_GOVUK}/67d2bb074702aacd2251cb94/Approved_Document_B_volume_1_Dwellings_2019_edition_incorporating_2020_2022_and_2025_amendments_collated_with_2026_and_2029_amendments.pdf",
        filename="EW_ADB_2025_vol1_dwellings_collated.pdf",
        notes="Current published consolidation — the natural Version 2 against adb-2019-v1.",
    ),
    CorpusEntry(
        key="adb-2025-v2",
        title="Approved Document B — Volume 2: Buildings other than dwellings (collated to 2029)",
        jurisdiction="EW",
        publisher="MHCLG",
        edition="2019 edition incl. 2020, 2022, 2025 amendments, collated with 2026 and 2029",
        url=f"{_GOVUK}/67d17064a005e6f9841a1d50/Approved_Document_B_volume_2_Buildings_other_than_Dwellings_2019_edition_incorporating_2020_2022_and_2025_amendments_collated_with_2026_and_2029_amendments.pdf",
        filename="EW_ADB_2025_vol2_other_collated.pdf",
    ),
    # ── England & Wales — amendment booklets ─────────────────────────
    CorpusEntry(
        key="adb-amd-2020",
        title="May 2020 amendments to Approved Document B",
        jurisdiction="EW",
        publisher="MHCLG",
        edition="May 2020",
        url=f"{_GOVUK}/5ec7f1c086650c76ab17fc0c/AD_B_2019_edition__May2020_amendments.pdf",
        filename="EW_ADB_amendment_2020_05.pdf",
        kind="amendment",
        parent="adb-2019-v1",
    ),
    CorpusEntry(
        key="adb-amd-2022",
        title="June 2022 amendments to Approved Document B",
        jurisdiction="EW",
        publisher="MHCLG",
        edition="June 2022",
        url=f"{_GOVUK}/62964fac8fa8f5039927d15b/ADB_amendment_booklet_June_2022.pdf",
        filename="EW_ADB_amendment_2022_06.pdf",
        kind="amendment",
        parent="adb-2019-v1",
    ),
    CorpusEntry(
        key="adb-amd-2024",
        title="March 2024 amendments to Approved Document B (superseded)",
        jurisdiction="EW",
        publisher="MHCLG",
        edition="March 2024",
        url=f"{_GOVUK}/66054cc0f9ab41001aeea490/AD_B_amendment_booklet.pdf",
        filename="EW_ADB_amendment_2024_03.pdf",
        kind="amendment",
        parent="adb-2019-v1",
        notes="No longer current; retained to trace the amendment trail.",
    ),
    CorpusEntry(
        key="adb-amd-2025",
        title="2025 amendments to Approved Document B",
        jurisdiction="EW",
        publisher="MHCLG",
        edition="2025",
        url=f"{_GOVUK}/67c1ac3d16dc9038974dbcfe/2025_Amendments_to_Approved_Document_B_volume_1_and_volume_2.pdf",
        filename="EW_ADB_amendment_2025.pdf",
        kind="amendment",
        parent="adb-2019-v1",
    ),
    CorpusEntry(
        key="adb-amd-2026",
        title="2026 amendments to Approved Document B",
        jurisdiction="EW",
        publisher="MHCLG",
        edition="2026 (future-dated)",
        url=f"{_GOVUK}/66d57a94d107658faec7e448/AD_B_2026_amendments.pdf",
        filename="EW_ADB_amendment_2026.pdf",
        kind="amendment",
        parent="adb-2019-v1",
    ),
    CorpusEntry(
        key="adb-amd-2029",
        title="2029 amendments to Approved Document B",
        jurisdiction="EW",
        publisher="MHCLG",
        edition="2029 (future-dated)",
        url=f"{_GOVUK}/66d57aaabdecebe01a18341b/AD_B_2029_amendments.pdf",
        filename="EW_ADB_amendment_2029.pdf",
        kind="amendment",
        parent="adb-2019-v1",
    ),
    CorpusEntry(
        key="adb-circ-2025",
        title="Circular 01/2025 — Approved Document B corrections",
        jurisdiction="EW",
        publisher="MHCLG",
        edition="February 2025",
        url=f"{_GOVUK}/67c1e22716dc9038974dbd24/250226_Circular_012025_Approved_Document_B_corrections.pdf",
        filename="EW_ADB_circular_2025_01.pdf",
        kind="circular",
        parent="adb-2019-v1",
    ),
    # ── Northern Ireland ─────────────────────────────────────────────
    CorpusEntry(
        key="ni-tbe-2012",
        title="Technical Booklet E — Fire safety",
        jurisdiction="NI",
        publisher="Department of Finance (NI)",
        edition="October 2012",
        url="https://www.finance-ni.gov.uk/sites/default/files/publications/dfp/Technical-booklet-E-Fire-Safety-October-2012_0.pdf",
        filename="NI_TBE_2012_fire_safety.pdf",
    ),
    CorpusEntry(
        key="ni-tbe-2012-mirror",
        title="Technical Booklet E — Fire safety (Building Control NI copy)",
        jurisdiction="NI",
        publisher="Building Control NI",
        edition="October 2012",
        url="https://www.buildingcontrol-ni.com/assets/pdf/TechnicalBookletE2012.pdf",
        filename="NI_TBE_2012_fire_safety_mirror.pdf",
        notes="Mirror of the same booklet; useful when finance-ni.gov.uk is unreachable.",
    ),
    # ── Republic of Ireland ──────────────────────────────────────────
    CorpusEntry(
        key="ie-tgdb-2020-v2",
        title="Technical Guidance Document B — Fire Safety, Volume 2: Dwelling Houses",
        jurisdiction="IE",
        publisher="Dept. of Housing, Local Government and Heritage",
        edition="2006 edition, 2020 reprint",
        url="https://assets.gov.ie/100107/46250a2d-e09c-480a-8290-eb0b8bddcdcd.pdf",
        filename="IE_TGDB_2020_vol2_dwellings.pdf",
    ),
    CorpusEntry(
        key="ie-tgdb-2020-amended",
        title="Technical Guidance Document B — Fire Safety (2006, amended 2020)",
        jurisdiction="IE",
        publisher="Dept. of Housing, Local Government and Heritage",
        edition="2006 edition amended 2020",
        url="https://www.galway.ie/sites/default/files/2025-07/Technical%20Guidance%20Document%20Part%20B%20-%20Fire%20Safety%202006%20(Amended%202020).pdf",
        filename="IE_TGDB_2020_amended.pdf",
    ),
    CorpusEntry(
        key="ie-tgdb-2024-v1",
        title="Technical Guidance Document B — Fire Safety, Volume 1: Buildings other than Dwelling Houses",
        jurisdiction="IE",
        publisher="Dept. of Housing, Local Government and Heritage",
        edition="2024",
        url="https://assets.gov.ie/static/documents/technical-guidance-document-b-2024-fire-safety-volume-1-buildings-other-than-dwelling-.pdf",
        filename="IE_TGDB_2024_vol1_other.pdf",
        notes="Pairs with ie-tgdb-2020-amended to show how Irish guidance evolved.",
    ),
    # ── Scotland ─────────────────────────────────────────────────────
    CorpusEntry(
        key="sc-thb-2022-nd",
        title="Building Standards Technical Handbook 2022 — Non-domestic",
        jurisdiction="SC",
        publisher="Scottish Government",
        edition="June 2022 (July 2022 erratum)",
        url=(
            f"{_GOVSCOT}/building-standards-technical-handbook-2022-non-domestic/documents/"
            "building-standards-technical-handbook-2022-non-domestic/"
            "building-standards-technical-handbook-2022-non-domestic/govscot%3Adocument/"
            "Building%2Bstandards%2Btechnical%2Bhandbook%2B-%2Bnon-domestic%2B%2528June%2B2022%2529%2B-%2BJuly%2B2022%2Berratum.pdf"
        ),
        filename="SC_THB_2022_non_domestic.pdf",
        notes="Section 2 is the fire section; the handbook is published as one volume.",
    ),
    CorpusEntry(
        key="sc-thb-2022-d",
        title="Building Standards Technical Handbook 2022 — Domestic",
        jurisdiction="SC",
        publisher="Scottish Government",
        edition="June 2022 (July 2022 erratum)",
        url=(
            f"{_GOVSCOT}/building-standards-technical-handbook-2022-domestic/documents/"
            "building-standards-technical-handbook-2022-domestic/"
            "building-standards-technical-handbook-2022-domestic/govscot%3Adocument/"
            "Building%2Bstandards%2Btechnical%2Bhandbook%2B-%2Bdomestic%2B%2528June%2B2022%2529%2B-%2BJuly%2B2022%2Berratum.pdf"
        ),
        filename="SC_THB_2022_domestic.pdf",
    ),
    # ── British Standards (copyright BSI — not downloadable) ─────────
    CorpusEntry(
        key="bs-9999",
        title="BS 9999 — Fire safety in the design, management and use of buildings",
        jurisdiction="BSI",
        publisher="BSI",
        edition="BS 9999:2017",
        url="https://knowledge.bsigroup.com/products/fire-safety-in-the-design-management-and-use-of-buildings-code-of-practice-1",
        filename="BSI_BS9999_2017.pdf",
        access="licensed",
        notes="Sold under BSI copyright. Buy or use an institutional licence, then save the PDF here.",
    ),
    CorpusEntry(
        key="bs-9991",
        title="BS 9991 — Fire safety in the design, management and use of residential buildings",
        jurisdiction="BSI",
        publisher="BSI",
        edition="BS 9991:2024",
        url="https://knowledge.bsigroup.com/products/fire-safety-in-the-design-management-and-use-of-residential-buildings-code-of-practice",
        filename="BSI_BS9991_2024.pdf",
        access="licensed",
    ),
    CorpusEntry(
        key="bs-7974",
        title="BS 7974 — Application of fire safety engineering principles to the design of buildings",
        jurisdiction="BSI",
        publisher="BSI",
        edition="BS 7974:2019",
        url="https://knowledge.bsigroup.com/products/application-of-fire-safety-engineering-principles-to-the-design-of-buildings-code-of-practice",
        filename="BSI_BS7974_2019.pdf",
        access="licensed",
        notes="Framework standard; the PD 7974 series holds the sub-system guidance.",
    ),
]


ENTRY_BY_KEY = {e.key: e for e in ENTRIES}


def open_entries() -> list[CorpusEntry]:
    """Entries the fetcher is allowed to download."""
    return [e for e in ENTRIES if e.access == "open"]


def status() -> list[dict]:
    """Checklist rows: one per registered document, with on-disk state."""
    rows = []
    for e in ENTRIES:
        rows.append({
            "key": e.key,
            "title": e.title,
            "jurisdiction": e.jurisdiction,
            "publisher": e.publisher,
            "edition": e.edition,
            "kind": e.kind,
            "access": e.access,
            "url": e.url,
            "filename": e.filename,
            "present": e.present,
            "size_bytes": e.size_bytes,
            "notes": e.notes,
        })
    return rows


def summary() -> dict:
    """Collection progress, split by what is actually obtainable."""
    rows = status()
    downloadable = [r for r in rows if r["access"] == "open"]
    licensed = [r for r in rows if r["access"] == "licensed"]
    return {
        "total": len(rows),
        "collected": sum(1 for r in rows if r["present"]),
        "downloadable": len(downloadable),
        "downloadable_collected": sum(1 for r in downloadable if r["present"]),
        "licensed": len(licensed),
        "licensed_collected": sum(1 for r in licensed if r["present"]),
        "bytes": sum(r["size_bytes"] for r in rows),
    }
