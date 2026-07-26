import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:
    import mysql.connector
except ImportError:  # The API can still run without MySQL.
    mysql = None  # type: ignore[assignment]

try:
    from llama_cpp import Llama
except ImportError:  # Model discovery remains available without llama-cpp-python.
    Llama = None  # type: ignore[assignment,misc]


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODEL_DIRECTORY = Path(
    os.getenv("RAGDOLL_MODEL_DIR", str(PROJECT_ROOT / "models" / "models"))
).resolve()

DB_ENABLED = os.getenv("RAGDOLL_DB_ENABLED", "true").lower() not in {
    "0",
    "false",
    "no",
}
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "database": os.getenv("DB_NAME", "ragdoll_db"),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
}


def _relative_model_path(path: Path) -> str:
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def _scan_gguf_files() -> List[Path]:
    MODEL_DIRECTORY.mkdir(parents=True, exist_ok=True)
    return sorted(
        (
            path.resolve()
            for path in MODEL_DIRECTORY.iterdir()
            if path.is_file() and path.suffix.lower() == ".gguf"
        ),
        key=lambda path: path.name.lower(),
    )


class ModelDatabase:
    """Small MySQL adapter used only for local model metadata."""

    @contextmanager
    def connection(self) -> Iterator[Any]:
        if not DB_ENABLED:
            raise RuntimeError("MySQL integration is disabled by RAGDOLL_DB_ENABLED.")
        if mysql is None:
            raise RuntimeError("mysql-connector-python is not installed.")

        connection = mysql.connector.connect(**DB_CONFIG)
        try:
            yield connection
        finally:
            connection.close()

    def sync_discovered_models(
        self, files: List[Path]
    ) -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
        """Register new GGUF files and return metadata keyed by lower-case filename."""

        if not DB_ENABLED:
            return {}, "MySQL integration is disabled."

        try:
            with self.connection() as connection:
                cursor = connection.cursor(dictionary=True)
                cursor.execute(
                    """
                    SELECT model_id, model_name, model_type, model_path,
                           model_location, is_enabled
                    FROM Models
                    WHERE model_location = 'local'
                    """
                )
                rows = list(cursor.fetchall())

                next_model_id: Optional[int] = None
                changed = False

                for model_file in files:
                    filename_key = model_file.name.lower()
                    stem_key = model_file.stem.lower()
                    relative_path = _relative_model_path(model_file)

                    row = next(
                        (
                            existing
                            for existing in rows
                            if Path(str(existing.get("model_path") or "")).name.lower()
                            == filename_key
                            or str(existing.get("model_name") or "").lower() == stem_key
                        ),
                        None,
                    )

                    if row is None:
                        if next_model_id is None:
                            cursor.execute(
                                "SELECT COALESCE(MAX(model_id), 0) + 1 AS next_id FROM Models"
                            )
                            next_model_id = int(cursor.fetchone()["next_id"])

                        model_name = model_file.stem
                        cursor.execute(
                            """
                            INSERT INTO Models
                                (model_id, model_name, model_type, model_path,
                                 model_location, server_model_id, is_enabled)
                            VALUES (%s, %s, 'gguf', %s, 'local', '', 1)
                            """,
                            (next_model_id, model_name, relative_path),
                        )
                        row = {
                            "model_id": next_model_id,
                            "model_name": model_name,
                            "model_type": "gguf",
                            "model_path": relative_path,
                            "model_location": "local",
                            "is_enabled": 1,
                        }
                        rows.append(row)
                        next_model_id += 1
                        changed = True
                    elif (
                        str(row.get("model_path") or "") != relative_path
                        or str(row.get("model_type") or "").lower() != "gguf"
                    ):
                        cursor.execute(
                            """
                            UPDATE Models
                            SET model_path = %s,
                                model_type = 'gguf',
                                model_location = 'local'
                            WHERE model_id = %s
                            """,
                            (relative_path, row["model_id"]),
                        )
                        row["model_path"] = relative_path
                        row["model_type"] = "gguf"
                        changed = True

                if changed:
                    connection.commit()

                cursor.close()

                metadata: Dict[str, Dict[str, Any]] = {}
                for row in rows:
                    filename = Path(str(row.get("model_path") or "")).name.lower()
                    if filename:
                        metadata[filename] = row
                return metadata, None
        except Exception as error:
            return {}, str(error)


MODEL_DATABASE = ModelDatabase()


def discover_models() -> Tuple[List[Dict[str, Any]], Optional[str]]:
    files = _scan_gguf_files()
    database_rows, database_error = MODEL_DATABASE.sync_discovered_models(files)

    models: List[Dict[str, Any]] = []
    for path in files:
        row = database_rows.get(path.name.lower())

        # When MySQL is available, its enabled flag controls visibility.
        if row is not None and not bool(row.get("is_enabled", 1)):
            continue

        models.append(
            {
                "model_id": row.get("model_id") if row else None,
                "model_name": row.get("model_name") if row else path.stem,
                "file_name": path.name,
                "model_path": _relative_model_path(path),
                "absolute_path": str(path),
                "model_type": "gguf",
                "is_enabled": True,
                "database_registered": row is not None,
            }
        )

    return models, database_error


class QueryRequest(BaseModel):
    query_text: str = Field(min_length=1)
    model_id: Optional[int] = None
    model_file: Optional[str] = None
    model_name: Optional[str] = None
    system_prompt: Optional[str] = None
    max_tokens: int = Field(default=256, ge=1, le=4096)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


