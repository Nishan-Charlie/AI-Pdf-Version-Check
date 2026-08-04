"""
Schema Migrations
─────────────────
Brings an existing fire_safety.db up to the current model without dropping
data. SQLite only supports additive ALTERs, which is all this needs: every
column added since the first release is nullable or has a server default.

`init_db()` runs this on every start, so upgrading is just launching the app.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from config import DEFAULT_JURISDICTION

# table → column → SQLite column definition
_ADDITIONS: dict[str, dict[str, str]] = {
    "documents": {
        "country_code": f"VARCHAR(8) NOT NULL DEFAULT '{DEFAULT_JURISDICTION}'",
        "doc_type": "VARCHAR(120)",
        "publisher": "VARCHAR(300)",
    },
    "versions": {
        "parser_profile": "VARCHAR(60)",
        "parser_confidence": "VARCHAR(20)",
        "page_count": "INTEGER",
    },
    "clauses": {
        "section": "VARCHAR(500)",
        "level": "INTEGER NOT NULL DEFAULT 2",
        "ordinal": "INTEGER NOT NULL DEFAULT 0",
    },
}

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_documents_country_code ON documents (country_code)",
    "CREATE INDEX IF NOT EXISTS ix_clause_version_ordinal ON clauses (version_id, ordinal)",
]


def _existing_columns(connection, table: str) -> set[str]:
    rows = connection.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {row[1] for row in rows}


def _table_exists(connection, table: str) -> bool:
    row = connection.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
        {"name": table},
    ).first()
    return row is not None


def migrate(engine: Engine) -> list[str]:
    """
    Apply outstanding migrations. Returns the statements that ran, so a caller
    can log what changed rather than guessing.
    """
    applied: list[str] = []

    with engine.begin() as connection:
        for table, columns in _ADDITIONS.items():
            if not _table_exists(connection, table):
                continue  # create_all will build it from the model
            present = _existing_columns(connection, table)
            for column, definition in columns.items():
                if column in present:
                    continue
                statement = f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                connection.execute(text(statement))
                applied.append(statement)

        if _table_exists(connection, "clauses"):
            applied.extend(_backfill_ordinals(connection))

        for statement in _INDEXES:
            connection.execute(text(statement))

    return applied


def _backfill_ordinals(connection) -> list[str]:
    """
    Give pre-migration clauses a document order.

    Rows inserted before `ordinal` existed all default to 0, which would make
    every version's clauses sort arbitrarily. Insertion order is the original
    document order, so rowid recovers it exactly.
    """
    stale = connection.execute(text("""
        SELECT version_id
        FROM clauses
        GROUP BY version_id
        HAVING COUNT(*) > 1 AND MAX(ordinal) = 0
    """)).fetchall()

    if not stale:
        return []

    connection.execute(text("""
        UPDATE clauses
        SET ordinal = (
            SELECT COUNT(*)
            FROM clauses AS earlier
            WHERE earlier.version_id = clauses.version_id
              AND earlier.id < clauses.id
        )
        WHERE version_id IN (
            SELECT version_id FROM clauses
            GROUP BY version_id
            HAVING COUNT(*) > 1 AND MAX(ordinal) = 0
        )
    """))

    return [f"backfilled clause ordinals for {len(stale)} version(s)"]
