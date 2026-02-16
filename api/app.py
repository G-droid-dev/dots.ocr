"""
FastAPI application — vehicle pricelist parsing API.

Endpoints
---------
POST /parse          Synchronous document parsing
POST /parse/async    Asynchronous parsing (returns job ID)
GET  /result/{id}    Poll async job status
GET  /health         Health check
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

# Ensure repo root is on sys.path so imports like ``schemas.*`` resolve
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from api.job_queue import JobQueue, JobStatus, job_queue  # noqa: E402
from api.schemas import (  # noqa: E402
    AsyncAcceptedResponse,
    ErrorResponse,
    HealthResponse,
    JobStatusResponse,
    PageResult,
    ParseResponse,
    TableResult,
)
from dots_ocr.parser import DotsOCRParser  # noqa: E402
from dots_ocr.utils.consts import (  # noqa: E402
    DEFAULT_DPI,
    DEFAULT_MAX_TOKENS,
    MAX_PIXELS,
    excel_extensions,
    image_extensions,
)
from dots_ocr.utils.table_extractor import extract_tables_from_cells  # noqa: E402

# ---------------------------------------------------------------------------
# App initialisation
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Dots.OCR Vehicle Pricelist API",
    version="1.0.0",
    description="Offline API for parsing OEM vehicle pricelists from PDF, images, and Excel files.",
)

# Global parser instance — loaded once at startup
_parser: Optional[DotsOCRParser] = None

# Background thread pool for async jobs
_executor = ThreadPoolExecutor(max_workers=2)

# Supported extensions
_SUPPORTED_EXTS = {".pdf"} | image_extensions | excel_extensions


def _get_parser() -> DotsOCRParser:
    """Lazy-load the parser on first request."""
    global _parser
    if _parser is None:
        backend = os.getenv("DOTS_BACKEND", "hf")
        device = os.getenv("DOTS_DEVICE", "cpu")
        model_path = os.getenv("DOTS_MODEL_PATH", os.path.join(_REPO_ROOT, "weights", "DotsOCR"))

        _parser = DotsOCRParser(
            backend=backend,
            device=device,
            model_path=model_path,
            tables_only=True,
            dpi=DEFAULT_DPI,
            max_completion_tokens=DEFAULT_MAX_TOKENS,
            max_pixels=MAX_PIXELS,
            output_dir=os.path.join(_REPO_ROOT, "output"),
        )
    return _parser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _save_upload(upload: UploadFile, suffix: str) -> str:
    """Save uploaded file to a temp path, return the path."""
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    content = upload.file.read()
    tmp.write(content)
    tmp.close()
    return tmp.name


def _build_page_results(
    raw_results: list,
    output_format: str,
    field_mapping_path: Optional[str],
) -> list[PageResult]:
    """Convert raw parser output into ``PageResult`` objects."""
    pages: list[PageResult] = []

    for res in raw_results:
        page_no = res.get("page_no", 0)
        sheet_name = res.get("sheet_name")

        # Load cells_data from the layout JSON file
        layout_path = res.get("layout_info_path", "")
        cells_data = []
        if layout_path and os.path.isfile(layout_path):
            with open(layout_path, "r", encoding="utf-8") as f:
                cells_data = json.load(f)

        if output_format == "raw":
            # Return cells_data as-is (one "table" per table cell)
            tables = [
                TableResult(
                    table_index=i,
                    headers=[],
                    rows=[{"category": c.get("category"), "text": c.get("text"), "bbox": c.get("bbox")}],
                    raw_html=c.get("text", "") if c.get("category") == "Table" else "",
                )
                for i, c in enumerate(cells_data)
            ]
        elif output_format == "markdown":
            md_path = res.get("md_content_path", "")
            md_text = ""
            if md_path and os.path.isfile(md_path):
                with open(md_path, "r", encoding="utf-8") as f:
                    md_text = f.read()
            tables = [TableResult(table_index=0, headers=[], rows=[{"markdown": md_text}], raw_html="")]
        else:
            # structured (default): extract & map tables
            tables_data = extract_tables_from_cells(cells_data, field_mapping_path)
            tables = [
                TableResult(
                    table_index=t["table_index"],
                    headers=t["headers"],
                    rows=t["rows"],
                    raw_html=t["raw_html"],
                )
                for t in tables_data
            ]

        pages.append(PageResult(page=page_no, sheet_name=sheet_name, tables=tables))

    return pages


def _resolve_field_mapping(name: Optional[str]) -> Optional[str]:
    """Resolve a mapping filename to an absolute path."""
    if not name:
        return None  # will use default
    candidate = os.path.join(_REPO_ROOT, "field_mappings", name)
    if os.path.isfile(candidate):
        return candidate
    # If they passed a bare name without .yaml, try appending
    if not candidate.endswith((".yaml", ".yml")):
        for ext in (".yaml", ".yml"):
            c = candidate + ext
            if os.path.isfile(c):
                return c
    return None  # fall back to default


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check — reports model status."""
    parser = _get_parser()
    return HealthResponse(
        status="healthy",
        model_loaded=hasattr(parser, "hf_model") and parser.hf_model is not None,
        backend=parser.backend,
        model_file=os.path.basename(parser.model_path) if parser.model_path else "",
        device=parser.device,
        max_pixels=parser.max_pixels or MAX_PIXELS,
        version="1.0.0",
    )


