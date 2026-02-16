"""
Vehicle pricelist Pydantic schemas.
These define the structured output format for the API.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Leaf / nested models
# ---------------------------------------------------------------------------

class EngineInfo(BaseModel):
    displacement: Optional[str] = None
    fuel_type: Optional[str] = None
    power_hp: Optional[float] = None
    power_kw: Optional[float] = None
    description: Optional[str] = None


class PriceInfo(BaseModel):
    value: Optional[float] = None
    currency: Optional[str] = None
    includes_tax: Optional[bool] = None
    tax_rate: Optional[float] = None


class OptionItem(BaseModel):
    name: str
    code: Optional[str] = None
    price: Optional[float] = None


class SourceInfo(BaseModel):
    file_name: str
    page: int
    table_index: int


# ---------------------------------------------------------------------------
# Row-level schema
# ---------------------------------------------------------------------------

class VehicleRow(BaseModel):
    """One vehicle row extracted from a pricelist table."""

    make: Optional[str] = None
    model: Optional[str] = None
    variant: Optional[str] = None
    trim: Optional[str] = None
    body_type: Optional[str] = None

    engine: Optional[EngineInfo] = Field(default_factory=EngineInfo)
    transmission: Optional[str] = None
    drivetrain: Optional[str] = None
    doors: Optional[int] = None
    seats: Optional[int] = None

    price: Optional[PriceInfo] = Field(default_factory=PriceInfo)
    msrp: Optional[float] = None
    effective_date: Optional[str] = None
    country: Optional[str] = None

    options: List[OptionItem] = Field(default_factory=list)
    source: Optional[SourceInfo] = None

    # Catch-all for unmapped columns
    extra: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Table-level schema
# ---------------------------------------------------------------------------

class TableResult(BaseModel):
    """One table extracted from a page / sheet."""
    table_index: int = 0
    headers: List[str] = Field(default_factory=list)
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    raw_html: str = ""


class PageResult(BaseModel):
    """Results for one page (PDF/image) or one sheet (Excel)."""
    page: int
    sheet_name: Optional[str] = None
    tables: List[TableResult] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Top-level response
# ---------------------------------------------------------------------------

class ParseResponse(BaseModel):
    """Top-level API response for ``POST /parse``."""
    status: str = "success"
    file_name: str = ""
    file_type: str = ""
    pages: int = 0
    processing_time_seconds: float = 0.0
    data: List[PageResult] = Field(default_factory=list)


class AsyncAcceptedResponse(BaseModel):
    """Response for ``POST /parse/async``."""
    status: str = "accepted"
    job_id: str = ""
    message: str = ""
    estimated_seconds: float = 0.0


class JobStatusResponse(BaseModel):
    """Response for ``GET /result/{job_id}``."""
    status: str  # "processing" | "completed" | "failed"
    job_id: str
    file_name: str = ""
    pages: int = 0
    processing_time_seconds: float = 0.0
    progress: str = ""
    estimated_remaining_seconds: Optional[float] = None
    data: List[PageResult] = Field(default_factory=list)
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Response for ``GET /health``."""
    status: str = "healthy"
    model_loaded: bool = False
    backend: str = ""
    model_file: str = ""
    device: str = "cpu"
    max_pixels: int = 0
    version: str = "1.0.0"
