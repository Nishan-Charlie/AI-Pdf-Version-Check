"""
SQLAlchemy ORM Models
─────────────────────
Document → Version → Clause.

A Document is one regulatory instrument in one jurisdiction (for example
Approved Document B in England & Wales). A Version is a dated edition of it.
Comparisons run between any two Versions, including Versions belonging to
different Documents in different jurisdictions.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, Index
)
from sqlalchemy.orm import declarative_base, relationship

from config import DEFAULT_JURISDICTION

Base = declarative_base()


class Document(Base):
    """
    A regulatory instrument, scoped to the jurisdiction that publishes it.
    A document can have many versions over time.
    """
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(500), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)

    # Jurisdiction code from config.JURISDICTIONS ("EW", "SC", "NI", "IE", …)
    country_code = Column(
        String(8), nullable=False,
        default=DEFAULT_JURISDICTION, server_default=DEFAULT_JURISDICTION,
        index=True,
    )
    # Publishing tradition, e.g. "Approved Document", "Technical Handbook"
    doc_type = Column(String(120), nullable=True)
    publisher = Column(String(300), nullable=True)

    created_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    versions = relationship(
        "Version", back_populates="document",
        cascade="all, delete-orphan",
        order_by="Version.uploaded_at.desc()"
    )

    def __repr__(self):
        return f"<Document(id={self.id}, name='{self.name}', country='{self.country_code}')>"


class Version(Base):
    """A dated edition of a document, holding one set of parsed clauses."""
    __tablename__ = "versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    version_label = Column(String(200), nullable=False)
    source_file = Column(String(1000), nullable=True)

    # Which parsing grammar read this file, and how sure the detector was.
    # Recorded so a comparison can explain how its clauses were derived.
    parser_profile = Column(String(60), nullable=True)
    parser_confidence = Column(String(20), nullable=True)
    page_count = Column(Integer, nullable=True)

    uploaded_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    document = relationship("Document", back_populates="versions")
    clauses = relationship(
        "Clause", back_populates="version",
        cascade="all, delete-orphan",
        order_by="Clause.ordinal"
    )

    __table_args__ = (
        Index("ix_version_doc_label", "document_id", "version_label", unique=True),
    )

    def __repr__(self):
        return (
            f"<Version(id={self.id}, doc_id={self.document_id}, "
            f"label='{self.version_label}')>"
        )


class Clause(Base):
    """
    One clause within a version.

    `ordinal` is the clause's position in the document. It is the ordering key
    everywhere, because clause numbers sort wrongly as strings ("10.1" before
    "2.1") and cross-country comparisons cannot rely on them at all.
    """
    __tablename__ = "clauses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version_id = Column(
        Integer, ForeignKey("versions.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    clause_number = Column(String(80), nullable=False)
    title = Column(String(500), nullable=True)
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=True, index=True)

    # Nearest enclosing heading — topic context for cross-country matching.
    section = Column(String(500), nullable=True)
    level = Column(Integer, nullable=False, default=2, server_default="2")
    ordinal = Column(Integer, nullable=False, default=0, server_default="0")

    version = relationship("Version", back_populates="clauses")

    __table_args__ = (
        Index("ix_clause_version_number", "version_id", "clause_number"),
        Index("ix_clause_version_ordinal", "version_id", "ordinal"),
    )

    def __repr__(self):
        return (
            f"<Clause(id={self.id}, version_id={self.version_id}, "
            f"number='{self.clause_number}')>"
        )
