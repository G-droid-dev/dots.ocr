"""
API-level Pydantic models (request validation & response serialisation).
Re-exports the core schemas from ``schemas.pricelist`` and adds API-specific
wrappers such as error bodies.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

# Re-export the domain models so the API layer imports from one place
from schemas.pricelist import (  # noqa: F401
    AsyncAcceptedResponse,
    HealthResponse,
    JobStatusResponse,
    PageResult,
    ParseResponse,
    TableResult,
    VehicleRow,
)


# ---------------------------------------------------------------------------
# Error response
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    status: str = "error"
    detail: str = ""


# ---------------------------------------------------------------------------
# Parse request form fields (for documentation / OpenAPI schema)
# ---------------------------------------------------------------------------

class ParseFormFields(BaseModel):
    """
    Documents the multipart form fields accepted by ``POST /parse``.
    FastAPI extracts these via ``Form()``; this model is only for OpenAPI docs.
    """
    max_pixels: int = Field(default=1_000_000, ge=250_000, le=11_300_000)
    dpi: int = Field(default=150, ge=72, le=300)
    max_completion_tokens: int = Field(default=4096, ge=256, le=32_768)
    prompt_mode: str = Field(default="prompt_layout_all_en")
    tables_only: bool = Field(default=True)
    output_format: str = Field(
        default="structured",
        description="structured | raw | markdown",
    )
    field_mapping: Optional[str] = Field(
        default=None,
        description="Name of a YAML file in field_mappings/ (e.g. 'toyota_jp.yaml')",
    )
