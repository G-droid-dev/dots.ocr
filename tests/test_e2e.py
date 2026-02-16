"""
End-to-end test suite for the vehicle pricelist parsing system.

Tests are grouped by tier:
  Tier 1 — No model required (Excel parsing, API routing, schemas)
  Tier 2 — Requires model weights (PDF/image inference)

Run:  python -m pytest tests/test_e2e.py -v
      python -m pytest tests/test_e2e.py -v -k tier1    # model-free tests only
"""

import json
import os
import sys
import tempfile

import pytest

# Ensure repo root on sys.path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture(scope="session")
def sample_excel_path():
    """Create a sample Excel pricelist and return its path."""
    from tests.create_test_excel import create_sample_pricelist
    return create_sample_pricelist()


@pytest.fixture(scope="session")
def model_available():
    """Check if model weights are present."""
    weights_dir = os.path.join(_REPO_ROOT, "weights", "DotsOCR")
    return os.path.isdir(weights_dir) and os.path.isfile(
        os.path.join(weights_dir, "config.json")
    )


@pytest.fixture(scope="session")
def api_client():
    """FastAPI test client (no real server needed)."""
    from fastapi.testclient import TestClient
    from api.app import app
    return TestClient(app)


# ============================================================
# TIER 1 — No model required
# ============================================================

class TestTier1ExcelUtils:
    """Test Excel → HTML conversion."""

    def test_excel_to_html_tables(self, sample_excel_path):
        from dots_ocr.utils.excel_utils import excel_to_html_tables

        tables = excel_to_html_tables(sample_excel_path)
        assert len(tables) == 3, f"Expected 3 sheets, got {len(tables)}"

        sheet_names = [name for name, _ in tables]
        assert "Sedan Range" in sheet_names
        assert "SUV Range" in sheet_names
        assert "Preisliste DE" in sheet_names

    def test_html_contains_data(self, sample_excel_path):
        from dots_ocr.utils.excel_utils import excel_to_html_tables

        tables = excel_to_html_tables(sample_excel_path)
        sedan_html = tables[0][1]

        assert "<table>" in sedan_html
        assert "Corolla" in sedan_html
        assert "28950" in sedan_html

    def test_merged_cell_handling(self, sample_excel_path):
        from dots_ocr.utils.excel_utils import excel_to_html_tables

        tables = excel_to_html_tables(sample_excel_path)
        sedan_html = tables[0][1]

        # The title row has a merged cell spanning 6 columns
        assert 'colspan="6"' in sedan_html

    def test_file_not_found(self):
        from dots_ocr.utils.excel_utils import excel_to_html_tables

        with pytest.raises(FileNotFoundError):
            excel_to_html_tables("/nonexistent/file.xlsx")


class TestTier1TableExtractor:
    """Test HTML table → structured data extraction."""

    def test_extract_simple_table(self):
        from dots_ocr.utils.table_extractor import extract_tables_from_cells

        cells_data = [
            {
                "bbox": [0, 0, 100, 100],
                "category": "Table",
                "text": "<table><tr><th>Model</th><th>Price</th></tr>"
                        "<tr><td>Corolla</td><td>28950</td></tr></table>",
            }
        ]
        result = extract_tables_from_cells(cells_data)
        assert len(result) == 1
        assert result[0]["headers"] == ["Model", "Price"]
        assert len(result[0]["rows"]) == 1

    def test_field_mapping_applied(self):
        from dots_ocr.utils.table_extractor import extract_tables_from_cells

        cells_data = [
            {
                "bbox": [0, 0, 100, 100],
                "category": "Table",
                "text": "<table><tr><th>Model</th><th>Price</th><th>Engine</th></tr>"
                        "<tr><td>Camry</td><td>39900</td><td>2.5L Hybrid</td></tr></table>",
            }
        ]
        mapping_path = os.path.join(_REPO_ROOT, "field_mappings", "default.yaml")
        result = extract_tables_from_cells(cells_data, mapping_path)

        row = result[0]["rows"][0]
        # "Model" should map to "model" field
        assert "model" in row, f"Expected 'model' key, got: {list(row.keys())}"
        assert row["model"] == "Camry"

    def test_german_column_mapping(self):
        from dots_ocr.utils.table_extractor import extract_tables_from_cells

        cells_data = [
            {
                "bbox": [0, 0, 100, 100],
                "category": "Table",
                "text": "<table><tr><th>Modell</th><th>Preis</th><th>Getriebe</th></tr>"
                        "<tr><td>Corolla</td><td>29450</td><td>CVT</td></tr></table>",
            }
        ]
        mapping_path = os.path.join(_REPO_ROOT, "field_mappings", "default.yaml")
        result = extract_tables_from_cells(cells_data, mapping_path)

        row = result[0]["rows"][0]
        assert "model" in row
        assert "transmission" in row
        assert row["model"] == "Corolla"

    def test_non_table_cells_ignored(self):
        from dots_ocr.utils.table_extractor import extract_tables_from_cells

        cells_data = [
            {"bbox": [0, 0, 100, 100], "category": "Title", "text": "Price List 2026"},
            {"bbox": [0, 100, 100, 200], "category": "Paragraph", "text": "Some text."},
        ]
        result = extract_tables_from_cells(cells_data)
        assert len(result) == 0


