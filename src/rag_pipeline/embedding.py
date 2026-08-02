"""Local Sentence Transformer wrapper.

This module loads one locally configured text-embedding model at a time. It does
not assume a specific model name, directory name, or query instruction.
"""

import json
import os
import threading
from pathlib import Path
from typing import Any, Sequence

try:
    import torch
    from sentence_transformers import SentenceTransformer
except ImportError:
    torch = None
    SentenceTransformer = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_ROOT = Path(
    os.getenv(
        "RAGDOLL_EMBEDDING_MODEL_DIR",
        PROJECT_ROOT / "models" / "embedding",
    )
).resolve()
QUERY_PREFIX = os.getenv("RAGDOLL_EMBEDDING_QUERY_PREFIX", "")
DOCUMENT_PREFIX = os.getenv("RAGDOLL_EMBEDDING_DOCUMENT_PREFIX", "")


def clean_text(value: object) -> str:
    """Replace invalid lone surrogate code points before model tokenization."""
    return "".join(
        "\ufffd" if 0xD800 <= ord(character) <= 0xDFFF else character
        for character in str(value)
    )


def is_model_directory(path: Path) -> bool:
    """Recognize common local Sentence Transformer directory layouts."""
    return path.is_dir() and (
        (path / "modules.json").is_file()
        or (path / "config.json").is_file()
        or (path / "config_sentence_transformers.json").is_file()
    )


def read_model_name(path: Path) -> str:
    """Read a model identifier from local metadata when one is available."""
    config_files = (
        path / "config_sentence_transformers.json",
        path / "config.json",
        path / "0_Transformer" / "config.json",
    )
    for config_file in config_files:
        if not config_file.is_file():
            continue
        try:
            values = json.loads(config_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for key in ("model_name", "_name_or_path", "name_or_path"):
            value = str(values.get(key, "")).strip()
            if not value:
                continue
            candidate = Path(value)
            if candidate.is_absolute() or candidate.exists():
                return candidate.name or path.name
            return value
    return path.name or str(path)


def resolve_model_directory() -> Path:
    """Select one local embedding model without assuming a model name."""
    configured = os.getenv("RAGDOLL_EMBEDDING_MODEL_DIR", "").strip()
    if configured:
        return MODEL_ROOT

    if is_model_directory(MODEL_ROOT):
        return MODEL_ROOT

    if not MODEL_ROOT.is_dir():
        return MODEL_ROOT

    candidates = sorted(
        path.resolve()
        for path in MODEL_ROOT.iterdir()
        if is_model_directory(path)
    )
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise RuntimeError(
            "Multiple embedding models were found. Keep one model under "
            f"{MODEL_ROOT} or set RAGDOLL_EMBEDDING_MODEL_DIR."
        )
    return MODEL_ROOT


class Embedder:
    """Load one local Sentence Transformer and reuse it for every request."""

    def __init__(self) -> None:
        self._model: Any = None
        self._model_directory: Path | None = None
        self._lock = threading.Lock()

    @property
    def model_directory(self) -> Path:
        if self._model_directory is None:
            self._model_directory = resolve_model_directory()
        return self._model_directory

    @property
    def model_name(self) -> str:
        return read_model_name(self.model_directory)

    def _device(self) -> str:
        configured = os.getenv("RAGDOLL_EMBEDDING_DEVICE", "").strip()
        if configured:
            return configured
        return "cuda" if torch is not None and torch.cuda.is_available() else "cpu"

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            if SentenceTransformer is None:
                raise RuntimeError("sentence-transformers is not installed")
            if not is_model_directory(self.model_directory):
                raise RuntimeError(
                    "Sentence Transformer files were not found in "
                    f"{self.model_directory}"
                )
            self._model = SentenceTransformer(
                str(self.model_directory),
                device=self._device(),
                local_files_only=True,
            )
            return self._model

    def encode(self, texts: Sequence[str], query: bool = False) -> list[list[float]]:
        cleaned = [" ".join(clean_text(text).split()) for text in texts]
        if not cleaned or any(not text for text in cleaned):
            raise ValueError("Embedding text cannot be empty")

        prefix = QUERY_PREFIX if query else DOCUMENT_PREFIX
        if prefix:
            cleaned = [prefix + text for text in cleaned]

        vectors = self._load().encode(
            cleaned,
            batch_size=int(os.getenv("RAGDOLL_EMBEDDING_BATCH_SIZE", "16")),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.astype("float32").tolist()

    def status(self) -> dict[str, object]:
        directory = self.model_directory
        return {
            "model_name": self.model_name,
            "model_directory": str(directory),
            "directory_exists": directory.is_dir(),
            "model_files_present": is_model_directory(directory),
            "model_loaded": self._model is not None,
            "device": self._device(),
            "offline_only": True,
            "query_prefix_configured": bool(QUERY_PREFIX),
            "document_prefix_configured": bool(DOCUMENT_PREFIX),
        }


EMBEDDER = Embedder()