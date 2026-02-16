"""
GGUF / llama.cpp inference backend for dots.ocr.

This module wraps ``llama-cpp-python`` to run the INT4-quantised GGUF model
on CPU.  It provides an interface compatible with the HF backend so the
parser can switch between them transparently.

Phase 1 status: **placeholder** — the actual GGUF model file must first be
generated via ``scripts/convert_to_gguf.py``.
"""

from __future__ import annotations

import base64
import os
from io import BytesIO
from typing import Optional

from PIL import Image


class GGUFInference:
    """
    Loads a GGUF model + vision projector and runs chat-completion inference.

    Parameters
    ----------
    model_path : str
        Path to the main ``*.gguf`` file (e.g. ``weights/DotsOCR-Q4_K_M.gguf``).
    mmproj_path : str, optional
        Path to the multimodal projector GGUF file.
        If ``None``, looks for ``mmproj-DotsOCR.gguf`` next to *model_path*.
    n_ctx : int
        Context window (default 4096).
    n_threads : int
        CPU threads to use.
    """

    def __init__(
        self,
        model_path: str,
        mmproj_path: Optional[str] = None,
        n_ctx: int = 4096,
        n_threads: Optional[int] = None,
    ):
        self.model_path = model_path
        self.mmproj_path = mmproj_path or self._default_mmproj(model_path)
        self.n_ctx = n_ctx
        self.n_threads = n_threads or os.cpu_count() or 4

        self._model = None  # loaded lazily

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load the GGUF model into memory.  Call once at startup."""
        try:
            from llama_cpp import Llama
        except ImportError:
            raise ImportError(
                "llama-cpp-python is not installed.  "
                "Install it with: pip install llama-cpp-python"
            )

        if not os.path.isfile(self.model_path):
            raise FileNotFoundError(
                f"GGUF model not found at {self.model_path}.  "
                "Run scripts/convert_to_gguf.py first."
            )

        kwargs = {
            "model_path": self.model_path,
            "n_ctx": self.n_ctx,
            "n_threads": self.n_threads,
            "verbose": False,
        }

        if self.mmproj_path and os.path.isfile(self.mmproj_path):
            kwargs["chat_handler"] = self._build_chat_handler()

        self._model = Llama(**kwargs)

    def generate(
        self,
        prompt: str,
        image: Optional[Image.Image] = None,
        max_tokens: int = 4096,
        temperature: float = 0.1,
    ) -> str:
        """
        Run inference.

        Parameters
        ----------
        prompt : str
            The text prompt (system + user combined).
        image : PIL.Image, optional
            Input document image.
        max_tokens : int
            Maximum tokens to generate.
        temperature : float
            Sampling temperature.

        Returns
        -------
        str
            Raw model output text.
        """
        if self._model is None:
            self.load()

        messages = self._build_messages(prompt, image)

        response = self._model.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        return response["choices"][0]["message"]["content"]

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    @staticmethod
    def _default_mmproj(model_path: str) -> str:
        model_dir = os.path.dirname(model_path)
        return os.path.join(model_dir, "mmproj-DotsOCR.gguf")

    def _build_chat_handler(self):
        """Build a llama-cpp-python chat handler with multimodal support."""
        try:
            from llama_cpp.llama_chat_format import MoondreamChatHandler

            # MoondreamChatHandler works for vision models with a clip projector
            return MoondreamChatHandler(clip_model_path=self.mmproj_path)
        except (ImportError, Exception):
            # Fall back — handler may not exist in all versions
            return None

    @staticmethod
    def _build_messages(prompt: str, image: Optional[Image.Image] = None) -> list:
        """Build OpenAI-style chat messages with optional image."""
        content = []

        if image is not None:
            buf = BytesIO()
            image.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            })

        content.append({"type": "text", "text": prompt})

        return [{"role": "user", "content": content}]
