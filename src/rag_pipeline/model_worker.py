"""Private JSON-lines worker for llama.cpp and Hugging Face operations."""

import json
import os
import sys
import threading
import traceback
from pathlib import Path
from typing import Any

from documents import prepare
from embedding import EMBEDDER

try:
    from llama_cpp import Llama
    from llama_cpp import llama_cpp
except ImportError:
    Llama = None
    llama_cpp = None


def clean_text(value: object) -> str:
    """Replace invalid lone UTF-16 surrogate code points with U+FFFD."""
    return "".join(
        "\ufffd" if 0xD800 <= ord(character) <= 0xDFFF else character
        for character in str(value)
    )


def clean_value(value: object) -> object:
    """Recursively sanitize strings before UTF-8 encoding or model use."""
    if isinstance(value, str):
        return clean_text(value)
    if isinstance(value, list):
        return [clean_value(item) for item in value]
    if isinstance(value, tuple):
        return [clean_value(item) for item in value]
    if isinstance(value, dict):
        return {clean_text(key): clean_value(item) for key, item in value.items()}
    return value


class LlamaRunner:
    """Load and reuse one GGUF model at a time."""

    def __init__(self) -> None:
        self._model: Any = None
        self._path: Path | None = None
        self._lock = threading.Lock()

    def status(self) -> dict[str, object]:
        return {
            "llama_cpp_available": Llama is not None,
            "gpu_offload_supported": self._gpu_offload_supported(),
            "configured_gpu_layers": int(
                os.getenv("LLAMA_N_GPU_LAYERS", "-1")
            ),
            "loaded_model": str(self._path) if self._path is not None else None,
        }

    def _gpu_offload_supported(self) -> bool:
        if llama_cpp is None:
            return False
        checker = getattr(llama_cpp, "llama_supports_gpu_offload", None)
        if not callable(checker):
            return False
        try:
            return bool(checker())
        except Exception:
            return False

    def _close_model(self) -> None:
        if self._model is None:
            return
        close = getattr(self._model, "close", None)
        if callable(close):
            close()
        self._model = None
        self._path = None

    def _load(self, path_value: str) -> Any:
        path = Path(path_value).resolve()
        if not path.is_file() or path.suffix.lower() != ".gguf":
            raise ValueError(f"GGUF model was not found: {path}")
        if Llama is None or llama_cpp is None:
            raise RuntimeError("llama-cpp-python is not installed")

        gpu_layers = int(os.getenv("LLAMA_N_GPU_LAYERS", "-1"))
        if gpu_layers == 0:
            raise RuntimeError(
                "GPU offloading is disabled because LLAMA_N_GPU_LAYERS is 0."
            )
        if not self._gpu_offload_supported():
            raise RuntimeError(
                "The installed llama-cpp-python build does not support GPU "
                "offloading. Install a CUDA-enabled build."
            )

        if self._model is None or self._path != path:
            self._close_model()
            print(
                f"Loading {path.name} with {gpu_layers} GPU layers.",
                file=sys.stderr,
                flush=True,
            )
            self._model = Llama(
                model_path=str(path),
                n_ctx=int(os.getenv("LLAMA_N_CTX", "2048")),
                n_batch=int(os.getenv("LLAMA_N_BATCH", "256")),
                n_ubatch=int(os.getenv("LLAMA_N_UBATCH", "128")),
                n_threads=int(
                    os.getenv(
                        "LLAMA_N_THREADS",
                        str(max(1, (os.cpu_count() or 2) // 2)),
                    )
                ),
                n_gpu_layers=gpu_layers,
                main_gpu=int(os.getenv("LLAMA_MAIN_GPU", "0")),
                offload_kqv=True,
                use_mmap=True,
                use_mlock=False,
                verbose=os.getenv("LLAMA_VERBOSE", "true").lower() == "true",
            )
            self._path = path
        return self._model

    def generate(
        self,
        model_path: str,
        messages: list[dict[str, str]],
        max_tokens: int,
        temperature: float,
    ) -> str:
        with self._lock:
            model = self._load(clean_text(model_path))
            safe_messages = clean_value(messages)
            if not isinstance(safe_messages, list):
                raise ValueError("Model messages must be a list")
            try:
                result = model.create_chat_completion(
                    messages=safe_messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
                return clean_text(result["choices"][0]["message"]["content"] or "").strip()
            except Exception:
                prompt = "\n\n".join(
                    f"{message['role'].title()}: {message['content']}"
                    for message in safe_messages
                ) + "\n\nAssistant:"
                result = model(
                    prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    echo=False,
                    stop=["</s>", "<end_of_turn>", "\nUser:"],
                )
                return clean_text(result["choices"][0]["text"] or "").strip()


LLAMA = LlamaRunner()


def handle(request: dict[str, object]) -> object:
    action = request.get("action")
    if not isinstance(action, str) or not action:
        raise ValueError("Worker action is required")
    if action == "status":
        return {**LLAMA.status(), "embedding": EMBEDDER.status()}
    if action == "embed":
        vectors = EMBEDDER.encode(
            clean_value(request.get("texts") or []),
            query=bool(request.get("query")),
        )
        return {
            "vectors": vectors,
            "embedding_model": EMBEDDER.model_name,
            "embedding_dimension": len(vectors[0]) if vectors else 0,
        }
    if action == "prepare_document":
        return prepare(clean_text(request["path"]))
    if action == "generate":
        return {
            "text": LLAMA.generate(
                clean_text(request["model_path"]),
                clean_value(request.get("messages") or []),
                int(request.get("max_tokens") or 256),
                float(0.7 if request.get("temperature") is None else request["temperature"]),
            )
        }
    raise ValueError(f"Unknown worker action: {action}")


def main() -> None:
    if hasattr(sys.stdin, "reconfigure"):
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
        sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

    for line in sys.stdin:
        request_id = None
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("Worker request must be a JSON object")
            request_id = request.get("id")
            response = {
                "id": request_id,
                "ok": True,
                "result": clean_value(handle(request)),
            }
        except Exception as error:
            traceback.print_exc(file=sys.stderr)
            response = {
                "id": request_id,
                "ok": False,
                "error": clean_text(error),
            }
        print(
            json.dumps(response, ensure_ascii=True, separators=(",", ":")),
            flush=True,
        )


if __name__ == "__main__":
    main()