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

MODEL_SYNC_LOCK = threading.Lock()
CONVERSATION_WRITE_LOCK = threading.Lock()
MAX_CONVERSATIONS = int(os.getenv("RAGDOLL_MAX_CONVERSATIONS", "50"))
MAX_HISTORY_TURNS = max(1, int(os.getenv("RAGDOLL_MAX_HISTORY_TURNS", "20")))

# Demo account displayed by dashboard.jsp. The API creates/repairs this row
# automatically so conversation history always has a real Users foreign key.
DEFAULT_USER_ID = int(os.getenv("RAGDOLL_DEFAULT_USER_ID", "0"))
DEFAULT_USERNAME = os.getenv("RAGDOLL_DEFAULT_USERNAME", "john_roblox").strip() or "john_roblox"
DEFAULT_USER_EMAIL = (
    os.getenv("RAGDOLL_DEFAULT_USER_EMAIL", "john.roblox@ragdoll.local").strip()
    or "john.roblox@ragdoll.local"
)


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


@contextmanager
def _database_connection() -> Iterator[Any]:
    if not DB_ENABLED:
        raise RuntimeError("MySQL integration is disabled by RAGDOLL_DB_ENABLED.")
    if mysql is None:
        raise RuntimeError("mysql-connector-python is not installed.")

    connection = mysql.connector.connect(**DB_CONFIG)
    try:
        yield connection
    finally:
        connection.close()