class LoadedModel:
    """Caches one model so selecting a different model releases the previous one."""

    def __init__(self) -> None:
        self._model_path: Optional[Path] = None
        self._model: Any = None
        self._load_lock = threading.Lock()
        self.inference_lock = threading.Lock()

    def get(self, model_path: Path) -> Any:
        if Llama is None:
            raise RuntimeError(
                "llama-cpp-python is not installed. Run install_dependencies.bat or: "
                "python -m pip install --user -r requirements.txt"
            )

        with self._load_lock:
            if self._model is not None and self._model_path == model_path:
                return self._model

            self._model = None
            self._model_path = None

            n_threads_default = max(1, (os.cpu_count() or 2) - 1)
            self._model = Llama(
                model_path=str(model_path),
                n_ctx=int(os.getenv("LLAMA_N_CTX", "4096")),
                n_threads=int(os.getenv("LLAMA_N_THREADS", str(n_threads_default))),
                n_gpu_layers=int(os.getenv("LLAMA_N_GPU_LAYERS", "0")),
                verbose=os.getenv("LLAMA_VERBOSE", "false").lower()
                in {"1", "true", "yes"},
            )
            self._model_path = model_path
            return self._model


LOADED_MODEL = LoadedModel()


def _resolve_model(request: QueryRequest) -> Dict[str, Any]:
    models, database_error = discover_models()
    if not models:
        detail = (
            f"No .gguf models were found in {MODEL_DIRECTORY}. "
            "Replace the gemma.txt placeholder with a real GGUF model file."
        )
        if database_error:
            detail += f" MySQL status: {database_error}"
        raise HTTPException(status_code=404, detail=detail)

    selected: Optional[Dict[str, Any]] = None
    if request.model_id is not None:
        selected = next(
            (model for model in models if model.get("model_id") == request.model_id),
            None,
        )
    if selected is None and request.model_file:
        selected = next(
            (
                model
                for model in models
                if model["file_name"].lower() == request.model_file.lower()
            ),
            None,
        )
    if selected is None and request.model_name:
        selected = next(
            (
                model
                for model in models
                if str(model["model_name"]).lower() == request.model_name.lower()
            ),
            None,
        )
    if (
        selected is None
        and request.model_id is None
        and not request.model_file
        and not request.model_name
    ):
        selected = models[0]

    if selected is None:
        raise HTTPException(status_code=404, detail="The selected GGUF model is unavailable.")
    return selected


def _generate_response(llm: Any, request: QueryRequest) -> str:
    messages: List[Dict[str, str]] = []
    if request.system_prompt:
        messages.append({"role": "system", "content": request.system_prompt})
    messages.append({"role": "user", "content": request.query_text})

    try:
        result = llm.create_chat_completion(
            messages=messages,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
        )
        content = result["choices"][0]["message"]["content"]
        return str(content or "").strip()
    except Exception as chat_error:
        # Some GGUF files do not include a usable chat template. A plain prompt
        # keeps those models queryable without model-specific hard-coding.
        prompt_parts = []
        if request.system_prompt:
            prompt_parts.append(f"System: {request.system_prompt}")
        prompt_parts.append(f"User: {request.query_text}")
        prompt_parts.append("Assistant:")
        prompt = "\n\n".join(prompt_parts)

        try:
            result = llm(
                prompt,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                echo=False,
                stop=["</s>", "<end_of_turn>", "\nUser:"],
            )
            return str(result["choices"][0]["text"] or "").strip()
        except Exception as completion_error:
            raise RuntimeError(
                f"Chat generation failed: {chat_error}; "
                f"plain completion also failed: {completion_error}"
            ) from completion_error


app = FastAPI(title="RAGdoll Local GGUF API", version="1.0")

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "RAGDOLL_ALLOWED_ORIGINS",
        "http://localhost:8080,http://127.0.0.1:8080",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
def health() -> Dict[str, Any]:
    models, database_error = discover_models()
    return {
        "status": "ok",
        "model_count": len(models),
        "llama_cpp_available": Llama is not None,
        "database_connected": database_error is None,
        "database_error": database_error,
    }


@app.get("/api/models")
def list_models() -> Dict[str, Any]:
    models, database_error = discover_models()
    public_models = [
        {key: value for key, value in model.items() if key != "absolute_path"}
        for model in models
    ]
    return {
        "models": public_models,
        "model_directory": str(MODEL_DIRECTORY),
        "database_connected": database_error is None,
        "database_error": database_error,
    }


@app.post("/api/query")
def query_model(request: QueryRequest) -> Dict[str, Any]:
    selected = _resolve_model(request)
    model_path = Path(selected["absolute_path"])

    try:
        llm = LOADED_MODEL.get(model_path)
        started_at = time.perf_counter()
        with LOADED_MODEL.inference_lock:
            response_text = _generate_response(llm, request)
        elapsed_seconds = round(time.perf_counter() - started_at, 3)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Model query failed: {error}") from error

    return {
        "response_text": response_text,
        "model_id": selected.get("model_id"),
        "model_name": selected["model_name"],
        "model_file": selected["file_name"],
        "elapsed_seconds": elapsed_seconds,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("RAGDOLL_API_HOST", "127.0.0.1"),
        port=int(os.getenv("RAGDOLL_API_PORT", "8000")),
    )