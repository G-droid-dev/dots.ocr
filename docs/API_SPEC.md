# API Specification

## Base URL

```
http://127.0.0.1:8080
```

---

## Endpoints

### `POST /parse`

Synchronous document parsing. Accepts a single file, returns structured pricelist data.

**Use for:** Single images, single-page PDFs, Excel files.
**For multi-page PDFs:** Use `/parse/async` instead.

#### Request

```
Content-Type: multipart/form-data
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `file` | file | **Yes** | — | PDF, image (.jpg/.jpeg/.png), or Excel (.xlsx/.xls) |
| `max_pixels` | integer | No | `1000000` | Max pixel budget for image resizing |
| `dpi` | integer | No | `150` | PDF rendering DPI |
| `max_completion_tokens` | integer | No | `4096` | Max output tokens from model |
| `prompt_mode` | string | No | `prompt_layout_all_en` | One of: `prompt_layout_all_en`, `prompt_layout_only_en`, `prompt_ocr`, `prompt_grounding_ocr` |
| `tables_only` | boolean | No | `true` | If true, return only table-category elements |
| `output_format` | string | No | `structured` | `structured` (schema-mapped JSON), `raw` (cells_data JSON), or `markdown` |

#### Response — `200 OK`

```json
{
  "status": "success",
  "file_name": "toyota_pricelist_2026.pdf",
  "file_type": "pdf",
  "pages": 1,
  "processing_time_seconds": 18.4,
  "data": [
    {
      "page": 1,
      "tables": [
        {
          "table_index": 0,
          "headers": ["Model", "Engine", "Transmission", "Price (EUR)"],
          "rows": [
            {
              "model": "Corolla",
              "engine": "1.8L Hybrid",
              "transmission": "CVT",
              "price": 28950,
              "currency": "EUR"
            }
          ],
          "raw_html": "<table>...</table>"
        }
      ],
      "metadata": {
        "title": "Toyota Price List 2026",
        "sections": ["Sedan Range", "SUV Range"],
        "footnotes": ["* Prices exclude VAT"]
      }
    }
  ]
}
```

#### Response — `422 Unprocessable Entity`

```json
{
  "status": "error",
  "detail": "Unsupported file type: .docx. Supported: .pdf, .jpg, .jpeg, .png, .xlsx, .xls"
}
```

---

### `POST /parse/async`

Asynchronous parsing for multi-page PDFs. Returns immediately with a job ID.

#### Request

Same as `POST /parse`.

#### Response — `202 Accepted`

```json
{
  "status": "accepted",
  "job_id": "a1b2c3d4",
  "message": "Processing 12 pages. Poll GET /result/a1b2c3d4 for results.",
  "estimated_seconds": 216
}
```

---

### `GET /result/{job_id}`

Poll for async job results.

#### Response — `200 OK` (completed)

```json
{
  "status": "completed",
  "job_id": "a1b2c3d4",
  "file_name": "honda_pricelist.pdf",
  "pages": 12,
  "processing_time_seconds": 198.3,
  "progress": "12/12",
  "data": [ ... ]
}
```

#### Response — `200 OK` (in progress)

```json
{
  "status": "processing",
  "job_id": "a1b2c3d4",
  "progress": "5/12",
  "estimated_remaining_seconds": 126
}
```

#### Response — `404 Not Found`

```json
{
  "status": "error",
  "detail": "Job ID not found: xyz123"
}
```

---

### `GET /health`

Health check endpoint.

#### Response — `200 OK`

```json
{
  "status": "healthy",
  "model_loaded": true,
  "backend": "gguf",
  "model_file": "DotsOCR-Q4_K_M.gguf",
  "device": "cpu",
  "max_pixels": 1000000,
  "version": "1.0.0"
}
```

---

## Output Schema — Vehicle Pricelist

The `structured` output format maps extracted table data into this schema:

```json
{
  "make": "string",
  "model": "string",
  "variant": "string | null",
  "trim": "string | null",
  "body_type": "string | null",
  "engine": {
    "displacement": "string | null",
    "fuel_type": "string | null",
    "power_hp": "number | null",
    "power_kw": "number | null",
    "description": "string | null"
  },
  "transmission": "string | null",
  "drivetrain": "string | null",
  "doors": "number | null",
  "seats": "number | null",
  "price": {
    "value": "number",
    "currency": "string",
    "includes_tax": "boolean | null",
    "tax_rate": "number | null"
  },
  "msrp": "number | null",
  "effective_date": "string (ISO 8601) | null",
  "country": "string (ISO 3166-1 alpha-2) | null",
  "options": [
    {
      "name": "string",
      "code": "string | null",
      "price": "number | null"
    }
  ],
  "source": {
    "file_name": "string",
    "page": "number",
    "table_index": "number"
  }
}
```

---

## Field Mapping Configuration

Table column headers are mapped to schema fields via `field_mappings/default.yaml`:

```yaml
# Column header patterns → schema field
# Patterns are case-insensitive regex

mappings:
  model:
    patterns: ["model", "modell", "modèle", "modelo", "車型"]
    schema_field: "model"

  variant:
    patterns: ["variant", "variante", "version", "ausstattung", "trim"]
    schema_field: "variant"

  engine:
    patterns: ["engine", "motor", "moteur", "エンジン", "displacement"]
    schema_field: "engine.description"

  price:
    patterns: ["price", "preis", "prix", "precio", "価格", "msrp", "rrp", "pvp"]
    schema_field: "price.value"

  currency:
    patterns: ["currency", "währung", "devise"]
    schema_field: "price.currency"
    # Auto-detected from price column format if not explicit

  transmission:
    patterns: ["transmission", "getriebe", "boîte", "cambio", "gearbox"]
    schema_field: "transmission"
```

Custom mappings can be added per OEM or country by creating additional YAML files and passing the filename in the API request.

---

## Error Codes

| HTTP Status | Meaning |
|---|---|
| `200` | Success |
| `202` | Accepted (async job created) |
| `400` | Bad request (missing file, invalid parameters) |
| `404` | Job ID not found |
| `413` | File too large |
| `422` | Unsupported file type |
| `500` | Internal server error (model failure) |
| `503` | Model not loaded / server starting up |
