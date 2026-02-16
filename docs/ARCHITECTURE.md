# System Architecture

## Overview

A three-layer offline system that converts OEM vehicle pricelists into structured JSON via a REST API.

```
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI Server                           │
│                                                                 │
│  POST /parse ──► Ingestion ──► Inference ──► Extraction ──► JSON│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Component Diagram

```
                    ┌──────────────┐
                    │  REST Client │
                    └──────┬───────┘
                           │ HTTP POST (file upload)
                           ▼
                 ┌─────────────────────┐
                 │     api/app.py      │
                 │     (FastAPI)       │
                 │                     │
                 │  ┌───────────────┐  │
                 │  │  Job Queue    │  │  ← async jobs for multi-page PDFs
                 │  │  (in-memory)  │  │
                 │  └───────┬───────┘  │
                 └──────────┼──────────┘
                            │
              ┌─────────────┼─────────────┐
              ▼             ▼             ▼
     ┌──────────────┐ ┌──────────┐ ┌───────────┐
     │ Excel Reader │ │ PDF/Image│ │ Image     │
     │ excel_utils  │ │ doc_utils│ │ img_utils │
     │ (openpyxl)   │ │ (PyMuPDF)│ │ (PIL)     │
     └──────┬───────┘ └────┬─────┘ └─────┬─────┘
            │              │             │
            │              ▼             │
            │    ┌───────────────────┐   │
            │    │  DotsOCRParser    │◄──┘
            │    │  (parser.py)      │
            │    │                   │
            │    │  Backend:         │
            │    │  ├─ GGUF (INT4)  │  ← primary (fastest)
            │    │  ├─ HF (CPU)     │  ← fallback / debug
            │    │  └─ vLLM (GPU)   │  ← future GPU deployment
            │    └────────┬─────────┘
            │             │
            │             ▼ cells_data JSON
            │    ┌───────────────────┐
            └───►│ Table Extractor   │
                 │ table_extractor.py│
                 │                   │
                 │ • pandas.read_html│
                 │ • field mapping   │
                 │ • schema mapping  │
                 └────────┬──────────┘
                          │
                          ▼
                 ┌───────────────────┐
                 │ Pricelist Schema  │
                 │ (Pydantic model)  │
                 │                   │
                 │ → JSON response   │
                 └───────────────────┘
```

---

## Data Flow

### PDF / Image Input

```
PDF file
  │
  ├─► PyMuPDF renders each page at 150 DPI → PIL Image
  │
  ▼
PIL Image (clamped to max_pixels=1M)
  │
  ├─► GGUF backend: image → base64 → llama.cpp inference
  │   OR
  ├─► HF backend:   image → processor → model.generate()
  │
  ▼
Raw model output (JSON string)
  │
  ├─► post_process_output() → cells_data list
  │     [{ "bbox": [x1,y1,x2,y2], "category": "Table", "text": "<table>...</table>" }, ...]
  │
  ├─► filter tables_only (if flag set)
  │
  ├─► Table Extractor: HTML → pandas DataFrame → field mapping
  │
  ▼
Pricelist schema JSON response
```

### Excel Input

```
Excel file (.xlsx / .xls)
  │
  ├─► openpyxl reads all sheets
  │   ├─► handles merged cells
  │   ├─► converts each sheet → HTML table string
  │
  ├─► Table Extractor: HTML → pandas DataFrame → field mapping
  │     (bypasses dots.ocr entirely — no model inference needed)
  │
  ▼
