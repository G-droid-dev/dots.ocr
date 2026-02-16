"""
Accuracy validation harness.

Compares structured output from different backends / configurations against
a ground-truth JSONL file to quantify accuracy loss from quantisation,
pixel reduction, or other optimisations.

Usage
-----
    python scripts/validate_accuracy.py \
        --input ./test_data/ground_truth.jsonl \
        --backend hf \
        --device cpu
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List

# Ensure repo root on path
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def main():
    parser = argparse.ArgumentParser(description="Validate parsing accuracy")
    parser.add_argument("--input", required=True, help="Ground truth JSONL (one entry per file)")
    parser.add_argument("--backend", default="hf", choices=["hf", "gguf", "vllm"])
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--model-path", default=os.path.join(_REPO_ROOT, "weights", "DotsOCR"))
    parser.add_argument("--max-pixels", type=int, default=1_000_000)
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--output", default="./validation_report.json")
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"ERROR: Ground truth file not found: {args.input}")
        sys.exit(1)

    # Load ground truth
    ground_truth = _load_ground_truth(args.input)
    print(f"Loaded {len(ground_truth)} ground truth entries.\n")

    # Initialise parser
    from dots_ocr.parser import DotsOCRParser

    ocr = DotsOCRParser(
        backend=args.backend,
        device=args.device,
        model_path=args.model_path,
        max_pixels=args.max_pixels,
        dpi=args.dpi,
        tables_only=True,
    )

    results = []
    total_correct = 0
    total_fields = 0

    for i, entry in enumerate(ground_truth):
        file_path = entry.get("file")
        expected = entry.get("expected", {})

        if not file_path or not os.path.isfile(file_path):
            print(f"  [{i+1}] SKIP — file not found: {file_path}")
            continue

        print(f"  [{i+1}/{len(ground_truth)}] Parsing: {os.path.basename(file_path)} ...", end=" ", flush=True)
        t0 = time.time()

        try:
            raw = ocr.parse_file(input_path=file_path)
            elapsed = round(time.time() - t0, 2)
            print(f"{elapsed}s")
        except Exception as e:
            print(f"ERROR: {e}")
            results.append({"file": file_path, "error": str(e)})
            continue

        # Compare output against expected
        accuracy = _compare(raw, expected)
        total_correct += accuracy["correct"]
        total_fields += accuracy["total"]

        results.append({
            "file": file_path,
            "time_seconds": elapsed,
            "accuracy": accuracy,
        })

    # Summary
    overall = round(total_correct / total_fields * 100, 1) if total_fields > 0 else 0.0
    report = {
        "backend": args.backend,
        "device": args.device,
        "max_pixels": args.max_pixels,
        "dpi": args.dpi,
        "overall_accuracy_pct": overall,
        "total_correct": total_correct,
        "total_fields": total_fields,
        "files": results,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"\n{'='*50}")
    print(f"Overall accuracy: {overall}% ({total_correct}/{total_fields})")
    print(f"Report saved to: {args.output}")


def _load_ground_truth(path: str) -> List[Dict]:
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries


def _compare(raw_results: list, expected: dict) -> Dict[str, Any]:
    """
    Simple field-level comparison.

    *expected* is a dict of field→value pairs.  We check if the raw
    results contain text matching each expected value (case-insensitive
    substring match).
    """
    correct = 0
    total = len(expected)
    mismatches = []

    # Flatten all text from results
    all_text = ""
    for r in raw_results:
        layout_path = r.get("layout_info_path", "")
        if layout_path and os.path.isfile(layout_path):
            with open(layout_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for cell in data:
                    all_text += " " + str(cell.get("text", ""))

    all_text_lower = all_text.lower()

    for field, value in expected.items():
        if str(value).lower() in all_text_lower:
            correct += 1
        else:
            mismatches.append({"field": field, "expected": value})

    return {
        "correct": correct,
        "total": total,
        "pct": round(correct / total * 100, 1) if total > 0 else 100.0,
        "mismatches": mismatches,
    }


if __name__ == "__main__":
    main()
