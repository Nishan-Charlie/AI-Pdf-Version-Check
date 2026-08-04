"""Request bodies for the API."""

from __future__ import annotations

from pydantic import BaseModel, Field

from config import ALIGNMENT_AUTO, ALIGNMENT_IDENTIFIER, ALIGNMENT_SEMANTIC


class CompareRequest(BaseModel):
    """Which two versions to compare, and how to line their clauses up."""

    version_v1: int = Field(..., description="Baseline version id")
    version_v2: int = Field(..., description="Revised version id")
    strategy: str = Field(
        ALIGNMENT_AUTO,
        description=(
            f"'{ALIGNMENT_IDENTIFIER}' to match on clause number, "
            f"'{ALIGNMENT_SEMANTIC}' to match on meaning, "
            f"'{ALIGNMENT_AUTO}' to decide from the jurisdictions."
        ),
        pattern=f"^({ALIGNMENT_AUTO}|{ALIGNMENT_IDENTIFIER}|{ALIGNMENT_SEMANTIC})$",
    )