class TestTier1Schemas:
    """Test Pydantic schemas."""

    def test_parse_response_serialisation(self):
        from schemas.pricelist import ParseResponse, PageResult, TableResult

        resp = ParseResponse(
            status="success",
            file_name="test.xlsx",
            file_type="xlsx",
            pages=1,
            processing_time_seconds=0.5,
            data=[
                PageResult(
                    page=0,
                    sheet_name="Sheet1",
                    tables=[
                        TableResult(
                            table_index=0,
                            headers=["Model", "Price"],
                            rows=[{"model": "Corolla", "price": 28950}],
                            raw_html="<table>...</table>",
                        )
                    ],
                )
            ],
        )
        d = resp.model_dump()
        assert d["status"] == "success"
        assert d["pages"] == 1
        assert len(d["data"]) == 1
        assert d["data"][0]["tables"][0]["rows"][0]["model"] == "Corolla"

    def test_vehicle_row_defaults(self):
        from schemas.pricelist import VehicleRow

        row = VehicleRow()
        assert row.make is None
        assert row.model is None
        assert row.extra == {}


class TestTier1JobQueue:
    """Test in-memory job queue."""

    def test_create_and_retrieve_job(self):
        from api.job_queue import JobQueue, JobStatus

        q = JobQueue()
        job = q.create_job("test.pdf", total_pages=5)
        assert job.status == JobStatus.QUEUED
        assert job.total_pages == 5

        fetched = q.get_job(job.job_id)
        assert fetched is not None
        assert fetched.job_id == job.job_id

    def test_job_lifecycle(self):
        from api.job_queue import JobQueue, JobStatus

        q = JobQueue()
        job = q.create_job("test.pdf", total_pages=3)

        q.mark_started(job.job_id)
        assert q.get_job(job.job_id).status == JobStatus.PROCESSING

        q.update_progress(job.job_id, 2)
        assert q.get_job(job.job_id).progress == "2/3"

        q.mark_completed(job.job_id, {"data": []})
        assert q.get_job(job.job_id).status == JobStatus.COMPLETED

    def test_missing_job_returns_none(self):
        from api.job_queue import JobQueue

        q = JobQueue()
        assert q.get_job("nonexistent") is None


class TestTier1API:
    """Test API endpoints that don't require model inference."""

    def test_health_endpoint(self, api_client):
        resp = api_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "backend" in data
        assert data["version"] == "1.0.0"

    def test_parse_unsupported_file_type(self, api_client):
        # Upload a .txt file — should get 422
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            f.write(b"not a real docx")
            f.flush()
            f.seek(0)
            resp = api_client.post(
                "/parse",
                files={"file": ("test.docx", open(f.name, "rb"), "application/octet-stream")},
            )
        os.unlink(f.name)
        assert resp.status_code == 422

    def test_parse_excel_via_api(self, api_client, sample_excel_path):
        with open(sample_excel_path, "rb") as f:
            resp = api_client.post(
                "/parse",
                files={"file": ("toyota_pricelist_2026.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
                data={"output_format": "structured"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["file_type"] == "xlsx"
        assert data["pages"] == 3  # 3 sheets

        # Check that structured extraction worked
        sedan_page = data["data"][0]
        assert len(sedan_page["tables"]) >= 1

    def test_parse_excel_raw_format(self, api_client, sample_excel_path):
        with open(sample_excel_path, "rb") as f:
            resp = api_client.post(
                "/parse",
                files={"file": ("toyota.xlsx", f, "application/octet-stream")},
                data={"output_format": "raw"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        # raw format should contain table HTML in cells
        raw_table = data["data"][0]["tables"][0]
        assert "raw_html" in raw_table

    def test_result_endpoint_404(self, api_client):
        resp = api_client.get("/result/nonexistent_job_id")
        assert resp.status_code == 404


# ============================================================
# TIER 2 — Requires model weights
# ============================================================

class TestTier2Inference:
    """Tests that require the DotsOCR model weights."""

    @pytest.fixture(autouse=True)
    def skip_if_no_model(self, model_available):
        if not model_available:
            pytest.skip("Model weights not available — skipping Tier 2 tests")

    def test_parse_sample_image(self, api_client):
        """Parse a simple test image through the API."""
        # Look for any sample image in assets/
        assets_dir = os.path.join(_REPO_ROOT, "assets")
        if not os.path.isdir(assets_dir):
            pytest.skip("No assets/ directory found")

        images = [f for f in os.listdir(assets_dir) if f.lower().endswith((".png", ".jpg", ".jpeg"))]
        if not images:
            pytest.skip("No sample images in assets/")

        img_path = os.path.join(assets_dir, images[0])
        with open(img_path, "rb") as f:
            resp = api_client.post(
                "/parse",
                files={"file": (images[0], f, "image/png")},
                data={"output_format": "raw", "tables_only": "false"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["pages"] == 1
        # Should have at least one cell in raw output
        assert len(data["data"][0]["tables"]) >= 1