@app.post("/parse", response_model=ParseResponse)
async def parse_sync(
    file: UploadFile = File(...),
    max_pixels: int = Form(default=MAX_PIXELS),
    dpi: int = Form(default=DEFAULT_DPI),
    max_completion_tokens: int = Form(default=DEFAULT_MAX_TOKENS),
    prompt_mode: str = Form(default="prompt_layout_all_en"),
    tables_only: bool = Form(default=True),
    output_format: str = Form(default="structured"),
    field_mapping: Optional[str] = Form(default=None),
):
    """Synchronous parse — blocks until done."""
    # Validate extension
    _, ext = os.path.splitext(file.filename or "")
    ext = ext.lower()
    if ext not in _SUPPORTED_EXTS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type: {ext}. Supported: {sorted(_SUPPORTED_EXTS)}",
        )

    # Save to temp file
    tmp_path = _save_upload(file, suffix=ext)

    try:
        parser = _get_parser()
        # Override per-request settings
        parser.max_pixels = max_pixels
        parser.dpi = dpi
        parser.max_completion_tokens = max_completion_tokens
        parser.tables_only = tables_only

        t0 = time.time()
        raw_results = parser.parse_file(
            input_path=tmp_path,
            prompt_mode=prompt_mode,
        )
        elapsed = round(time.time() - t0, 2)

        mapping_path = _resolve_field_mapping(field_mapping)
        pages = _build_page_results(raw_results, output_format, mapping_path)

        return ParseResponse(
            status="success",
            file_name=file.filename or "",
            file_type=ext.lstrip("."),
            pages=len(pages),
            processing_time_seconds=elapsed,
            data=pages,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if os.path.isfile(tmp_path):
            os.unlink(tmp_path)


@app.post("/parse/async", response_model=AsyncAcceptedResponse)
async def parse_async(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    max_pixels: int = Form(default=MAX_PIXELS),
    dpi: int = Form(default=DEFAULT_DPI),
    max_completion_tokens: int = Form(default=DEFAULT_MAX_TOKENS),
    prompt_mode: str = Form(default="prompt_layout_all_en"),
    tables_only: bool = Form(default=True),
    output_format: str = Form(default="structured"),
    field_mapping: Optional[str] = Form(default=None),
):
    """Asynchronous parse — returns immediately with a job ID."""
    _, ext = os.path.splitext(file.filename or "")
    ext = ext.lower()
    if ext not in _SUPPORTED_EXTS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported file type: {ext}. Supported: {sorted(_SUPPORTED_EXTS)}",
        )

    tmp_path = _save_upload(file, suffix=ext)

    # Estimate page count (rough: 1 for image/Excel, unknown for PDF)
    est_pages = 1
    if ext == ".pdf":
        try:
            import fitz
            doc = fitz.open(tmp_path)
            est_pages = doc.page_count
            doc.close()
        except Exception:
            est_pages = 1

    job = job_queue.create_job(file_name=file.filename or "", total_pages=est_pages)
    est_seconds = est_pages * 20.0  # rough estimate: 20s per page

    # Run parsing in background thread
    background_tasks.add_task(
        _run_async_job,
        job_id=job.job_id,
        tmp_path=tmp_path,
        prompt_mode=prompt_mode,
        max_pixels=max_pixels,
        dpi=dpi,
        max_completion_tokens=max_completion_tokens,
        tables_only=tables_only,
        output_format=output_format,
        field_mapping=field_mapping,
    )

    return AsyncAcceptedResponse(
        status="accepted",
        job_id=job.job_id,
        message=f"Processing {est_pages} page(s). Poll GET /result/{job.job_id} for results.",
        estimated_seconds=est_seconds,
    )


