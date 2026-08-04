"""
Database Operations
───────────────────
High-level reads and writes over Documents, Versions, and Clauses.

Every function returns plain dicts rather than ORM instances. Sessions are
short-lived and closed before returning, so detached-instance errors cannot
reach the API layer.
"""

from __future__ import annotations

import hashlib
from typing import Optional

from sqlalchemy import func, or_, select

from config import CORPUS_SEARCH_LIMIT, DEFAULT_JURISDICTION, jurisdiction_name
from database.db import get_session
from database.models import Clause, Document, Version


# ─── Serialisation ───────────────────────────────────────────────────

def _document_dict(doc: Document, version_count: int = 0) -> dict:
    return {
        "id": doc.id,
        "name": doc.name,
        "description": doc.description,
        "country_code": doc.country_code or DEFAULT_JURISDICTION,
        "country_name": jurisdiction_name(doc.country_code),
        "doc_type": doc.doc_type,
        "publisher": doc.publisher,
        "version_count": version_count,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
    }


def _version_dict(version: Version, doc: Document, clause_count: int = 0) -> dict:
    return {
        "id": version.id,
        "document_id": version.document_id,
        "document_name": doc.name,
        "country_code": doc.country_code or DEFAULT_JURISDICTION,
        "country_name": jurisdiction_name(doc.country_code),
        "doc_type": doc.doc_type,
        "version_label": version.version_label,
        "source_file": version.source_file,
        "parser_profile": version.parser_profile,
        "parser_confidence": version.parser_confidence,
        "page_count": version.page_count,
        "clause_count": clause_count,
        "uploaded_at": version.uploaded_at.isoformat() if version.uploaded_at else None,
    }


def _clause_dict(clause: Clause) -> dict:
    return {
        "id": clause.id,
        "clause_number": clause.clause_number,
        "title": clause.title,
        "content": clause.content,
        "section": clause.section,
        "level": clause.level or 2,
        "ordinal": clause.ordinal or 0,
    }


# ─── Documents ───────────────────────────────────────────────────────

def upsert_document(
    name: str,
    description: Optional[str] = None,
    country_code: str = DEFAULT_JURISDICTION,
    doc_type: Optional[str] = None,
    publisher: Optional[str] = None,
) -> dict:
    """Get a document by name, or create it. Later uploads refine its metadata."""
    session = get_session()
    try:
        doc = session.query(Document).filter(Document.name == name).first()

        if doc is None:
            doc = Document(
                name=name,
                description=description,
                country_code=country_code or DEFAULT_JURISDICTION,
                doc_type=doc_type,
                publisher=publisher,
            )
            session.add(doc)
        else:
            if description:
                doc.description = description
            if country_code:
                doc.country_code = country_code
            if doc_type:
                doc.doc_type = doc_type
            if publisher:
                doc.publisher = publisher

        session.commit()
        session.refresh(doc)
        return _document_dict(doc)
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_all_documents(country_code: Optional[str] = None) -> list[dict]:
    """All documents, newest jurisdiction-filtered first by name."""
    session = get_session()
    try:
        counts = dict(
            session.query(Version.document_id, func.count(Version.id))
            .group_by(Version.document_id)
            .all()
        )

        query = session.query(Document)
        if country_code:
            query = query.filter(Document.country_code == country_code)

        docs = query.order_by(Document.name).all()
        return [_document_dict(d, counts.get(d.id, 0)) for d in docs]
    finally:
        session.close()


def delete_document(document_id: int) -> bool:
    """Remove a document and everything under it."""
    session = get_session()
    try:
        doc = session.get(Document, document_id)
        if doc is None:
            return False
        session.delete(doc)
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ─── Versions ────────────────────────────────────────────────────────

def add_version(
    document_id: int,
    version_label: str,
    source_file: Optional[str],
    clauses_data: list[dict],
    parser_profile: Optional[str] = None,
    parser_confidence: Optional[str] = None,
    page_count: Optional[int] = None,
) -> dict:
    """
    Store a parsed version. Re-uploading the same label replaces it, so a
    failed parse can be corrected without hand-editing the database.
    """
    session = get_session()
    try:
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

        version = Version(
            document_id=document_id,
            version_label=version_label,
            source_file=source_file,
            parser_profile=parser_profile,
            parser_confidence=parser_confidence,
            page_count=page_count,
        )
        session.add(version)
        session.flush()

        session.add_all([
            Clause(
                version_id=version.id,
                clause_number=data["clause_number"],
                title=data.get("title"),
                content=data.get("content", ""),
                content_hash=hashlib.sha256(
                    data.get("content", "").encode("utf-8")
                ).hexdigest(),
                section=data.get("section"),
                level=data.get("level", 2),
                ordinal=data.get("ordinal", index),
            )
            for index, data in enumerate(clauses_data)
        ])

        session.commit()
        session.refresh(version)
        doc = session.get(Document, document_id)
        return _version_dict(version, doc, len(clauses_data))
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_versions(document_id: int) -> list[dict]:
    """Versions of one document, newest first."""
    session = get_session()
    try:
        doc = session.get(Document, document_id)
        if doc is None:
            return []
        counts = _clause_counts(session)
        versions = (
            session.query(Version)
            .filter(Version.document_id == document_id)
            .order_by(Version.uploaded_at.desc())
            .all()
        )
        return [_version_dict(v, doc, counts.get(v.id, 0)) for v in versions]
    finally:
        session.close()


