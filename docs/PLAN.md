# Vehicle Pricelist Parsing System — Project Plan

## Objective

Build an offline, CPU-only REST API that ingests OEM vehicle pricelists (PDF, Excel, images) and returns structured pricing data in a predefined JSON schema. Powered entirely by dots.ocr (1.7B VLM). No secondary LLM. Runs on Intel Core Ultra 7 laptops without internet.

---

## Phase 1 — Core System (Implementation)

### 1.1 Convert dots.ocr to GGUF INT4 via llama.cpp

**Goal:** 5–8× inference speedup over vanilla PyTorch FP16/FP32.

**What:** dots.ocr is architecturally identical to Qwen2.5-VL (it's a fine-tune). llama.cpp natively supports Qwen2.5-VL GGUF inference including the vision encoder.

**Deliverables:**
- `scripts/convert_to_gguf.py` — converts `./weights/DotsOCR` HF checkpoint to `DotsOCR-Q4_K_M.gguf` + `mmproj-DotsOCR.gguf` (vision projector).
- `dots_ocr/model/inference_gguf.py` — new inference backend using `llama-cpp-python` bindings (or llama.cpp HTTP server as a subprocess). Same input/output contract as existing `inference_with_vllm`.
- Update `DotsOCRParser.__init__` with a `backend` parameter: `"gguf"` (default), `"hf"`, or `"vllm"`.

**Risk:** The vision encoder (aimv2) may not convert cleanly. Mitigation: if GGUF conversion fails, fall back to INT8 dynamic quantization on the HF path (~2× speedup instead of 5–8×).

---

### 1.2 Reduce Visual Token Count

**Goal:** ~3–5× reduction in vision prefill cost.

**What:** Lower `MAX_PIXELS` from 11.3M → 1M and PDF `dpi` from 200 → 150. This reduces visual tokens from ~14,400 to ~1,276.

**Deliverables:**
- Modify `dots_ocr/utils/consts.py`:
  - `MAX_PIXELS` default: `11289600` → `1000000`
  - Add `DEFAULT_DPI = 150`
  - Add `DEFAULT_MAX_TOKENS = 4096`
- Make `max_pixels`, `dpi`, `max_completion_tokens` overridable per-request via API and CLI.
- Keep original constants available as `MAX_PIXELS_FULL = 11289600` for high-fidelity mode.

**Risk:** Small text (footnotes, fine print) may become unreadable at 1M pixels. Mitigated by the accuracy validation harness (step 1.6).

---

### 1.3 Cap Output Tokens + Table-Only Mode

**Goal:** ~1.5–2× reduction in decode time; cleaner output.

**What:**
- Default `max_completion_tokens`: `16384` → `4096` (sufficient for single-table pages).
- Add `tables_only` parameter to `_parse_single_image` — post-filters `cells_data` to keep only `category == "Table"` cells.
- Add `prompt_mode` routing: allow per-request prompt selection. For pure table pages, `prompt_ocr` generates fewer tokens.

**Deliverables:**
- Modified `dots_ocr/parser.py`: `_parse_single_image` gains `tables_only: bool = False` parameter.
- New utility in `dots_ocr/utils/table_extractor.py`: parses table HTML from cells_data using `pandas.read_html()` / BeautifulSoup into structured DataFrames.
- Configurable field-mapping rules (YAML) to map DataFrame columns → output schema fields.

---

### 1.4 Patch CPU Inference Path (HF Backend)

**Goal:** Make HuggingFace inference runnable on CPU (fallback/debugging backend).

**What:** Fix four hardcoded GPU assumptions in `dots_ocr/parser.py`:

| Current Code | Change To |
|---|---|
| `attn_implementation="flash_attention_2"` | `"sdpa"` |
| `torch_dtype=torch.bfloat16` | `torch.float32` |
| `device_map="auto"` | `"cpu"` |
| `inputs.to("cuda")` | `inputs.to("cpu")` |

**Deliverables:**
- Modified `_load_hf_model` and `_inference_with_hf` in `dots_ocr/parser.py`.
- Configurable `device` parameter in `DotsOCRParser.__init__`.
- Model path configurable (currently hardcoded to `"./weights/DotsOCR"`).

---

### 1.5 Build FastAPI REST API + Excel Ingestion

**Goal:** Production-ready REST interface for document parsing.

**Deliverables:**
- `api/app.py` — FastAPI application.
- `api/schemas.py` — Pydantic request/response models (see API_SPEC.md).
- `schemas/pricelist.py` — target output schema for vehicle pricing data.
- `dots_ocr/utils/excel_utils.py` — Excel reader using `openpyxl` (merged cells, multi-sheet).
- Extended `parse_file` in `dots_ocr/parser.py` to accept `.xlsx`/`.xls`.

**Endpoints:**
| Method | Path | Purpose |
|---|---|---|
| `POST` | `/parse` | Synchronous parse (single image or short PDF) |
| `POST` | `/parse/async` | Async parse (returns job_id for long PDFs) |
| `GET` | `/result/{job_id}` | Poll async result |
| `GET` | `/health` | Health check |

---

### 1.6 Accuracy Validation Harness

**Goal:** Ensure optimizations maintain ≥99% of baseline accuracy.

**Deliverables:**
- `scripts/validate_accuracy.py` — runs reference pages through baseline vs optimized pipelines.
- Compares table HTML output using edit distance and TEDS score.
- Sweeps `max_pixels` from 500K → 3M to find the accuracy/speed sweet spot.
- Outputs a report: per-page TEDS, average edit distance, pass/fail against 99% threshold.

---

### 1.7 Offline Setup Script

**Goal:** One-time internet-connected setup; production runs fully offline.

**Deliverables:**
- `scripts/setup_offline.ps1` (Windows) / `scripts/setup_offline.sh` (Linux).
- Downloads dots.ocr weights via `tools/download_model.py`.
- Runs GGUF conversion (step 1.1).
- Caches all pip packages locally.
- Writes `.env` file with `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`.
- Validates installation by running a test inference.

---

### 1.8 Fix Existing Bugs

**What:** Address issues found during codebase analysis.

| Bug | Fix |
|---|---|
| `setup.py` passes comment lines to `install_requires` | Filter lines starting with `#` in `parse_requirements()` |
| `torch` not in `requirements.txt` | Add `torch` (CPU) to requirements |
| `image_extensions` missing `.xlsx`/`.xls` | Add Excel extensions to supported set |
| `_load_hf_model` imports `AutoTokenizer` but never uses it | Remove unused import |

---

## Phase 1 — Expected Outcome

| Metric | Baseline | Phase 1 Target |
|---|---|---|
| Per-page latency (CPU) | 5–10 minutes | ~15–30 seconds |
| Model format | FP16/FP32 PyTorch | INT4 GGUF |
| Model size on disk | ~3.4 GB | ~0.85 GB |
| RAM usage | ~7 GB | ~2 GB |
| Max pixels per page | 11.3M | 1M (configurable) |
| PDF DPI | 200 | 150 (configurable) |
| Max output tokens | 16,384 | 4,096 (configurable) |
| Supported inputs | PDF, JPG, PNG | + Excel (.xlsx/.xls) |
| Interface | CLI / Gradio demo | REST API (FastAPI) |
| Network required | Yes (HF Hub checks) | No (fully offline) |
| Table accuracy (TEDS) | Baseline | ≥99% of baseline |

---

## Phase 2 — Post-Production Optimization (Deferred)

### 2.1 Intel-Specific Acceleration

- **IPEX (Intel Extension for PyTorch):** Drop-in `ipex.optimize(model)` for fused CPU kernels. ~1.3–1.5× additional speedup.
- **OpenVINO conversion:** Export model to ONNX → OpenVINO IR for best Intel CPU/NPU performance. ~2–4× additional speedup. High engineering effort; no community precedent for dots.ocr.
- **NPU offload:** Intel Core Ultra 7's AI Boost NPU for vision encoder offload. Experimental.

### 2.2 Structured Pruning (LTH-Informed)

- Remove redundant attention heads and FFN neurons using magnitude-based structured pruning.
- Requires GPU cluster for iterative pruning rounds + production calibration dataset.
- Target: reduce model to ~50–70% of original parameters → proportional decode speedup.
- Stacks with INT4 quantization for compound compression.
- Risk: accuracy degradation on complex tables; LTH validated only on small models.

### 2.3 Knowledge Distillation

- Distill dots.ocr (1.7B) into a 0.5B student model specialized for vehicle pricelist tables.
- Requires labeled training data from production usage.
- Target: 3–4× faster decode with ≥95% table accuracy.

### 2.4 Combined Phase 2 Target

| Metric | Phase 1 | Phase 2 Target |
|---|---|---|
| Per-page latency (CPU) | ~15–30 seconds | **<5 seconds** |
| Model size | ~0.85 GB (INT4) | ~0.3–0.5 GB (pruned + INT4) |

---

## Implementation Order

```
Week 1:  [1.4] Patch CPU inference path (unblocks all testing)
         [1.8] Fix existing bugs
         [1.2] Reduce visual tokens (constants + configurability)

Week 2:  [1.1] GGUF INT4 conversion (biggest speed win)
         [1.3] Table-only mode + output token cap

Week 3:  [1.5] FastAPI API + Excel ingestion + output schema
         [1.6] Accuracy validation harness

Week 4:  [1.7] Offline setup script
         Integration testing + tuning max_pixels sweet spot
```

---

## Dependencies

### Python Packages (additions to requirements.txt)
```
torch                    # CPU build, via --index-url https://download.pytorch.org/whl/cpu
llama-cpp-python         # GGUF inference backend
fastapi                  # REST API framework
uvicorn                  # ASGI server
python-multipart         # File upload support for FastAPI
openpyxl                 # Excel parsing
beautifulsoup4           # HTML table parsing
pandas                   # Table data manipulation
pydantic>=2.0            # Request/response schemas
python-dotenv            # .env file loading
```

### External Tools (setup-time only)
```
llama.cpp                # For GGUF conversion scripts (cloned during setup)
```