def _run_async_job(
    job_id: str,
    tmp_path: str,
    prompt_mode: str,
    max_pixels: int,
    dpi: int,
    max_completion_tokens: int,
    tables_only: bool,
    output_format: str,
    field_mapping: Optional[str],
) -> None:
    """Background worker for async parsing."""
    job_queue.mark_started(job_id)
    try:
        parser = _get_parser()
        parser.max_pixels = max_pixels
        parser.dpi = dpi
        parser.max_completion_tokens = max_completion_tokens
        parser.tables_only = tables_only

        raw_results = parser.parse_file(input_path=tmp_path, prompt_mode=prompt_mode)

        mapping_path = _resolve_field_mapping(field_mapping)
        pages = _build_page_results(raw_results, output_format, mapping_path)

        response = ParseResponse(
            status="success",
            file_name=job_queue.get_job(job_id).file_name if job_queue.get_job(job_id) else "",
            file_type=os.path.splitext(tmp_path)[1].lstrip("."),
            pages=len(pages),
            processing_time_seconds=0,  # filled on retrieval
            data=pages,
        )
        job_queue.mark_completed(job_id, response.model_dump())
    except Exception as e:
        traceback.print_exc()
        job_queue.mark_failed(job_id, str(e))
    finally:
        if os.path.isfile(tmp_path):
            os.unlink(tmp_path)


@app.get("/result/{job_id}", response_model=JobStatusResponse)
async def get_result(job_id: str):
    """Poll for async job results."""
    job = job_queue.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job ID not found: {job_id}")

    if job.status == JobStatus.COMPLETED:
        result = job.result or {}
        return JobStatusResponse(
            status="completed",
            job_id=job_id,
            file_name=job.file_name,
            pages=result.get("pages", 0),
            processing_time_seconds=job.processing_time,
            progress=job.progress,
            data=[PageResult(**p) for p in result.get("data", [])],
        )
    elif job.status == JobStatus.FAILED:
        return JobStatusResponse(
            status="failed",
            job_id=job_id,
            file_name=job.file_name,
            processing_time_seconds=job.processing_time,
            progress=job.progress,
            error=job.error,
        )
    else:
        return JobStatusResponse(
            status=job.status.value,
            job_id=job_id,
            file_name=job.file_name,
            progress=job.progress,
            estimated_remaining_seconds=job.estimated_remaining,
        )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main():
    """CLI entry point: ``python -m api.app``."""
    import uvicorn

    host = os.getenv("DOTS_HOST", "127.0.0.1")
    port = int(os.getenv("DOTS_PORT", "8080"))
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
