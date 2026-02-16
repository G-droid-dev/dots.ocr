"""
Convert a HuggingFace dots.ocr model checkpoint to GGUF INT4 (Q4_K_M) format.

Prerequisites
-------------
- llama.cpp cloned and built (cmake + make) with ``convert_hf_to_gguf.py``
  available.
- Python packages: ``transformers``, ``torch`` (CPU is fine).

Usage
-----
    python scripts/convert_to_gguf.py \
        --hf-model ./weights/DotsOCR \
        --llama-cpp-dir ../llama.cpp \
        --output ./weights/DotsOCR-Q4_K_M.gguf \
        --quant Q4_K_M
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description="Convert DotsOCR HF model → GGUF")

    parser.add_argument(
        "--hf-model",
        default="./weights/DotsOCR",
        help="Path to the HuggingFace model directory",
    )
    parser.add_argument(
        "--llama-cpp-dir",
        default=None,
        help="Path to a cloned llama.cpp repository (must contain convert_hf_to_gguf.py)",
    )
    parser.add_argument(
        "--output",
        default="./weights/DotsOCR-Q4_K_M.gguf",
        help="Output path for the quantised GGUF file",
    )
    parser.add_argument(
        "--quant",
        default="Q4_K_M",
        choices=["Q4_0", "Q4_K_M", "Q4_K_S", "Q5_K_M", "Q8_0", "F16"],
        help="Quantisation type (default: Q4_K_M)",
    )

    args = parser.parse_args()
    hf_model = os.path.abspath(args.hf_model)
    output = os.path.abspath(args.output)

    if not os.path.isdir(hf_model):
        print(f"ERROR: HF model directory not found: {hf_model}")
        sys.exit(1)

    # Step 1: Convert HF → FP16 GGUF
    fp16_path = output.replace(".gguf", "-f16.gguf")
    print(f"\n[1/2] Converting HF → FP16 GGUF ...")
    print(f"      Source:  {hf_model}")
    print(f"      Target:  {fp16_path}")

    convert_script = _find_convert_script(args.llama_cpp_dir)
    if convert_script is None:
        print(
            "\nERROR: Could not find convert_hf_to_gguf.py.\n"
            "Please clone llama.cpp and pass --llama-cpp-dir:\n"
            "  git clone https://github.com/ggerganov/llama.cpp\n"
        )
        sys.exit(1)

    cmd_convert = [
        sys.executable, convert_script,
        hf_model,
        "--outfile", fp16_path,
        "--outtype", "f16",
    ]
    _run(cmd_convert)

    # Step 2: Quantise FP16 → INT4
    if args.quant == "F16":
        print(f"\nQuantisation type is F16 — skipping quantisation step.")
        if fp16_path != output:
            os.rename(fp16_path, output)
    else:
        print(f"\n[2/2] Quantising FP16 → {args.quant} ...")
        quantize_bin = _find_quantize_binary(args.llama_cpp_dir)
        if quantize_bin is None:
            print(
                "\nERROR: Could not find llama-quantize binary.\n"
                "Build llama.cpp first:\n"
                "  cd llama.cpp && cmake -B build && cmake --build build --config Release\n"
            )
            sys.exit(1)

        cmd_quant = [quantize_bin, fp16_path, output, args.quant]
        _run(cmd_quant)

        # Clean up intermediate FP16 file
        if os.path.isfile(fp16_path) and fp16_path != output:
            os.remove(fp16_path)
            print(f"Removed intermediate: {fp16_path}")

    print(f"\n✅ Done. GGUF model saved to: {output}")
    print(f"   Size: {os.path.getsize(output) / 1024**3:.2f} GB")


def _find_convert_script(llama_cpp_dir: str | None) -> str | None:
    """Locate convert_hf_to_gguf.py in llama.cpp."""
    candidates = []
    if llama_cpp_dir:
        candidates.append(os.path.join(llama_cpp_dir, "convert_hf_to_gguf.py"))
    # Also try common relative locations
    for rel in ["../llama.cpp", "../../llama.cpp", "llama.cpp"]:
        candidates.append(os.path.join(rel, "convert_hf_to_gguf.py"))

    for c in candidates:
        if os.path.isfile(c):
            return os.path.abspath(c)
    return None


def _find_quantize_binary(llama_cpp_dir: str | None) -> str | None:
    """Locate the llama-quantize binary."""
    names = ["llama-quantize", "llama-quantize.exe", "quantize", "quantize.exe"]
    dirs = []
    if llama_cpp_dir:
        dirs.extend([
            os.path.join(llama_cpp_dir, "build", "bin"),
            os.path.join(llama_cpp_dir, "build", "bin", "Release"),
            os.path.join(llama_cpp_dir, "build"),
            llama_cpp_dir,
        ])
    for rel in ["../llama.cpp", "../../llama.cpp", "llama.cpp"]:
        dirs.extend([
            os.path.join(rel, "build", "bin"),
            os.path.join(rel, "build", "bin", "Release"),
        ])

    for d in dirs:
        for name in names:
            candidate = os.path.join(d, name)
            if os.path.isfile(candidate):
                return os.path.abspath(candidate)
    return None


def _run(cmd: list) -> None:
    """Run a subprocess, streaming output."""
    print(f"  $ {' '.join(cmd)}")
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        print(f"\nCommand exited with code {result.returncode}")
        sys.exit(result.returncode)


if __name__ == "__main__":
    main()