Pricelist schema JSON response (instant, <1 second)
```

---

## File Structure (after implementation)

```
dots.ocr/
├── api/
│   ├── app.py                    # FastAPI application
│   ├── schemas.py                # Request/response Pydantic models
│   └── job_queue.py              # In-memory async job management
│
├── dots_ocr/
│   ├── __init__.py
│   ├── parser.py                 # DotsOCRParser (MODIFIED: CPU support, backend selection)
│   │
│   ├── model/
│   │   ├── inference.py          # vLLM backend (existing)
│   │   └── inference_gguf.py     # GGUF/llama.cpp backend (NEW)
│   │
│   └── utils/
│       ├── __init__.py
│       ├── consts.py             # (MODIFIED: lower defaults, configurable)
│       ├── doc_utils.py          # PDF → images (existing)
│       ├── excel_utils.py        # Excel → HTML tables (NEW)
│       ├── format_transformer.py # Layout JSON → Markdown (existing)
│       ├── image_utils.py        # Image loading/resizing (existing)
│       ├── layout_utils.py       # Post-processing (existing)
│       ├── output_cleaner.py     # JSON error recovery (existing)
│       ├── prompts.py            # Prompt templates (existing)
│       ├── table_extractor.py    # HTML tables → structured data (NEW)
│       └── demo_utils/
│           └── display.py
│
├── schemas/
│   └── pricelist.py              # Vehicle pricelist Pydantic schema (NEW)
│
├── scripts/
│   ├── convert_to_gguf.py        # HF → GGUF INT4 conversion (NEW)
│   ├── setup_offline.ps1         # Windows offline setup (NEW)
│   ├── setup_offline.sh          # Linux offline setup (NEW)
│   └── validate_accuracy.py      # Accuracy comparison harness (NEW)
│
├── field_mappings/
│   └── default.yaml              # Column header → schema field rules (NEW)
│
├── docs/
│   ├── PLAN.md                   # This project plan
│   ├── ARCHITECTURE.md           # System architecture (this file)
│   └── API_SPEC.md               # API endpoint specification
│
├── docker/                       # (existing, untouched in Phase 1)
├── demo/                         # (existing, untouched in Phase 1)
├── tools/                        # (existing)
├── weights/                      # Model weights (gitignored)
│   ├── DotsOCR/                  # HF checkpoint (existing)
│   ├── DotsOCR-Q4_K_M.gguf      # INT4 GGUF model (generated)
│   └── mmproj-DotsOCR.gguf      # Vision projector GGUF (generated)
│
├── .env                          # HF_HUB_OFFLINE=1, etc. (generated by setup)
├── requirements.txt              # (MODIFIED: add new deps)
├── setup.py                      # (MODIFIED: fix comment parsing)
├── LICENSE
└── README.md
```

---

## Inference Backends

### GGUF Backend (Primary — Phase 1)

```
DotsOCRParser(backend="gguf")
  │
  └─► inference_gguf.py
        │
        ├─► loads DotsOCR-Q4_K_M.gguf + mmproj-DotsOCR.gguf
        │   via llama-cpp-python (llama_cpp.Llama)
        │
        ├─► image → base64 → chat completion
        │
        └─► returns raw text response
```

- **Speed:** ~15–30 s/page on CPU (INT4)
- **RAM:** ~2 GB
- **Disk:** ~0.85 GB model file
- **Accuracy:** ~99% of FP16 baseline

### HF Backend (Fallback / Debug)

```
DotsOCRParser(backend="hf", device="cpu")
  │
  └─► _inference_with_hf()
        │
        ├─► loads from ./weights/DotsOCR via AutoModelForCausalLM
        │   attn_implementation="sdpa", torch_dtype=float32, device_map="cpu"
        │
        └─► returns raw text response
```

- **Speed:** ~5–10 min/page on CPU (FP32)
- **RAM:** ~7 GB
- **Disk:** ~6.8 GB model
- **Accuracy:** baseline (100%)

### vLLM Backend (GPU deployment, existing)

```
DotsOCRParser(backend="vllm", ip="localhost", port=8000)
  │
  └─► inference_with_vllm() (existing, unchanged)
```

- **Speed:** ~2–5 s/page on GPU
- **For:** GPU-equipped servers, not laptops

---

## Offline Guarantees

| Component | Network Behavior | Offline Safeguard |
|---|---|---|
| Model loading (HF) | `transformers` may check HuggingFace Hub | `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` in `.env` |
| Model loading (GGUF) | `llama-cpp-python` loads local file only | No safeguard needed |
| Image loading | `fetch_image()` supports HTTP URLs | Only pass local file paths; no URL input in API |
| pip packages | `huggingface_hub`, `modelscope` may phone home | Pre-installed during setup; never imported at inference time |
| FastAPI server | Binds to `127.0.0.1` | No external network access |

---

## Configuration

All tunable parameters, with defaults optimized for vehicle pricelists:

| Parameter | Default | Range | Impact |
|---|---|---|---|
| `max_pixels` | 1,000,000 | 250K – 11.3M | Vision tokens: higher = more accurate, slower |
| `dpi` | 150 | 72 – 300 | PDF rendering: higher = more pixels, slower |
| `max_completion_tokens` | 4,096 | 1K – 32K | Output cap: higher = more content, slower |
| `prompt_mode` | `prompt_layout_all_en` | 4 modes | Task type |
| `tables_only` | `true` | bool | Filter non-table elements from output |
| `backend` | `gguf` | gguf / hf / vllm | Inference engine |
| `device` | `cpu` | cpu / cuda | Hardware target (HF backend only) |
