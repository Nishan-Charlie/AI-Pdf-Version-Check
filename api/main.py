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
import threading
import time
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api import downloads
from api.schemas import CompareRequest
from comparison.engine import get_comparator, loaded_models
from comparison.report import ChangeType, VersionRef
from config import (
    ALIGNMENT_AUTO,
    AUTO_JURISDICTION,
    CORPUS_SEARCH_LIMIT,
    JURISDICTIONS,
    LOW_MEMORY_THRESHOLD_MB,
    MAX_LOADED_MODELS,
    MINOR_EDIT_THRESHOLD,
    MODEL_NAME,
    MODEL_REGISTRY,
    PRELOAD_DEFAULT_MODEL,
    PRELOAD_MAY_DOWNLOAD,
    UNCHANGED_THRESHOLD,
    hf_repo_id,
    model_is_downloaded,
    resolve_model,
    total_ram_mb,
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

_MAX_UPLOAD_BYTES = 120 * 1024 * 1024


@app.on_event("startup")
def _startup() -> None:
    applied = init_db()
    for statement in applied:
        print(f"[migrate] {statement}")

    if PRELOAD_DEFAULT_MODEL:
        _preload_default_model()


def _preload_default_model() -> None:
    """
    Load the default encoder in the background as the service comes up.

    On a thread, so the API answers immediately: the library, corpus, and
    version lists are all usable while the weights load, and only a comparison
    has to wait. Loading on the first comparison instead would make that one
    request several seconds slower than every other for no visible reason.

    A model that is not yet downloaded is normally left alone — fetching
    hundreds of megabytes unasked at startup is not the service's decision to
    make, and the dashboard offers it with a progress bar instead. Setting
    FIRE_SAFETY_PRELOAD_DOWNLOAD reverses that, which is right in a container:
    with a fresh model volume, the alternative is that the user's first
    comparison downloads the encoder inside the request and outlasts the
    dashboard's proxy timeout.
    """
    if not model_is_downloaded(MODEL_NAME) and not PRELOAD_MAY_DOWNLOAD:
        print(f"[model] {MODEL_NAME} is not on disk yet; "
              f"it will be fetched when you first compare")
        return

    def load() -> None:
        started = time.perf_counter()
        if not model_is_downloaded(MODEL_NAME):
            print(f"[model] downloading {MODEL_NAME} — the service is already "
                  f"answering, but comparisons wait for this")
        try:
            get_comparator(MODEL_NAME)
            print(f"[model] {MODEL_NAME} ready in {time.perf_counter() - started:.1f}s")
        except Exception as exc:  # noqa: BLE001 — startup must not die for this
            # Say what failed and what happens next. A bare message here reads
            # as though the service is broken, when in fact the model is simply
            # fetched on demand instead.
            print(f"[model] could not preload {MODEL_NAME}")
            print(f"[model]   {type(exc).__name__}: {exc}")
            print(f"[model]   the service is still usable — the model will be "
                  f"downloaded when you first compare")
            print(f"[model]   if this repeats, clear the cached copy and let it "
                  f"download again:")
            print(f"[model]   python -c \"import shutil,os;"
                  f"from huggingface_hub.constants import HF_HUB_CACHE;"
                  f"shutil.rmtree(os.path.join(HF_HUB_CACHE,'models--"
                  f"{hf_repo_id(MODEL_NAME).replace('/', '--')}'),ignore_errors=True)\"")

    threading.Thread(target=load, daemon=True, name="preload-model").start()


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


@app.get("/api/models")
def models() -> dict:
    """
    Encoders the comparison can run on, and whether each is ready to use.

    `downloaded` lets the interface distinguish an instant switch from one that
    fetches hundreds of megabytes first, so a first comparison on a new model
    does not look like a hang.
    """
    resident = set(loaded_models())
    ram = total_ram_mb()
    constrained = bool(ram) and ram < LOW_MEMORY_THRESHOLD_MB

    entries = []
    for key, meta in MODEL_REGISTRY.items():
        entries.append({
            "key": key,
            "id": meta["id"],
            "dimensions": meta["dim"],
            "window": meta["window"],
            "size_mb": meta["size_mb"],
            "ram_mb": meta["ram_mb"],
            "downloaded": model_is_downloaded(meta["id"]),
            "loaded": meta["id"] in resident,
            "is_default": meta["id"] == MODEL_NAME,
            # A model this service can hold without starving whatever else the
            # machine is running — the dashboard's compiler, most of all.
            "heavy_for_machine": constrained and meta["ram_mb"] > 1000,
        })

    return {
        "default": MODEL_NAME,
        "models": entries,
        "machine": {
            "total_ram_mb": ram,
            "low_memory": constrained,
            "max_loaded_models": MAX_LOADED_MODELS,
        },
    }


@app.post("/api/models/download")
def start_model_download(model: Optional[str] = Query(None)) -> dict:
    """
    Begin fetching a model in the background.

    Returns immediately with a job to poll, so the interface can show what is
    happening instead of holding a request open for several minutes. Calling
    this for a model already held returns a finished job straight away.
    """
    model_id = resolve_model(model)

    if model_is_downloaded(model_id) and model_id in loaded_models():
        return {
            "model": model_id,
            "state": downloads.READY,
            "percent": 100.0,
            "done_bytes": 0,
            "total_bytes": 0,
            "message": "Ready",
            "error": "",
            "elapsed_seconds": 0.0,
        }

    return downloads.start(model_id).as_dict()


@app.get("/api/models/status")
def model_download_status(model: Optional[str] = Query(None)) -> dict:
    """Progress of a model fetch, for polling while the bar is on screen."""
    model_id = resolve_model(model)
    job = downloads.get_job(model_id)

    if job is None:
        held = model_is_downloaded(model_id)
        return {
            "model": model_id,
            "state": downloads.READY if held and model_id in loaded_models() else downloads.IDLE,
            "percent": 100.0 if held else 0.0,
            "done_bytes": 0,
            "total_bytes": 0,
            "message": "On disk" if held else "Not downloaded",
            "error": "",
            "elapsed_seconds": 0.0,
        }

    return job.as_dict()


@app.post("/api/models/warm")
def warm_model(model: Optional[str] = Query(None)) -> dict:
    """
    Load a model now and wait for it.

    The blocking counterpart to /api/models/download, for scripts that would
    rather wait than poll.
    """
    model_id = resolve_model(model)
    try:
        comparator = get_comparator(model_id)
        dimensions = comparator.dimension          # touching it forces the load
        window = comparator.model.max_seq_length
    except Exception as exc:  # noqa: BLE001 — surface the loader's own message
        raise HTTPException(502, f"Could not load '{model_id}': {exc}") from exc

    return {
        "model": model_id,
        "dimensions": dimensions,
        "window": window,
        "loaded": True,
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
        request.version_v1, request.version_v2, request.strategy, request.model
    )
    return report.as_dict()


@app.get("/api/compare/export")
def compare_export(
    version_v1: int = Query(...),
    version_v2: int = Query(...),
    strategy: str = Query(ALIGNMENT_AUTO),
    model: Optional[str] = Query(None),
) -> StreamingResponse:
    """The same comparison as a CSV download."""
    if version_v1 == version_v2:
        raise HTTPException(422, "Pick two different versions to compare.")

    report = _run_comparison(version_v1, version_v2, strategy, model)
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


def _run_comparison(
    version_v1: int,
    version_v2: int,
    strategy: str,
    model: Optional[str] = None,
):
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

    try:
        comparator = get_comparator(model)
    except Exception as exc:  # noqa: BLE001 — surface the loader's own message
        raise HTTPException(502, f"Could not load model '{model}': {exc}") from exc

    return comparator.compare(
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
    return {"status": "ok", "model": MODEL_NAME, "loaded": loaded_models()}