class ModelDatabase:
    """MySQL adapter for local model metadata and availability."""

    @staticmethod
    def _ensure_availability_column(cursor: Any) -> None:
        cursor.execute("SHOW COLUMNS FROM Models LIKE 'is_available'")
        if cursor.fetchone() is None:
            cursor.execute(
                """
                ALTER TABLE Models
                ADD COLUMN is_available TINYINT(1) NOT NULL DEFAULT 0
                AFTER is_enabled
                """
            )

    @staticmethod
    def _get_free_tier_id(cursor: Any) -> int:
        cursor.execute(
            """
            SELECT tier_id
            FROM Tiers
            WHERE LOWER(tier_name) = 'free'
            ORDER BY tier_id
            LIMIT 1
            """
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("The Free tier was not found in the Tiers table.")
        return int(row["tier_id"])

    def sync_discovered_models(
        self, files: List[Path]
    ) -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
        """
        Synchronize local GGUF files with MySQL.

        Newly discovered models are inserted, marked available, and assigned to
        the Free tier. Remembered local models that are no longer present remain
        in MySQL with is_available = 0.
        """

        if not DB_ENABLED:
            return {}, "MySQL integration is disabled."

        try:
            with _database_connection() as connection:
                cursor = connection.cursor(dictionary=True)
                self._ensure_availability_column(cursor)

                cursor.execute(
                    """
                    SELECT model_id, model_name, model_type, model_path,
                           model_location, is_enabled, is_available
                    FROM Models
                    WHERE model_location = 'local'
                    """
                )
                rows = list(cursor.fetchall())

                cursor.execute(
                    """
                    UPDATE Models
                    SET is_available = 0
                    WHERE model_location = 'local'
                    """
                )
                for row in rows:
                    row["is_available"] = 0

                next_model_id: Optional[int] = None
                free_tier_id: Optional[int] = None

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
                        if free_tier_id is None:
                            free_tier_id = self._get_free_tier_id(cursor)

                        model_name = model_file.stem
                        cursor.execute(
                            """
                            INSERT INTO Models
                                (model_id, model_name, model_type, model_path,
                                 model_location, server_model_id, is_enabled,
                                 is_available)
                            VALUES (%s, %s, 'gguf', %s, 'local', '', 1, 1)
                            """,
                            (next_model_id, model_name, relative_path),
                        )
                        cursor.execute(
                            """
                            INSERT IGNORE INTO Access (tier_id, model_id)
                            VALUES (%s, %s)
                            """,
                            (free_tier_id, next_model_id),
                        )
                        row = {
                            "model_id": next_model_id,
                            "model_name": model_name,
                            "model_type": "gguf",
                            "model_path": relative_path,
                            "model_location": "local",
                            "is_enabled": 1,
                            "is_available": 1,
                        }
                        rows.append(row)
                        next_model_id += 1
                    else:
                        cursor.execute(
                            """
                            UPDATE Models
                            SET model_path = %s,
                                model_type = 'gguf',
                                model_location = 'local',
                                is_available = 1
                            WHERE model_id = %s
                            """,
                            (relative_path, row["model_id"]),
                        )
                        row["model_path"] = relative_path
                        row["model_type"] = "gguf"
                        row["model_location"] = "local"
                        row["is_available"] = 1

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


class ConversationDatabase:
    """Persists conversations and loads prior turns for model context."""

    @staticmethod
    def _ensure_default_user_records(cursor: Any) -> None:
        """Create the temporary John Roblox account with user_id 0."""

        # Older project copies used user_id 21 for the same demo username.
        # Rename that legacy row first so the unique username/email constraints
        # do not prevent the new temporary user_id 0 row from being created.
        cursor.execute(
            """
            SELECT user_id
            FROM Users
            WHERE (username = %s OR email = %s)
              AND user_id <> %s
            ORDER BY user_id
            LIMIT 1
            """,
            (DEFAULT_USERNAME, DEFAULT_USER_EMAIL, DEFAULT_USER_ID),
        )
        legacy_user = cursor.fetchone()
        if legacy_user is not None:
            legacy_user_id = int(legacy_user["user_id"])
            cursor.execute(
                """
                UPDATE Users
                SET username = %s,
                    email = %s
                WHERE user_id = %s
                """,
                (
                    f"{DEFAULT_USERNAME}_legacy_{legacy_user_id}",
                    f"john.roblox.legacy.{legacy_user_id}@ragdoll.local",
                    legacy_user_id,
                ),
            )

        cursor.execute(
            """
            INSERT INTO Users (user_id, username, email, created_at)
            VALUES (%s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE
                username = VALUES(username),
                email = VALUES(email)
            """,
            (DEFAULT_USER_ID, DEFAULT_USERNAME, DEFAULT_USER_EMAIL),
        )

        # Keep the same demo-hash format used by database.sql. Authentication is
        # not yet connected, but this makes John a complete Users/User_Hashes row.
        cursor.execute(
            """
            INSERT INTO User_Hashes (user_id, password_hash, salt)
            VALUES (
                %s,
                SHA2(CONCAT(%s, '_password_', %s), 256),
                CONCAT('salt_', %s, '_', %s)
            )
            ON DUPLICATE KEY UPDATE
                password_hash = VALUES(password_hash),
                salt = VALUES(salt)
            """,
            (
                DEFAULT_USER_ID,
                DEFAULT_USERNAME,
                DEFAULT_USER_ID,
                DEFAULT_USERNAME,
                DEFAULT_USER_ID,
            ),
        )

        cursor.execute(
            """
            SELECT tier_id
            FROM Tiers
            WHERE LOWER(tier_name) = 'free'
            ORDER BY tier_id
            LIMIT 1
            """
        )
        free_tier = cursor.fetchone()
        if free_tier is not None:
            cursor.execute(
                """
                INSERT IGNORE INTO Has (user_id, tier_id, assigned_at)
                VALUES (%s, %s, NOW())
                """,
                (DEFAULT_USER_ID, int(free_tier["tier_id"])),
            )

    def ensure_default_user(self) -> None:
        """Persist John Roblox before the dashboard reads or writes history."""

        with _database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                self._ensure_default_user_records(cursor)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

    @staticmethod
    def _next_id(cursor: Any, table_name: str, column_name: str) -> int:
        allowed = {
            ("Conversations", "conversation_id"),
            ("Queries", "query_id"),
            ("Responses", "response_id"),
        }
        if (table_name, column_name) not in allowed:
            raise ValueError("Unsupported ID sequence.")
        cursor.execute(
            f"SELECT COALESCE(MAX({column_name}), 0) + 1 AS next_id FROM {table_name}"
        )
        return int(cursor.fetchone()["next_id"])

    @staticmethod
    def _title_from_query(query_text: str) -> str:
        title = " ".join(query_text.strip().split())
        if len(title) > 100:
            title = title[:97].rstrip() + "..."
        return title or "New conversation"

    @staticmethod
    def _verify_user(cursor: Any, user_id: int) -> None:
        cursor.execute("SELECT user_id FROM Users WHERE user_id = %s", (user_id,))
        if cursor.fetchone() is None:
            raise LookupError(f"User {user_id} was not found.")

    @staticmethod
    def _verify_conversation(cursor: Any, conversation_id: int, user_id: int) -> None:
        cursor.execute(
            """
            SELECT conversation_id
            FROM Conversations
            WHERE conversation_id = %s AND user_id = %s
            """,
            (conversation_id, user_id),
        )
        if cursor.fetchone() is None:
            raise LookupError(
                f"Conversation {conversation_id} does not belong to user {user_id}."
            )

    def load_history(self, conversation_id: int, user_id: int) -> List[Dict[str, str]]:
        if user_id == DEFAULT_USER_ID:
            self.ensure_default_user()
        with _database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            self._verify_conversation(cursor, conversation_id, user_id)
            cursor.execute(
                """
                SELECT q.query_text,
                       r.response_text
                FROM Contains_Query cq
                JOIN Queries q ON q.query_id = cq.query_id
                LEFT JOIN Responses r ON r.query_id = q.query_id
                LEFT JOIN Contains_Response cr
                    ON cr.response_id = r.response_id
                   AND cr.conversation_id = cq.conversation_id
                WHERE cq.conversation_id = %s
                  AND q.user_id = %s
                  AND (r.response_id IS NULL OR cr.response_id IS NOT NULL)
                ORDER BY q.created_at, q.query_id, r.created_at, r.response_id
                """,
                (conversation_id, user_id),
            )
            rows = list(cursor.fetchall())
            cursor.close()

        turns: List[Dict[str, str]] = []
        for row in rows:
            query_text = str(row.get("query_text") or "").strip()
            response_text = str(row.get("response_text") or "").strip()
            if query_text:
                turns.append(
                    {
                        "query_text": query_text,
                        "response_text": response_text,
                    }
                )
        return turns

    def list_conversations(self, user_id: int) -> List[Dict[str, Any]]:
        if user_id == DEFAULT_USER_ID:
            self.ensure_default_user()
        with _database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            self._verify_user(cursor, user_id)
            cursor.execute(
                """
                SELECT c.conversation_id,
                       c.title,
                       c.created_at,
                       COALESCE(MAX(COALESCE(r.created_at, q.created_at)), c.created_at)
                           AS updated_at
                FROM Conversations c
                LEFT JOIN Contains_Query cq
                    ON cq.conversation_id = c.conversation_id
                LEFT JOIN Queries q
                    ON q.query_id = cq.query_id
                LEFT JOIN Responses r
                    ON r.query_id = q.query_id
                WHERE c.user_id = %s
                GROUP BY c.conversation_id, c.title, c.created_at
                ORDER BY updated_at DESC, c.conversation_id DESC
                LIMIT %s
                """,
                (user_id, MAX_CONVERSATIONS),
            )
            rows = list(cursor.fetchall())
            cursor.close()
        return rows

    def get_conversation(self, conversation_id: int, user_id: int) -> Dict[str, Any]:
        if user_id == DEFAULT_USER_ID:
            self.ensure_default_user()
        with _database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            self._verify_conversation(cursor, conversation_id, user_id)
            cursor.execute(
                """
                SELECT conversation_id, title, created_at
                FROM Conversations
                WHERE conversation_id = %s AND user_id = %s
                """,
                (conversation_id, user_id),
            )
            conversation = cursor.fetchone()
            cursor.execute(
                """
                SELECT q.query_id,
                       q.query_text,
                       q.created_at AS query_created_at,
                       r.response_id,
                       r.response_text,
                       r.created_at AS response_created_at,
                       m.model_id,
                       m.model_name
                FROM Contains_Query cq
                JOIN Queries q ON q.query_id = cq.query_id
                LEFT JOIN Responses r ON r.query_id = q.query_id
                LEFT JOIN Contains_Response cr
                    ON cr.response_id = r.response_id
                   AND cr.conversation_id = cq.conversation_id
                LEFT JOIN Models m ON m.model_id = r.model_id
                WHERE cq.conversation_id = %s
                  AND q.user_id = %s
                  AND (r.response_id IS NULL OR cr.response_id IS NOT NULL)
                ORDER BY q.created_at, q.query_id, r.created_at, r.response_id
                """,
                (conversation_id, user_id),
            )
            rows = list(cursor.fetchall())
            cursor.close()

        messages: List[Dict[str, Any]] = []
        for row in rows:
            messages.append(
                {
                    "role": "user",
                    "text": str(row.get("query_text") or ""),
                    "created_at": row.get("query_created_at"),
                }
            )
            if row.get("response_id") is not None:
                messages.append(
                    {
                        "role": "assistant",
                        "text": str(row.get("response_text") or ""),
                        "created_at": row.get("response_created_at"),
                        "model_id": row.get("model_id"),
                        "model_name": row.get("model_name") or "RAGdoll",
                    }
                )

        return {
            "conversation_id": int(conversation["conversation_id"]),
            "title": conversation["title"],
            "created_at": conversation["created_at"],
            "messages": messages,
        }

    def delete_conversation(
        self, conversation_id: int, user_id: int
    ) -> Dict[str, int]:
        """Delete a conversation and its unshared queries and responses.

        The database schema cascades deletion from Queries to Responses and from
        Conversations to the Contains/Owns relationship rows. The explicit
        orphan checks also keep this safe if a query or response is ever linked
        to more than one conversation.
        """

        if user_id == DEFAULT_USER_ID:
            self.ensure_default_user()

        with CONVERSATION_WRITE_LOCK:
            with _database_connection() as connection:
                cursor = connection.cursor(dictionary=True)
                try:
                    self._verify_conversation(cursor, conversation_id, user_id)

                    cursor.execute(
                        """
                        SELECT query_id
                        FROM Contains_Query
                        WHERE conversation_id = %s
                        """,
                        (conversation_id,),
                    )
                    query_ids = [int(row["query_id"]) for row in cursor.fetchall()]

                    cursor.execute(
                        """
                        SELECT DISTINCT r.response_id
                        FROM Responses r
                        LEFT JOIN Contains_Response cr
                            ON cr.response_id = r.response_id
                        WHERE cr.conversation_id = %s
                           OR r.query_id IN (
                               SELECT query_id
                               FROM Contains_Query
                               WHERE conversation_id = %s
                           )
                        """,
                        (conversation_id, conversation_id),
                    )
                    response_ids = [
                        int(row["response_id"]) for row in cursor.fetchall()
                    ]

                    cursor.execute(
                        """
                        DELETE FROM Conversations
                        WHERE conversation_id = %s AND user_id = %s
                        """,
                        (conversation_id, user_id),
                    )
                    if cursor.rowcount != 1:
                        raise LookupError(
                            f"Conversation {conversation_id} does not belong to "
                            f"user {user_id}."
                        )

                    if response_ids:
                        placeholders = ", ".join(["%s"] * len(response_ids))
                        cursor.execute(
                            f"""
                            DELETE FROM Responses
                            WHERE response_id IN ({placeholders})
                              AND NOT EXISTS (
                                  SELECT 1
                                  FROM Contains_Response cr
                                  WHERE cr.response_id = Responses.response_id
                              )
                            """,
                            tuple(response_ids),
                        )

                    if query_ids:
                        placeholders = ", ".join(["%s"] * len(query_ids))
                        cursor.execute(
                            f"""
                            DELETE FROM Queries
                            WHERE query_id IN ({placeholders})
                              AND NOT EXISTS (
                                  SELECT 1
                                  FROM Contains_Query cq
                                  WHERE cq.query_id = Queries.query_id
                              )
                            """,
                            tuple(query_ids),
                        )

                    connection.commit()
                    return {
                        "conversation_id": conversation_id,
                        "deleted_queries": len(query_ids),
                        "deleted_responses": len(response_ids),
                    }
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()

    def save_turn(
        self,
        user_id: int,
        conversation_id: Optional[int],
        query_text: str,
        response_text: str,
        model_id: Optional[int],
    ) -> int:
        if model_id is None:
            raise RuntimeError("The selected model is not registered in MySQL.")

        with CONVERSATION_WRITE_LOCK:
            with _database_connection() as connection:
                cursor = connection.cursor(dictionary=True)
                try:
                    if user_id == DEFAULT_USER_ID:
                        self._ensure_default_user_records(cursor)
                    self._verify_user(cursor, user_id)

                    if conversation_id is None:
                        conversation_id = self._next_id(
                            cursor, "Conversations", "conversation_id"
                        )
                        cursor.execute(
                            """
                            INSERT INTO Conversations
                                (conversation_id, user_id, title, created_at)
                            VALUES (%s, %s, %s, NOW())
                            """,
                            (
                                conversation_id,
                                user_id,
                                self._title_from_query(query_text),
                            ),
                        )
                        cursor.execute(
                            """
                            INSERT IGNORE INTO Owns (user_id, conversation_id)
                            VALUES (%s, %s)
                            """,
                            (user_id, conversation_id),
                        )
                    else:
                        self._verify_conversation(cursor, conversation_id, user_id)

                    query_id = self._next_id(cursor, "Queries", "query_id")
                    response_id = self._next_id(cursor, "Responses", "response_id")

                    cursor.execute(
                        """
                        INSERT INTO Queries
                            (query_id, user_id, query_text, embedding_vector, created_at)
                        VALUES (%s, %s, %s, '[]', NOW())
                        """,
                        (query_id, user_id, query_text),
                    )
                    cursor.execute(
                        "INSERT IGNORE INTO Creates (user_id, query_id) VALUES (%s, %s)",
                        (user_id, query_id),
                    )
                    cursor.execute(
                        """
                        INSERT INTO Contains_Query (conversation_id, query_id)
                        VALUES (%s, %s)
                        """,
                        (conversation_id, query_id),
                    )
                    cursor.execute(
                        """
                        INSERT IGNORE INTO Prompts (query_id, model_id, prompted_at)
                        VALUES (%s, %s, NOW())
                        """,
                        (query_id, model_id),
                    )

                    cursor.execute(
                        """
                        INSERT INTO Responses
                            (response_id, query_id, model_id, response_text, created_at)
                        VALUES (%s, %s, %s, %s, NOW())
                        """,
                        (response_id, query_id, model_id, response_text),
                    )
                    cursor.execute(
                        "INSERT INTO Answers (query_id, response_id) VALUES (%s, %s)",
                        (query_id, response_id),
                    )
                    cursor.execute(
                        "INSERT INTO Generates (model_id, response_id) VALUES (%s, %s)",
                        (model_id, response_id),
                    )
                    cursor.execute(
                        """
                        INSERT INTO Contains_Response (conversation_id, response_id)
                        VALUES (%s, %s)
                        """,
                        (conversation_id, response_id),
                    )

                    connection.commit()
                    return int(conversation_id)
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()


MODEL_DATABASE = ModelDatabase()
CONVERSATION_DATABASE = ConversationDatabase()


def discover_models() -> Tuple[List[Dict[str, Any]], Optional[str]]:
    files = _scan_gguf_files()
    with MODEL_SYNC_LOCK:
        database_rows, database_error = MODEL_DATABASE.sync_discovered_models(files)

    models: List[Dict[str, Any]] = []
    for path in files:
        row = database_rows.get(path.name.lower())

        if row is not None and (
            not bool(row.get("is_enabled", 1))
            or not bool(row.get("is_available", 1))
        ):
            continue

        models.append(
            {
                "model_id": row.get("model_id") if row else None,
                "model_name": row.get("model_name") if row else path.stem,
                "file_name": path.name,
                "model_path": _relative_model_path(path),
                "absolute_path": str(path),
                "model_type": "gguf",
                "is_enabled": bool(row.get("is_enabled", 1)) if row else True,
                "is_available": bool(row.get("is_available", 1)) if row else True,
                "database_registered": row is not None,
            }
        )

    return models, database_error


class QueryRequest(BaseModel):
    query_text: str = Field(min_length=1)
    user_id: int = Field(default=DEFAULT_USER_ID, ge=0)
    conversation_id: Optional[int] = Field(default=None, ge=1)
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


def _trim_history(
    history: List[Dict[str, str]], request: QueryRequest
) -> List[Dict[str, str]]:
    """Return the newest complete conversation turns that fit the context window.

    Every turn remains stored in MySQL. Only the newest turns that fit are sent
    back to llama.cpp for the current generation.
    """

    n_ctx = int(os.getenv("LLAMA_N_CTX", "4096"))

    # Reserve room for generation, chat-template markers, and the new query.
    available_tokens = max(256, n_ctx - request.max_tokens - 384)
    character_budget = max(1000, available_tokens * 4 - len(request.query_text))

    selected: List[Dict[str, str]] = []
    used_characters = 0

    # A separate turn cap prevents very short conversations from creating an
    # unnecessarily large prompt even when the context window is large.
    candidate_turns = history[-MAX_HISTORY_TURNS:]

    for turn in reversed(candidate_turns):
        query_text = str(turn.get("query_text") or "")
        response_text = str(turn.get("response_text") or "")
        turn_size = len(query_text) + len(response_text)

        if used_characters + turn_size > character_budget:
            break

        selected.append(
            {
                "query_text": query_text,
                "response_text": response_text,
            }
        )
        used_characters += turn_size

    selected.reverse()
    return selected


def _generate_response(
    llm: Any,
    request: QueryRequest,
    history: List[Dict[str, str]],
) -> Tuple[str, int]:
    remembered_turns = _trim_history(history, request)
    messages: List[Dict[str, str]] = []
    if request.system_prompt:
        messages.append({"role": "system", "content": request.system_prompt})
    for turn in remembered_turns:
        messages.append({"role": "user", "content": turn["query_text"]})
        if turn.get("response_text"):
            messages.append(
                {"role": "assistant", "content": turn["response_text"]}
            )
    messages.append({"role": "user", "content": request.query_text})

    try:
        result = llm.create_chat_completion(
            messages=messages,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
        )
        content = result["choices"][0]["message"]["content"]
        return str(content or "").strip(), len(remembered_turns)
    except Exception as chat_error:
        prompt_parts: List[str] = []
        if request.system_prompt:
            prompt_parts.append(f"System: {request.system_prompt}")
        for turn in remembered_turns:
            prompt_parts.append(f"User: {turn['query_text']}")
            if turn.get("response_text"):
                prompt_parts.append(f"Assistant: {turn['response_text']}")
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
            return str(result["choices"][0]["text"] or "").strip(), len(
                remembered_turns
            )
        except Exception as completion_error:
            raise RuntimeError(
                f"Chat generation failed: {chat_error}; "
                f"plain completion also failed: {completion_error}"
            ) from completion_error


app = FastAPI(title="RAGdoll Local GGUF API", version="1.2")

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
    allow_methods=["GET", "POST", "DELETE"],
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


@app.get("/api/conversations")
def list_conversations(user_id: int = DEFAULT_USER_ID) -> Dict[str, Any]:
    try:
        conversations = CONVERSATION_DATABASE.list_conversations(user_id)
        return {"conversations": conversations}
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=f"Unable to load conversations from MySQL: {error}",
        ) from error


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: int, user_id: int = DEFAULT_USER_ID) -> Dict[str, Any]:
    try:
        return CONVERSATION_DATABASE.get_conversation(conversation_id, user_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=f"Unable to load the conversation from MySQL: {error}",
        ) from error


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: int, user_id: int = DEFAULT_USER_ID
) -> Dict[str, Any]:
    try:
        deleted = CONVERSATION_DATABASE.delete_conversation(
            conversation_id, user_id
        )
        return {
            "deleted": True,
            **deleted,
        }
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=f"Unable to delete the conversation from MySQL: {error}",
        ) from error


