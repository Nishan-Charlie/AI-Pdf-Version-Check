"""
Database CRUD & Upsert Operations
───────────────────────────────────
High-level functions for managing Documents, Versions, and Clauses.
"""

import hashlib
from typing import Optional
from sqlalchemy.orm import Session

from database.models import Document, Version, Clause
from database.db import get_session


# ─── Document Operations ─────────────────────────────────────────────

def upsert_document(name: str, description: Optional[str] = None) -> Document:
    """
    Get an existing document by name, or create a new one.

    Args:
        name: Unique document name.
        description: Optional description.

    Returns:
        The existing or newly created Document instance (detached-safe).
    """
    session = get_session()
    try:
        doc = session.query(Document).filter(Document.name == name).first()
        if doc is None:
            doc = Document(name=name, description=description)
            session.add(doc)
            session.commit()
        elif description and doc.description != description:
            doc.description = description
            session.commit()
        session.refresh(doc)
        return doc
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_all_documents() -> list[Document]:
    """Return all documents ordered by name."""
    session = get_session()
    try:
        return session.query(Document).order_by(Document.name).all()
    finally:
        session.close()


def get_document_by_id(document_id: int) -> Optional[Document]:
    """Fetch a single document by its ID."""
    session = get_session()
    try:
        return session.query(Document).filter(Document.id == document_id).first()
    finally:
        session.close()


# ─── Version Operations ──────────────────────────────────────────────

def add_version(
    document_id: int,
    version_label: str,
    source_file: Optional[str],
    clauses_data: list[dict],
) -> Version:
    """
    Add a new version to a document with its parsed clauses.

    If a version with the same label already exists for this document,
    it is replaced (delete + re-create) to support re-uploads.

    Args:
        document_id: FK to the parent Document.
        version_label: Human-readable label (e.g., "2024 Edition").
        source_file: Original filename of the uploaded PDF.
        clauses_data: List of dicts with keys: clause_number, title, content.

    Returns:
        The newly created Version instance.
    """
    session = get_session()
    try:
        # Remove existing version with same label (upsert behavior)
        existing = (
            session.query(Version)
            .filter(
                Version.document_id == document_id,
                Version.version_label == version_label,
            )
            .first()
        )
        if existing:
            session.delete(existing)
            session.flush()

        # Create new version
        version = Version(
            document_id=document_id,
            version_label=version_label,
            source_file=source_file,
        )
        session.add(version)
        session.flush()  # Get version.id

        # Bulk-insert clauses
        for clause_data in clauses_data:
            content = clause_data.get("content", "")
            content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

            clause = Clause(
                version_id=version.id,
                clause_number=clause_data["clause_number"],
                title=clause_data.get("title"),
                content=content,
                content_hash=content_hash,
            )
            session.add(clause)

        session.commit()
        session.refresh(version)
        return version
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_versions(document_id: int) -> list[Version]:
    """Return all versions for a document, newest first."""
    session = get_session()
    try:
        return (
            session.query(Version)
            .filter(Version.document_id == document_id)
            .order_by(Version.uploaded_at.desc())
            .all()
        )
    finally:
        session.close()


def get_version_by_id(version_id: int) -> Optional[Version]:
    """Fetch a single version by its ID."""
    session = get_session()
    try:
        return session.query(Version).filter(Version.id == version_id).first()
    finally:
        session.close()


# ─── Clause Operations ───────────────────────────────────────────────

def get_clauses(version_id: int) -> list[Clause]:
    """Return all clauses for a version, ordered by clause number."""
    session = get_session()
    try:
        return (
            session.query(Clause)
            .filter(Clause.version_id == version_id)
            .order_by(Clause.clause_number)
            .all()
        )
    finally:
        session.close()


def get_clause_count(version_id: int) -> int:
    """Return the number of clauses in a version."""
    session = get_session()
    try:
        return session.query(Clause).filter(Clause.version_id == version_id).count()
    finally:
        session.close()
