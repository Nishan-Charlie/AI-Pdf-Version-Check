"""
SQLAlchemy ORM Models
─────────────────────
Defines the Document → Version → Clause hierarchy for storing
fire safety documents and tracking changes across versions.
"""

from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, ForeignKey, Index
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class Document(Base):
    """
    Represents a logical fire safety document (e.g., "NBC Fire Safety Code 2016").
    A document can have many versions over time.
    """
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(500), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    versions = relationship(
        "Version", back_populates="document",
        cascade="all, delete-orphan",
        order_by="Version.uploaded_at.desc()"
    )

    def __repr__(self):
        return f"<Document(id={self.id}, name='{self.name}')>"


class Version(Base):
    """
    A specific version/revision of a document, tied to a point in time.
    Each version contains a set of parsed clauses.
    """
    __tablename__ = "versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(
        Integer, ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    version_label = Column(String(200), nullable=False)
    source_file = Column(String(1000), nullable=True)
    uploaded_at = Column(
        DateTime, nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    document = relationship("Document", back_populates="versions")
    clauses = relationship(
        "Clause", back_populates="version",
        cascade="all, delete-orphan",
        order_by="Clause.clause_number"
    )

    # Composite index for quick lookups
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
    An individual clause/section within a document version.
    Stores the clause number, optional title, and full text content.
    """
    __tablename__ = "clauses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    version_id = Column(
        Integer, ForeignKey("versions.id", ondelete="CASCADE"),
        nullable=False, index=True
    )
    clause_number = Column(String(50), nullable=False)
    title = Column(String(500), nullable=True)
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=True, index=True)

    # Relationships
    version = relationship("Version", back_populates="clauses")

    # Composite index for clause lookups within a version
    __table_args__ = (
        Index("ix_clause_version_number", "version_id", "clause_number"),
    )

    def __repr__(self):
        return (
            f"<Clause(id={self.id}, version_id={self.version_id}, "
            f"number='{self.clause_number}')>"
        )