@app.post("/api/query")
def query_model(request: QueryRequest) -> Dict[str, Any]:
    selected = _resolve_model(request)
    model_path = Path(selected["absolute_path"])

    history: List[Dict[str, str]] = []
    if request.conversation_id is not None:
        try:
            history = CONVERSATION_DATABASE.load_history(
                request.conversation_id, request.user_id
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail=f"Unable to load conversation memory from MySQL: {error}",
            ) from error

    try:
        llm = LOADED_MODEL.get(model_path)
        started_at = time.perf_counter()
        with LOADED_MODEL.inference_lock:
            response_text, remembered_turn_count = _generate_response(
                llm, request, history
            )
        elapsed_seconds = round(time.perf_counter() - started_at, 3)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Model query failed: {error}") from error

    saved_conversation_id = request.conversation_id
    conversation_saved = False
    conversation_error: Optional[str] = None
    try:
        saved_conversation_id = CONVERSATION_DATABASE.save_turn(
            user_id=request.user_id,
            conversation_id=request.conversation_id,
            query_text=request.query_text,
            response_text=response_text,
            model_id=selected.get("model_id"),
        )
        conversation_saved = True
    except Exception as error:
        conversation_error = str(error)

    return {
        "response_text": response_text,
        "model_id": selected.get("model_id"),
        "model_name": selected["model_name"],
        "model_file": selected["file_name"],
        "elapsed_seconds": elapsed_seconds,
        "conversation_id": saved_conversation_id,
        "conversation_saved": conversation_saved,
        "conversation_error": conversation_error,
        "remembered_turn_count": remembered_turn_count,
        "conversation_memory_used": remembered_turn_count > 0,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("RAGDOLL_API_HOST", "127.0.0.1"),
        port=int(os.getenv("RAGDOLL_API_PORT", "8000")),
    )