def list_all_versions(country_code: Optional[str] = None) -> list[dict]:
    """
    Every version in the library as a flat list.

    This is what the comparison picker reads: either side can be any version
    from any document, which is what makes cross-country comparison possible.
    """
    session = get_session()
    try:
        counts = _clause_counts(session)
        query = session.query(Version, Document).join(
            Document, Version.document_id == Document.id
        )
        if country_code:
            query = query.filter(Document.country_code == country_code)

        rows = query.order_by(
            Document.country_code, Document.name, Version.uploaded_at.desc()
        ).all()
        return [_version_dict(v, d, counts.get(v.id, 0)) for v, d in rows]
    finally:
        session.close()


def get_version(version_id: int) -> Optional[dict]:
    """One version with its document context."""
    session = get_session()
    try:
        version = session.get(Version, version_id)
        if version is None:
            return None
        doc = session.get(Document, version.document_id)
        counts = _clause_counts(session)
        return _version_dict(version, doc, counts.get(version.id, 0))
    finally:
        session.close()


def delete_version(version_id: int) -> bool:
    """Remove a single version and its clauses."""
    session = get_session()
    try:
        version = session.get(Version, version_id)
        if version is None:
            return False
        session.delete(version)
        session.commit()
        return True
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _clause_counts(session) -> dict[int, int]:
    return dict(
        session.query(Clause.version_id, func.count(Clause.id))
        .group_by(Clause.version_id)
        .all()
    )


# ─── Clauses ─────────────────────────────────────────────────────────

def get_clauses(version_id: int) -> list[dict]:
    """All clauses of a version in document order."""
    session = get_session()
    try:
        clauses = (
            session.query(Clause)
            .filter(Clause.version_id == version_id)
            .order_by(Clause.ordinal, Clause.id)
            .all()
        )
        return [_clause_dict(c) for c in clauses]
    finally:
        session.close()


# ─── Search ──────────────────────────────────────────────────────────

def search_clauses(
    query: str,
    country_code: Optional[str] = None,
    version_ids: Optional[list[int]] = None,
    limit: int = CORPUS_SEARCH_LIMIT,
) -> list[dict]:
    """
    Find clauses anywhere in the library whose text mentions `query`.

    Matches on clause text, title, section, and clause number so an auditor
    can search "door", "B3", or "means of escape" through the same box.
    """
    term = (query or "").strip()
    if len(term) < 2:
        return []

    pattern = f"%{term}%"
    session = get_session()
    try:
        statement = (
            select(Clause, Version, Document)
            .join(Version, Clause.version_id == Version.id)
            .join(Document, Version.document_id == Document.id)
            .where(or_(
                Clause.content.ilike(pattern),
                Clause.title.ilike(pattern),
                Clause.section.ilike(pattern),
                Clause.clause_number.ilike(pattern),
            ))
        )
        if country_code:
            statement = statement.where(Document.country_code == country_code)
        if version_ids:
            statement = statement.where(Clause.version_id.in_(version_ids))

        statement = statement.order_by(
            Document.country_code, Document.name, Clause.ordinal
        ).limit(limit)

        results = []
        for clause, version, doc in session.execute(statement).all():
            results.append({
                **_clause_dict(clause),
                "version_id": version.id,
                "version_label": version.version_label,
                "document_id": doc.id,
                "document_name": doc.name,
                "country_code": doc.country_code or DEFAULT_JURISDICTION,
                "country_name": jurisdiction_name(doc.country_code),
                "excerpt": _excerpt(clause.content, term),
            })
        return results
    finally:
        session.close()


def _excerpt(content: str, term: str, window: int = 160) -> str:
    """A window of text around the first hit, for the search results list."""
    position = content.lower().find(term.lower())
    if position < 0:
        return content[:window].strip()

    start = max(0, position - window // 2)
    end = min(len(content), position + len(term) + window // 2)
    snippet = content[start:end].strip()

    return f"{'…' if start > 0 else ''}{snippet}{'…' if end < len(content) else ''}"


def library_stats() -> dict:
    """Headline counts for the dashboard."""
    session = get_session()
    try:
        by_country = dict(
            session.query(Document.country_code, func.count(Document.id))
            .group_by(Document.country_code)
            .all()
        )
        return {
            "documents": session.query(func.count(Document.id)).scalar() or 0,
            "versions": session.query(func.count(Version.id)).scalar() or 0,
            "clauses": session.query(func.count(Clause.id)).scalar() or 0,
            "by_country": by_country,
        }
    finally:
        session.close()
