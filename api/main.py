"""
Fire Safety Regulation Comparison — HTTP API
────────────────────────────────────────────
Serves the Next.js dashboard. Ingests PDFs, runs comparisons, and searches the
clause library.

    uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import csv
import io
import os
import sys
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.schemas import CompareRequest
from comparison.engine import SemanticComparator
from comparison.report import ChangeType, VersionRef
from config import (
    ALIGNMENT_AUTO,
    AUTO_JURISDICTION,
    CORPUS_SEARCH_LIMIT,
    JURISDICTIONS,
    MINOR_EDIT_THRESHOLD,
    MODEL_NAME,
    UNCHANGED_THRESHOLD,
)
from corpus import registry
from database.db import init_db
from database.operations import (
    add_version,
    delete_document,
    delete_version,
    get_all_documents,
    get_clauses,
    get_version,
    library_stats,
    list_all_versions,
    search_clauses,
    upsert_document,
)
from ingestion.pipeline import ingest_pdf

app = FastAPI(
    title="Fire Safety Regulation Comparison",
    description="Clause-level version and cross-country comparison of fire safety regulations.",
    version="2.0.0",
)

# The dashboard runs on its own origin in development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_comparator = SemanticComparator()
_MAX_UPLOAD_BYTES = 120 * 1024 * 1024


@app.on_event("startup")
def _startup() -> None:
    applied = init_db()
    for statement in applied:
        print(f"[migrate] {statement}")


# ─── Reference data ──────────────────────────────────────────────────

@app.get("/api/meta")
def meta() -> dict:
    """Jurisdictions, thresholds, and change types the UI renders."""
    return {
        "jurisdictions": JURISDICTIONS,
        "change_types": [t.value for t in ChangeType],
        "thresholds": {
            "unchanged": UNCHANGED_THRESHOLD,
            "minor_edit": MINOR_EDIT_THRESHOLD,
        },
        "model": MODEL_NAME,
        "stats": library_stats(),
    }


@app.get("/api/corpus")
def corpus() -> dict:
    """The reference collection checklist and how much of it is held."""
    return {"summary": registry.summary(), "entries": registry.status()}


# ─── Library ─────────────────────────────────────────────────────────

@app.get("/api/documents")
def documents(country: Optional[str] = Query(None)) -> dict:
    return {"documents": get_all_documents(country_code=country)}


@app.get("/api/versions")
def versions(country: Optional[str] = Query(None)) -> dict:
    """Every stored version, flat — either side of a comparison can be any of them."""
    return {"versions": list_all_versions(country_code=country)}


@app.get("/api/versions/{version_id}/clauses")
def version_clauses(version_id: int) -> dict:
    if get_version(version_id) is None:
        raise HTTPException(404, f"No version with id {version_id}")
    return {"clauses": get_clauses(version_id)}


@app.delete("/api/versions/{version_id}")
def remove_version(version_id: int) -> dict:
    if not delete_version(version_id):
        raise HTTPException(404, f"No version with id {version_id}")
    return {"deleted": version_id}


@app.delete("/api/documents/{document_id}")
def remove_document(document_id: int) -> dict:
    if not delete_document(document_id):
        raise HTTPException(404, f"No document with id {document_id}")
    return {"deleted": document_id}


# ─── Ingestion ───────────────────────────────────────────────────────

@app.post("/api/ingest")
async def ingest(
    file: UploadFile = File(...),
    document_name: str = Form(...),
    version_label: str = Form(...),
    country_code: str = Form(AUTO_JURISDICTION),
    description: str = Form(""),
    publisher: str = Form(""),
) -> dict:
    """
    Parse an uploaded PDF and store it as a version.

    `country_code` may be "AUTO", in which case the jurisdiction is read from
    the document's own text.
    """
    document_name = document_name.strip()
    version_label = version_label.strip()

    if not document_name:
        raise HTTPException(422, "Give the document a name.")
    if not version_label:
        raise HTTPException(422, "Give this version a label.")

    payload = await file.read()
    if not payload:
        raise HTTPException(422, "The uploaded file is empty.")
    if len(payload) > _MAX_UPLOAD_BYTES:
        raise HTTPException(413, "That PDF is larger than the 120 MB limit.")

    try:
        result = ingest_pdf(payload, file.filename or "uploaded.pdf", country_code)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc

    if not result.clauses:
        raise HTTPException(
            422,
            f"No clauses were found in '{file.filename}'. It may not be a "
            "numbered regulation document.",
        )

    document = upsert_document(
        name=document_name,
        description=description.strip() or None,
        country_code=result.country_code,
        doc_type=result.profile_label,
        publisher=publisher.strip() or None,
    )

    version = add_version(
        document_id=document["id"],
        version_label=version_label,
        source_file=file.filename,
        clauses_data=result.clauses,
        parser_profile=result.profile_name,
        parser_confidence=f"{result.confidence:.2f}",
        page_count=result.page_count,
    )

    return {"document": document, "version": version, "parse": result.as_dict()}


# ─── Comparison ──────────────────────────────────────────────────────

@app.post("/api/compare")
def compare(request: CompareRequest) -> dict:
    """
    Compare two versions clause by clause.

    The two versions need not belong to the same document or the same country.
    """
    if request.version_v1 == request.version_v2:
        raise HTTPException(422, "Pick two different versions to compare.")

    report = _run_comparison(
        request.version_v1, request.version_v2, request.strategy
    )
    return report.as_dict()


@app.get("/api/compare/export")
def compare_export(
    version_v1: int = Query(...),
    version_v2: int = Query(...),
    strategy: str = Query(ALIGNMENT_AUTO),
) -> StreamingResponse:
    """The same comparison as a CSV download."""
    if version_v1 == version_v2:
        raise HTTPException(422, "Pick two different versions to compare.")

    report = _run_comparison(version_v1, version_v2, strategy)
    rows = report.to_rows()

    buffer = io.StringIO()
    if rows:
        writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    filename = (
        f"comparison_{_slug(report.v1.version_label)}"
        f"_vs_{_slug(report.v2.version_label)}.csv"
    )

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _run_comparison(version_v1: int, version_v2: int, strategy: str):
    left = get_version(version_v1)
    right = get_version(version_v2)

    if left is None:
        raise HTTPException(404, f"No version with id {version_v1}")
    if right is None:
        raise HTTPException(404, f"No version with id {version_v2}")

    clauses_v1 = get_clauses(version_v1)
    clauses_v2 = get_clauses(version_v2)

    if not clauses_v1 or not clauses_v2:
        raise HTTPException(422, "One of these versions has no stored clauses.")

    return _comparator.compare(
        clauses_v1,
        clauses_v2,
        ref_v1=_ref(left),
        ref_v2=_ref(right),
        strategy=strategy,
    )


def _ref(version: dict) -> VersionRef:
    return VersionRef(
        version_id=version["id"],
        document_name=version["document_name"],
        version_label=version["version_label"],
        country_code=version["country_code"],
        country_name=version["country_name"],
    )


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text).strip("_") or "version"


# ─── Search ──────────────────────────────────────────────────────────

@app.get("/api/search")
def search(
    q: str = Query(..., min_length=2),
    country: Optional[str] = Query(None),
    limit: int = Query(CORPUS_SEARCH_LIMIT, le=500),
) -> dict:
    """Find a keyword anywhere in the stored clause library."""
    results = search_clauses(q, country_code=country, limit=limit)
    return {"query": q, "count": len(results), "results": results}


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "model": MODEL_NAME}
