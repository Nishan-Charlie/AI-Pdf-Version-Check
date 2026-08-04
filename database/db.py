"""
Database Session Management
────────────────────────────
Provides SQLAlchemy engine and session factory for the SQLite database.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from config import DATABASE_URL
from database.models import Base

# Module-level engine (lazy-initialized)
_engine = None
_SessionFactory = None


def get_engine():
    """Get or create the SQLAlchemy engine (singleton)."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            DATABASE_URL,
            echo=False,
            connect_args={"check_same_thread": False},  # SQLite threading
        )
    return _engine


def get_session() -> Session:
    """Create and return a new database session."""
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine())
    return _SessionFactory()


def init_db() -> list[str]:
    """
    Create missing tables and bring existing ones up to the current schema.

    Safe to call on every start. Returns the migration statements that ran.
    """
    from database.migrate import migrate

    engine = get_engine()
    applied = migrate(engine)      # additive ALTERs first, on live tables
    Base.metadata.create_all(engine)  # then anything missing outright
    return applied


def reset_db():
    """
    Drop and recreate all tables. USE WITH CAUTION — destroys all data.
    Intended for development/testing only.
    """
    engine = get_engine()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
