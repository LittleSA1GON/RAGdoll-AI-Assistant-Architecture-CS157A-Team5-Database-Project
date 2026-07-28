import os
import sys

# queries are run from this file and stored and such
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
sys.dont_write_bytecode = True

import json
import math
import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

try:
    import mysql.connector
except ImportError:  # the API can still run without MySQL.
    mysql = None  # type: ignore[assignment]

try:
    from llama_cpp import Llama
except ImportError:  # model discovery remains available without llama-cpp-python.
    Llama = None  # type: ignore[assignment,misc]

try:
    from embedding import (
        DocumentExtractionError,
        EMBEDDER,
        EMBEDDING_MODEL_NAME,
        EmbeddingConfigurationError,
        SUPPORTED_EXTENSIONS,
        embed_query,
        prepare_document,
    )
except ImportError:
    from .embedding import (
        DocumentExtractionError,
        EMBEDDER,
        EMBEDDING_MODEL_NAME,
        EmbeddingConfigurationError,
        SUPPORTED_EXTENSIONS,
        embed_query,
        prepare_document,
    )


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
DOCUMENT_WRITE_LOCK = threading.Lock()
ADMIN_IDENTITY_LOCK = threading.Lock()
ADMIN_CONFIGURATION_LOCK = threading.Lock()
UPLOAD_DIRECTORY = Path(
    os.getenv("RAGDOLL_UPLOAD_DIR", str(PROJECT_ROOT / "data" / "uploads"))
).resolve()
MAX_UPLOAD_BYTES = max(1, int(os.getenv("RAGDOLL_MAX_UPLOAD_MB", "25"))) * 1024 * 1024
RAG_TOP_K = max(1, int(os.getenv("RAGDOLL_RAG_TOP_K", "4")))
RAG_MIN_SIMILARITY = min(
    1.0, max(-1.0, float(os.getenv("RAGDOLL_RAG_MIN_SIMILARITY", "0.55")))
)
RAG_SCORE_MARGIN = min(
    1.0, max(0.0, float(os.getenv("RAGDOLL_RAG_SCORE_MARGIN", "0.08")))
)
# Once the best chunk clears the main relevance threshold, additional chunks
# from that same document may be included at this lower cosine floor. This is
# useful for broad requests such as "summarize the project proposal," where a
# single top chunk does not contain the whole answer.
RAG_CONTEXT_MIN_SIMILARITY = min(
    1.0,
    max(-1.0, float(os.getenv("RAGDOLL_RAG_CONTEXT_MIN_SIMILARITY", "0.35"))),
)
RAG_ACCESS_SCOPE = "all_users"
RAG_MAX_CHUNKS_SCANNED = max(1, int(os.getenv("RAGDOLL_RAG_MAX_CHUNKS", "5000")))
RAG_ENABLED = os.getenv("RAGDOLL_RAG_ENABLED", "true").lower() not in {
    "0", "false", "no"
}
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

# Temporary administrator displayed by admin.jsp. Older databases may not yet
# contain this row even when database.sql has been updated, so the API repairs
# the identity automatically before administrator operations.
DEFAULT_ADMIN_USER_ID = int(os.getenv("RAGDOLL_DEFAULT_ADMIN_USER_ID", "20"))
DEFAULT_ADMIN_USERNAME = (
    os.getenv("RAGDOLL_DEFAULT_ADMIN_USERNAME", "jane_fortnite").strip()
    or "jane_fortnite"
)
DEFAULT_ADMIN_EMAIL = (
    os.getenv("RAGDOLL_DEFAULT_ADMIN_EMAIL", "jane.fortnite@ragdoll.local").strip()
    or "jane.fortnite@ragdoll.local"
)
DEFAULT_ADMIN_COMPANY_ID = (
    os.getenv("RAGDOLL_DEFAULT_ADMIN_COMPANY_ID", "RAGDOLL010").strip()
    or "RAGDOLL010"
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


ID_COLUMNS = {
    "Conversations": "conversation_id",
    "Queries": "query_id",
    "Responses": "response_id",
    "Documents": "document_id",
    "Chunks": "chunk_id",
    "Audit_Log": "log_id",
}

MODEL_COMPAT_COLUMNS = {
    "is_available": "TINYINT(1) NOT NULL DEFAULT 0 AFTER is_enabled",
}
DOCUMENT_COMPAT_COLUMNS = {
    "file_path": "VARCHAR(255) NULL AFTER file_type",
    "processing_status": "VARCHAR(20) NOT NULL DEFAULT 'uploaded' AFTER file_path",
    "processing_error": "TEXT NULL AFTER processing_status",
    "rag_access_scope": (
        "VARCHAR(20) NOT NULL DEFAULT 'all_users' AFTER processing_error"
    ),
}
CHUNK_COMPAT_COLUMNS = {
    "embedding_model": "VARCHAR(150) NULL AFTER embedding_vector",
    "embedding_dimension": "INT NULL AFTER embedding_model",
    "embedded_at": "DATETIME NULL AFTER embedding_dimension",
}
QUERY_COMPAT_COLUMNS = {
    "embedding_model": "VARCHAR(150) NULL AFTER embedding_vector",
    "embedding_dimension": "INT NULL AFTER embedding_model",
    "rag_eligible": "TINYINT(1) NOT NULL DEFAULT 1 AFTER embedding_dimension",
}
RETRIEVE_COMPAT_COLUMNS = {
    "similarity_score": "DECIMAL(8,6) NULL AFTER chunk_id",
}


def _next_id(cursor: Any, table: str) -> int:
    column = ID_COLUMNS.get(table)
    if column is None:
        raise ValueError(f"Unsupported ID sequence: {table}.")
    cursor.execute(
        f"SELECT COALESCE(MAX({column}), 0) + 1 AS next_id FROM {table}"
    )
    return int(cursor.fetchone()["next_id"])


def _ensure_columns(cursor: Any, table: str, required: Dict[str, str]) -> None:
    cursor.execute(f"SHOW COLUMNS FROM {table}")
    present = {str(row["Field"]) for row in cursor.fetchall()}
    for column, definition in required.items():
        if column not in present:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _verify_admin(cursor: Any, admin_user_id: int) -> None:
    cursor.execute("SELECT user_id FROM Admins WHERE user_id = %s", (admin_user_id,))
    if cursor.fetchone() is None:
        raise PermissionError(f"User {admin_user_id} is not an administrator.")


def _ensure_demo_user(
    cursor: Any,
    *,
    user_id: int,
    username: str,
    email: str,
    tier_name: str,
    legacy_email_template: str,
) -> None:
    """Upsert a demo user and move conflicting legacy identities aside."""

    cursor.execute(
        """
        SELECT user_id
        FROM Users
        WHERE (username = %s OR email = %s)
          AND user_id <> %s
        ORDER BY user_id
        """,
        (username, email, user_id),
    )
    for legacy_user in cursor.fetchall():
        legacy_user_id = int(legacy_user["user_id"])
        cursor.execute(
            """
            UPDATE Users
            SET username = %s, email = %s
            WHERE user_id = %s
            """,
            (
                f"{username}_legacy_{legacy_user_id}",
                legacy_email_template.format(user_id=legacy_user_id),
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
        (user_id, username, email),
    )
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
        (user_id, username, user_id, username, user_id),
    )
    cursor.execute(
        """
        SELECT tier_id
        FROM Tiers
        WHERE LOWER(tier_name) = LOWER(%s)
        ORDER BY tier_id
        LIMIT 1
        """,
        (tier_name,),
    )
    tier = cursor.fetchone()
    if tier is not None:
        cursor.execute(
            """
            INSERT IGNORE INTO Has (user_id, tier_id, assigned_at)
            VALUES (%s, %s, NOW())
            """,
            (user_id, int(tier["tier_id"])),
        )


class ModelDatabase:
    """MySQL adapter for local model metadata and availability."""

    @staticmethod
    def _ensure_availability_column(cursor: Any) -> None:
        _ensure_columns(cursor, "Models", MODEL_COMPAT_COLUMNS)

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

        _ensure_demo_user(
            cursor,
            user_id=DEFAULT_USER_ID,
            username=DEFAULT_USERNAME,
            email=DEFAULT_USER_EMAIL,
            tier_name="free",
            legacy_email_template="john.roblox.legacy.{user_id}@ragdoll.local",
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

    @staticmethod
    def _ensure_query_embedding_columns(cursor: Any) -> None:
        _ensure_columns(cursor, "Queries", QUERY_COMPAT_COLUMNS)
        _ensure_columns(cursor, "Retrieves", RETRIEVE_COMPAT_COLUMNS)

    def save_turn(
        self,
        user_id: int,
        conversation_id: Optional[int],
        query_text: str,
        response_text: str,
        model_id: Optional[int],
        query_embedding: Optional[List[float]] = None,
        retrieved_chunks: Optional[List[Dict[str, Any]]] = None,
        rag_eligible: bool = True,
    ) -> int:
        if model_id is None:
            raise RuntimeError("The selected model is not registered in MySQL.")

        with CONVERSATION_WRITE_LOCK:
            with _database_connection() as connection:
                cursor = connection.cursor(dictionary=True)
                try:
                    self._ensure_query_embedding_columns(cursor)
                    if user_id == DEFAULT_USER_ID:
                        self._ensure_default_user_records(cursor)
                    self._verify_user(cursor, user_id)

                    is_new_conversation = conversation_id is None
                    if is_new_conversation:
                        conversation_id = _next_id(cursor, "Conversations")
                        conversation_title = self._title_from_query(query_text)
                        cursor.execute(
                            """
                            INSERT INTO Conversations
                                (conversation_id, user_id, title, created_at)
                            VALUES (%s, %s, %s, NOW())
                            """,
                            (
                                conversation_id,
                                user_id,
                                conversation_title,
                            ),
                        )
                        cursor.execute(
                            """
                            INSERT IGNORE INTO Owns (user_id, conversation_id)
                            VALUES (%s, %s)
                            """,
                            (user_id, conversation_id),
                        )
                        AdminControlDatabase._insert_audit(
                            cursor,
                            user_id,
                            f"User created conversation '{conversation_title}'",
                            "CREATE_CONVERSATION",
                        )
                    else:
                        self._verify_conversation(cursor, conversation_id, user_id)

                    query_id = _next_id(cursor, "Queries")
                    response_id = _next_id(cursor, "Responses")

                    embedding_values = query_embedding or []
                    cursor.execute(
                        """
                        INSERT INTO Queries
                            (query_id, user_id, query_text, embedding_vector,
                             embedding_model, embedding_dimension, rag_eligible, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                        """,
                        (
                            query_id,
                            user_id,
                            query_text,
                            json.dumps(embedding_values, separators=(",", ":")),
                            EMBEDDING_MODEL_NAME if embedding_values else None,
                            len(embedding_values) if embedding_values else None,
                            1 if rag_eligible else 0,
                        ),
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
                    query_summary = " ".join(query_text.strip().split())
                    if len(query_summary) > 80:
                        query_summary = query_summary[:77].rstrip() + "..."
                    AdminControlDatabase._insert_audit(
                        cursor,
                        user_id,
                        f"User submitted query: {query_summary}" if query_summary
                        else "User submitted an empty query",
                        "SUBMIT_QUERY",
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
                    for retrieved in retrieved_chunks or []:
                        cursor.execute(
                            """
                            INSERT INTO Retrieves
                                (query_id, document_id, chunk_id, similarity_score)
                            VALUES (%s, %s, %s, %s)
                            ON DUPLICATE KEY UPDATE
                                similarity_score = VALUES(similarity_score)
                            """,
                            (
                                query_id,
                                int(retrieved["document_id"]),
                                int(retrieved["chunk_id"]),
                                float(retrieved.get("score", 0.0)),
                            ),
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


class DocumentDatabase:
    """Stores uploaded documents and dense chunk embeddings in MySQL."""

    @staticmethod
    def _ensure_document_columns(cursor: Any) -> None:
        _ensure_columns(cursor, "Documents", DOCUMENT_COMPAT_COLUMNS)
        cursor.execute(
            "UPDATE Documents SET rag_access_scope = %s "
            "WHERE rag_access_scope IS NULL OR rag_access_scope = ''",
            (RAG_ACCESS_SCOPE,),
        )

    @staticmethod
    def _ensure_chunk_embedding_columns(cursor: Any) -> None:
        _ensure_columns(cursor, "Chunks", CHUNK_COMPAT_COLUMNS)

    @staticmethod
    def _ensure_default_admin_records(cursor: Any) -> None:
        """Create or repair the temporary Jane administrator identity."""

        _ensure_demo_user(
            cursor,
            user_id=DEFAULT_ADMIN_USER_ID,
            username=DEFAULT_ADMIN_USERNAME,
            email=DEFAULT_ADMIN_EMAIL,
            tier_name="admin access",
            legacy_email_template=(
                "jane.fortnite.legacy.{user_id}@ragdoll.local"
            ),
        )

        cursor.execute(
            """
            SELECT user_id
            FROM Admins
            WHERE admin_email = %s
              AND user_id <> %s
            ORDER BY user_id
            """,
            (DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_USER_ID),
        )
        for legacy_admin in cursor.fetchall():
            legacy_admin_id = int(legacy_admin["user_id"])
            cursor.execute(
                """
                UPDATE Admins
                SET admin_email = %s
                WHERE user_id = %s
                """,
                (
                    f"jane.fortnite.admin.legacy.{legacy_admin_id}@ragdoll.local",
                    legacy_admin_id,
                ),
            )

        cursor.execute(
            """
            INSERT INTO Admins (user_id, company_id, admin_email)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                company_id = VALUES(company_id),
                admin_email = VALUES(admin_email)
            """,
            (
                DEFAULT_ADMIN_USER_ID,
                DEFAULT_ADMIN_COMPANY_ID,
                DEFAULT_ADMIN_EMAIL,
            ),
        )

    def ensure_admin_identity(self, admin_user_id: int) -> None:
        """Repair the configured temporary administrator automatically."""

        if admin_user_id != DEFAULT_ADMIN_USER_ID:
            return

        with ADMIN_IDENTITY_LOCK:
            with _database_connection() as connection:
                cursor = connection.cursor(dictionary=True)
                try:
                    self._ensure_default_admin_records(cursor)
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()

    def begin_document(
        self,
        admin_user_id: int,
        file_name: str,
        file_type: str,
    ) -> int:
        self.ensure_admin_identity(admin_user_id)
        with DOCUMENT_WRITE_LOCK:
            with _database_connection() as connection:
                cursor = connection.cursor(dictionary=True)
                try:
                    self._ensure_document_columns(cursor)
                    _verify_admin(cursor, admin_user_id)
                    document_id = _next_id(cursor, "Documents")
                    cursor.execute(
                        """
                        INSERT INTO Documents
                            (document_id, user_id, file_name, file_type, file_path,
                             processing_status, processing_error, rag_access_scope,
                             uploaded_at)
                        VALUES (%s, %s, %s, %s, NULL, 'processing', NULL, %s, NOW())
                        """,
                        (
                            document_id,
                            admin_user_id,
                            file_name,
                            file_type,
                            RAG_ACCESS_SCOPE,
                        ),
                    )
                    cursor.execute(
                        """
                        INSERT INTO Manages (admin_user_id, document_id, managed_at)
                        VALUES (%s, %s, NOW())
                        """,
                        (admin_user_id, document_id),
                    )
                    connection.commit()
                    return document_id
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()

    def set_file_path(self, document_id: int, file_path: str) -> None:
        with _database_connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    "UPDATE Documents SET file_path = %s WHERE document_id = %s",
                    (file_path, document_id),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

    def complete_document(
        self,
        document_id: int,
        chunks: List[str],
        embeddings: List[List[float]],
        embedding_model_name: str,
        embedding_dimension: int,
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("Chunk and embedding counts do not match.")

        with DOCUMENT_WRITE_LOCK:
            with _database_connection() as connection:
                cursor = connection.cursor(dictionary=True)
                try:
                    self._ensure_chunk_embedding_columns(cursor)
                    next_chunk_id = _next_id(cursor, "Chunks")
                    for offset, (chunk_text, vector) in enumerate(
                        zip(chunks, embeddings)
                    ):
                        chunk_id = next_chunk_id + offset
                        cursor.execute(
                            """
                            INSERT INTO Chunks
                                (chunk_id, document_id, chunk_text, embedding_vector,
                                 embedding_model, embedding_dimension, embedded_at)
                            VALUES (%s, %s, %s, %s, %s, %s, NOW())
                            """,
                            (
                                chunk_id,
                                document_id,
                                chunk_text,
                                json.dumps(vector, separators=(",", ":")),
                                embedding_model_name,
                                embedding_dimension,
                            ),
                        )
                        cursor.execute(
                            """
                            INSERT INTO Splits_Into (document_id, chunk_id)
                            VALUES (%s, %s)
                            """,
                            (document_id, chunk_id),
                        )
                    cursor.execute(
                        """
                        UPDATE Documents
                        SET processing_status = 'ready', processing_error = NULL
                        WHERE document_id = %s
                        """,
                        (document_id,),
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()

    def fail_document(self, document_id: int, error_message: str) -> None:
        with _database_connection() as connection:
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    UPDATE Documents
                    SET processing_status = 'failed', processing_error = %s
                    WHERE document_id = %s
                    """,
                    (error_message[:4000], document_id),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()

    def list_documents(self, admin_user_id: int) -> List[Dict[str, Any]]:
        self.ensure_admin_identity(admin_user_id)
        with _database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            self._ensure_document_columns(cursor)
            self._ensure_chunk_embedding_columns(cursor)
            _verify_admin(cursor, admin_user_id)
            cursor.execute(
                """
                SELECT d.document_id,
                       d.file_name,
                       d.file_type,
                       d.file_path,
                       d.processing_status,
                       d.processing_error,
                       d.uploaded_at,
                       COUNT(c.chunk_id) AS chunk_count,
                       MAX(c.embedding_model) AS embedding_model,
                       MAX(c.embedding_dimension) AS embedding_dimension
                FROM Documents d
                JOIN Manages m
                  ON m.document_id = d.document_id
                 AND m.admin_user_id = %s
                LEFT JOIN Chunks c ON c.document_id = d.document_id
                GROUP BY d.document_id, d.file_name, d.file_type, d.file_path,
                         d.processing_status, d.processing_error, d.uploaded_at
                ORDER BY d.uploaded_at DESC, d.document_id DESC
                """,
                (admin_user_id,),
            )
            rows = list(cursor.fetchall())
            cursor.close()
        return rows

    def get_document(self, admin_user_id: int, document_id: int) -> Dict[str, Any]:
        self.ensure_admin_identity(admin_user_id)
        with _database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                self._ensure_document_columns(cursor)
                _verify_admin(cursor, admin_user_id)
                cursor.execute(
                    """
                    SELECT d.document_id,
                           d.file_name,
                           d.file_type,
                           d.file_path,
                           d.processing_status,
                           d.processing_error,
                           d.uploaded_at,
                           COUNT(c.chunk_id) AS chunk_count
                    FROM Documents d
                    JOIN Manages m
                      ON m.document_id = d.document_id
                     AND m.admin_user_id = %s
                    LEFT JOIN Chunks c ON c.document_id = d.document_id
                    WHERE d.document_id = %s
                    GROUP BY d.document_id, d.file_name, d.file_type, d.file_path,
                             d.processing_status, d.processing_error, d.uploaded_at
                    """,
                    (admin_user_id, document_id),
                )
                row = cursor.fetchone()
                if row is None:
                    raise LookupError(
                        f"Document {document_id} was not found for administrator "
                        f"{admin_user_id}."
                    )
                return dict(row)
            finally:
                cursor.close()

    def delete_document(self, admin_user_id: int, document_id: int) -> Dict[str, Any]:
        """Delete a managed document and all of its stored RAG data."""

        self.ensure_admin_identity(admin_user_id)
        with DOCUMENT_WRITE_LOCK:
            with _database_connection() as connection:
                cursor = connection.cursor(dictionary=True)
                try:
                    self._ensure_document_columns(cursor)
                    _verify_admin(cursor, admin_user_id)
                    cursor.execute(
                        """
                        SELECT d.document_id, d.file_name, d.file_path
                        FROM Documents d
                        JOIN Manages m
                          ON m.document_id = d.document_id
                         AND m.admin_user_id = %s
                        WHERE d.document_id = %s
                        FOR UPDATE
                        """,
                        (admin_user_id, document_id),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        raise LookupError(
                            f"Document {document_id} was not found for administrator "
                            f"{admin_user_id}."
                        )
                    cursor.execute(
                        "SELECT COUNT(*) AS chunk_count FROM Chunks WHERE document_id = %s",
                        (document_id,),
                    )
                    count_row = cursor.fetchone()
                    row["chunk_count"] = int(count_row.get("chunk_count") or 0)

                    cursor.execute(
                        "DELETE FROM Retrieves WHERE document_id = %s",
                        (document_id,),
                    )
                    cursor.execute(
                        "DELETE FROM Splits_Into WHERE document_id = %s",
                        (document_id,),
                    )
                    cursor.execute(
                        "DELETE FROM Chunks WHERE document_id = %s",
                        (document_id,),
                    )
                    cursor.execute(
                        "DELETE FROM Manages WHERE document_id = %s",
                        (document_id,),
                    )
                    cursor.execute(
                        "DELETE FROM Documents WHERE document_id = %s",
                        (document_id,),
                    )
                    connection.commit()
                    return {
                        "document_id": int(row["document_id"]),
                        "file_name": str(row.get("file_name") or "document"),
                        "file_path": row.get("file_path"),
                        "deleted_chunk_count": int(row.get("chunk_count") or 0),
                    }
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()


class RagDatabase:
    """Cosine retrieval with intent and relevance gates."""

    _SOCIAL_ONLY_PATTERNS = (
        r"(?:hi|hello|hey|hiya|greetings)(?:\s+(?:there|ragdoll))?",
        r"good\s+(?:morning|afternoon|evening)",
        r"(?:how\s+are\s+you|how(?:'s|\s+is)\s+it\s+going|what(?:'s|\s+is)\s+up)",
        r"(?:thanks|thank\s+you|thx)(?:\s+(?:so\s+much|very\s+much))?",
        r"(?:bye|goodbye|see\s+you|see\s+ya|good\s+night)",
        r"(?:who\s+are\s+you|what\s+can\s+you\s+do)",
    )

    @staticmethod
    def _cosine_similarity(left: List[float], right: List[float]) -> float:
        if len(left) != len(right) or not left:
            return -1.0
        dot = float(sum(a * b for a, b in zip(left, right)))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0.0 or right_norm == 0.0:
            return -1.0
        return dot / (left_norm * right_norm)

    @classmethod
    def should_retrieve(cls, query_text: str) -> Tuple[bool, Optional[str]]:
        """Skip uploaded documents for greetings and other social-only turns."""

        normalized = re.sub(r"[^a-z0-9'\s]+", " " , query_text.lower())
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if not normalized:
            return False, "empty_query"
        if len(normalized.split()) <= 8 and any(
            re.fullmatch(pattern, normalized)
            for pattern in cls._SOCIAL_ONLY_PATTERNS
        ):
            return False, "social_or_greeting_query"
        return True, None

    def retrieve(
        self, query_text: str, top_k: int = RAG_TOP_K
    ) -> Tuple[List[float], List[Dict[str, Any]], Dict[str, Any]]:
        query_vector = embed_query(query_text)
        with _database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            DocumentDatabase._ensure_document_columns(cursor)
            DocumentDatabase._ensure_chunk_embedding_columns(cursor)
            # Persist automatic schema/access-scope repairs before retrieval.
            connection.commit()
            cursor.execute(
                """
                SELECT c.chunk_id,
                       c.document_id,
                       c.chunk_text,
                       c.embedding_vector,
                       c.embedding_model,
                       c.embedding_dimension,
                       d.file_name
                FROM Chunks c
                JOIN Documents d ON d.document_id = c.document_id
                WHERE d.processing_status = 'ready'
                  AND COALESCE(d.rag_access_scope, 'all_users') = %s
                ORDER BY c.chunk_id DESC
                LIMIT %s
                """,
                (RAG_ACCESS_SCOPE, RAG_MAX_CHUNKS_SCANNED),
            )
            rows = list(cursor.fetchall())
            cursor.close()

        scored: List[Dict[str, Any]] = []
        for row in rows:
            try:
                raw_vector = row.get("embedding_vector")
                if isinstance(raw_vector, (list, tuple)):
                    stored = raw_vector
                else:
                    stored = json.loads(str(raw_vector or "[]"))
                vector = [float(value) for value in stored]
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if len(vector) != len(query_vector) or not vector:
                # Legacy/demo vectors are ignored instead of contaminating retrieval.
                continue
            stored_model = str(row.get("embedding_model") or "").strip()
            if stored_model and stored_model != EMBEDDING_MODEL_NAME:
                # Equal-length vectors from different embedding models are not comparable.
                continue
            score = self._cosine_similarity(query_vector, vector)
            scored.append(
                {
                    "chunk_id": int(row["chunk_id"]),
                    "document_id": int(row["document_id"]),
                    "file_name": str(row.get("file_name") or "document"),
                    "chunk_text": str(row.get("chunk_text") or ""),
                    "embedding_model": row.get("embedding_model"),
                    "embedding_dimension": row.get("embedding_dimension"),
                    "score": score,
                }
            )

        scored.sort(key=lambda item: item["score"], reverse=True)
        top_score = float(scored[0]["score"]) if scored else None
        accepted: List[Dict[str, Any]] = []
        expanded_chunk_count = 0
        if top_score is not None and top_score >= RAG_MIN_SIMILARITY:
            relative_floor = max(RAG_MIN_SIMILARITY, top_score - RAG_SCORE_MARGIN)
            strict_matches = [
                item for item in scored
                if float(item["score"]) >= relative_floor
            ]

            # A passing top chunk proves that the document is relevant. Fill
            # the remaining context slots with the best cosine-ranked chunks
            # from that same document so broad questions can be answered from
            # more than one isolated paragraph.
            top_document_id = int(scored[0]["document_id"])
            same_document_expansion = [
                item
                for item in scored
                if int(item["document_id"]) == top_document_id
                and float(item["score"]) >= RAG_CONTEXT_MIN_SIMILARITY
                and item not in strict_matches
            ]

            for item in strict_matches + same_document_expansion:
                if item not in accepted:
                    accepted.append(item)
                if len(accepted) >= max(1, top_k):
                    break
            expanded_chunk_count = max(0, len(accepted) - len(strict_matches))

        metadata = {
            "candidate_count": len(scored),
            "top_score": top_score,
            "minimum_similarity": RAG_MIN_SIMILARITY,
            "context_minimum_similarity": RAG_CONTEXT_MIN_SIMILARITY,
            "score_margin": RAG_SCORE_MARGIN,
            "access_scope": RAG_ACCESS_SCOPE,
            "relevant_chunk_count": len(accepted),
            "expanded_chunk_count": expanded_chunk_count,
            "skip_reason": None if accepted else "below_similarity_threshold",
        }
        return query_vector, accepted, metadata

    @staticmethod
    def build_context(chunks: List[Dict[str, Any]]) -> str:
        if not chunks:
            return ""
        sections = [
            "RAGDoll has already authorized this user to use the shared RAG "
            "knowledge base. The excerpts below were selected from uploaded "
            "documents by normalized embedding vectors and cosine similarity. "
            "They are application-provided context, not inaccessible external "
            "files. When they answer the request, respond directly from them. "
            "Do not say that you lack document access, that the content is "
            "private, or that using it would violate confidentiality. Cite the "
            "supporting excerpt inline as [Source N]. If the excerpts are "
            "incomplete, answer what they support and clearly identify only the "
            "specific missing detail."
        ]
        for index, chunk in enumerate(chunks, start=1):
            sections.append(
                f"[Source {index}: {chunk['file_name']}; "
                f"similarity={float(chunk['score']):.4f}]\n{chunk['chunk_text']}"
            )
        return "\n\n".join(sections)


class AdminControlDatabase:
    """Administration queries for tiers, remembered models, and audit logs."""

    @staticmethod
    def _insert_audit(
        cursor: Any,
        user_id: int,
        action_log: str,
        action_type: str,
    ) -> int:
        log_id = _next_id(cursor, "Audit_Log")
        cursor.execute(
            """
            INSERT INTO Audit_Log
                (log_id, user_id, action_log, action_type, action_date)
            VALUES (%s, %s, %s, %s, NOW())
            """,
            (
                log_id,
                user_id,
                action_log[:255],
                action_type[:50],
            ),
        )
        cursor.execute(
            "INSERT INTO Triggers (user_id, log_id) VALUES (%s, %s)",
            (user_id, log_id),
        )
        return log_id

    def list_tiers_and_models(self, admin_user_id: int) -> Dict[str, Any]:
        DOCUMENT_DATABASE.ensure_admin_identity(admin_user_id)
        with _database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                _verify_admin(cursor, admin_user_id)
                MODEL_DATABASE._ensure_availability_column(cursor)

                cursor.execute(
                    """
                    SELECT tier_id, tier_name, price
                    FROM Tiers
                    ORDER BY tier_id
                    """
                )
                tier_rows = list(cursor.fetchall())

                cursor.execute(
                    """
                    SELECT model_id, model_name, model_type, model_path,
                           model_location, server_model_id, is_enabled,
                           is_available
                    FROM Models
                    ORDER BY model_id
                    """
                )
                model_rows = list(cursor.fetchall())

                cursor.execute(
                    """
                    SELECT tier_id, model_id
                    FROM Access
                    ORDER BY tier_id, model_id
                    """
                )
                access_rows = list(cursor.fetchall())
            finally:
                cursor.close()

        access_by_tier: Dict[int, List[int]] = {}
        for row in access_rows:
            access_by_tier.setdefault(int(row["tier_id"]), []).append(
                int(row["model_id"])
            )

        tiers = [
            {
                "tier_id": int(row["tier_id"]),
                "tier_name": str(row["tier_name"]),
                "price": float(row["price"]),
                "model_ids": access_by_tier.get(int(row["tier_id"]), []),
            }
            for row in tier_rows
        ]
        models = [
            {
                "model_id": int(row["model_id"]),
                "model_name": str(row["model_name"]),
                "model_type": str(row["model_type"]),
                "model_path": str(row.get("model_path") or ""),
                "model_location": str(row.get("model_location") or "local"),
                "server_model_id": str(row.get("server_model_id") or ""),
                "is_enabled": bool(row.get("is_enabled", 1)),
                "is_available": bool(row.get("is_available", 0)),
            }
            for row in model_rows
        ]
        return {"tiers": tiers, "models": models}

    def update_tier(
        self,
        admin_user_id: int,
        tier_id: int,
        price: float,
        model_ids: List[int],
    ) -> Dict[str, Any]:
        DOCUMENT_DATABASE.ensure_admin_identity(admin_user_id)
        selected_model_ids = sorted({int(model_id) for model_id in model_ids})

        with ADMIN_CONFIGURATION_LOCK:
            with _database_connection() as connection:
                cursor = connection.cursor(dictionary=True)
                try:
                    _verify_admin(cursor, admin_user_id)
                    cursor.execute(
                        "SELECT tier_id, tier_name FROM Tiers WHERE tier_id = %s",
                        (tier_id,),
                    )
                    tier = cursor.fetchone()
                    if tier is None:
                        raise LookupError(f"Tier {tier_id} was not found.")

                    if selected_model_ids:
                        placeholders = ", ".join(["%s"] * len(selected_model_ids))
                        cursor.execute(
                            f"SELECT model_id FROM Models WHERE model_id IN ({placeholders})",
                            tuple(selected_model_ids),
                        )
                        found = {int(row["model_id"]) for row in cursor.fetchall()}
                        missing = [
                            model_id
                            for model_id in selected_model_ids
                            if model_id not in found
                        ]
                        if missing:
                            raise LookupError(
                                "Unknown model IDs: "
                                + ", ".join(str(model_id) for model_id in missing)
                            )

                    cursor.execute(
                        "UPDATE Tiers SET price = %s WHERE tier_id = %s",
                        (round(float(price), 2), tier_id),
                    )
                    cursor.execute("DELETE FROM Access WHERE tier_id = %s", (tier_id,))
                    if selected_model_ids:
                        cursor.executemany(
                            "INSERT INTO Access (tier_id, model_id) VALUES (%s, %s)",
                            [(tier_id, model_id) for model_id in selected_model_ids],
                        )

                    self._insert_audit(
                        cursor,
                        admin_user_id,
                        (
                            f"Admin set {tier['tier_name']} tier price to "
                            f"${float(price):.2f} with "
                            f"{len(selected_model_ids)} model(s)"
                        ),
                        "UPDATE_TIER",
                    )
                    connection.commit()
                    return {
                        "tier_id": int(tier["tier_id"]),
                        "tier_name": str(tier["tier_name"]),
                        "price": round(float(price), 2),
                        "model_ids": selected_model_ids,
                    }
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()

    def list_audit_logs(
        self, admin_user_id: int, limit: int = 100
    ) -> List[Dict[str, Any]]:
        DOCUMENT_DATABASE.ensure_admin_identity(admin_user_id)
        safe_limit = max(1, min(int(limit), 500))
        with _database_connection() as connection:
            cursor = connection.cursor(dictionary=True)
            try:
                _verify_admin(cursor, admin_user_id)
                cursor.execute(
                    """
                    SELECT a.log_id,
                           a.user_id,
                           u.username,
                           a.action_log,
                           a.action_type,
                           a.action_date
                    FROM Audit_Log a
                    LEFT JOIN Users u ON u.user_id = a.user_id
                    ORDER BY a.action_date DESC, a.log_id DESC
                    LIMIT %s
                    """,
                    (safe_limit,),
                )
                rows = list(cursor.fetchall())
            finally:
                cursor.close()

        return [
            {
                "log_id": int(row["log_id"]),
                "user_id": (
                    int(row["user_id"]) if row.get("user_id") is not None else None
                ),
                "username": str(row.get("username") or "Deleted user"),
                "action_log": str(row["action_log"]),
                "action_type": str(row["action_type"]),
                "action_date": row["action_date"],
            }
            for row in rows
        ]

    def record_audit(
        self, admin_user_id: int, action_log: str, action_type: str
    ) -> None:
        DOCUMENT_DATABASE.ensure_admin_identity(admin_user_id)
        with ADMIN_CONFIGURATION_LOCK:
            with _database_connection() as connection:
                cursor = connection.cursor(dictionary=True)
                try:
                    _verify_admin(cursor, admin_user_id)
                    self._insert_audit(
                        cursor, admin_user_id, action_log, action_type
                    )
                    connection.commit()
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    cursor.close()


def _safe_upload_name(file_name: str) -> str:
    base_name = Path(file_name or "document").name
    cleaned = re.sub(r"[^A-Za-z0-9._ -]+", "_", base_name).strip(" .")
    return cleaned[:180] or "document"


def _project_relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _stored_upload_path(file_path: Any) -> Path:
    if not file_path:
        raise FileNotFoundError("The document does not have a stored upload path.")

    candidate = Path(str(file_path)).expanduser()
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    resolved = candidate.resolve()
    upload_root = UPLOAD_DIRECTORY.resolve()
    try:
        resolved.relative_to(upload_root)
    except ValueError as error:
        raise PermissionError(
            "The stored document path is outside the configured upload directory."
        ) from error
    return resolved


def _remove_stored_upload(document_id: int, file_path: Any) -> Tuple[bool, Optional[str]]:
    if not file_path:
        return False, None

    try:
        stored_path = _stored_upload_path(file_path)
        if not stored_path.exists():
            return False, None

        document_directory = stored_path.parent
        upload_root = UPLOAD_DIRECTORY.resolve()
        if (
            document_directory.parent == upload_root
            and document_directory.name == str(document_id)
        ):
            for child in document_directory.iterdir():
                if child.is_file() or child.is_symlink():
                    child.unlink()
                elif child.is_dir():
                    import shutil
                    shutil.rmtree(child)
            document_directory.rmdir()
        else:
            stored_path.unlink()
        return True, None
    except Exception as error:
        return False, str(error)


MODEL_DATABASE = ModelDatabase()
CONVERSATION_DATABASE = ConversationDatabase()
DOCUMENT_DATABASE = DocumentDatabase()
ADMIN_DATABASE = AdminControlDatabase()
RAG_DATABASE = RagDatabase()


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


class TierConfigurationUpdate(BaseModel):
    price: float = Field(ge=0.0, le=999999.99)
    model_ids: List[int] = Field(default_factory=list)


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


_RAG_ACCESS_REFUSAL_PATTERNS = (
    "do not have access",
    "don't have access",
    "cannot access",
    "can't access",
    "no access to the document",
    "privacy and confidentiality",
    "breach of privacy",
    "breach of confidentiality",
    "document you've referenced",
    "document you referenced",
)


def _looks_like_false_rag_refusal(response_text: str) -> bool:
    """Detect a model claiming it cannot use context already supplied by RAG."""

    normalized = re.sub(r"\s+", " ", str(response_text or "").lower()).strip()
    return any(pattern in normalized for pattern in _RAG_ACCESS_REFUSAL_PATTERNS)


def _build_extractive_rag_answer(chunks: List[Dict[str, Any]]) -> str:
    """Return a guaranteed grounded answer if a small model refuses twice."""

    lines = [
        "Based on the uploaded RAG documents, the relevant information is:",
    ]
    for index, chunk in enumerate(chunks, start=1):
        text = re.sub(r"\s+", " ", str(chunk.get("chunk_text") or "")).strip()
        if len(text) > 700:
            text = text[:697].rstrip() + "..."
        if text:
            lines.append(f"- {text} [Source {index}]")
    if len(lines) == 1:
        lines.append("The retrieved excerpts were empty.")
    return "\n\n".join(lines)


def _generate_response(
    llm: Any,
    request: QueryRequest,
    history: List[Dict[str, str]],
    rag_context: str = "",
    strict_rag_grounding: bool = False,
) -> Tuple[str, int]:
    remembered_turns = _trim_history(history, request)
    messages: List[Dict[str, str]] = []
    rag_active = bool(rag_context)
    rag_policy = ""
    if rag_active:
        rag_policy = (
            "The current user is allowed to use all shared RAG documents. "
            "The application has already retrieved and supplied the relevant "
            "excerpts. Treat them as available evidence and answer from them. "
            "Never claim that you cannot access the referenced document or that "
            "using the supplied excerpts would violate privacy or confidentiality."
        )
        if strict_rag_grounding:
            rag_policy += (
                " This is a grounding retry. Give a direct, factual answer based "
                "on the excerpts, cite [Source N], and do not replace the answer "
                "with a generic description of what the document might contain."
            )

    system_parts = [
        part for part in [request.system_prompt, rag_policy, rag_context] if part
    ]
    combined_system_prompt = "\n\n".join(system_parts)
    if combined_system_prompt:
        messages.append({"role": "system", "content": combined_system_prompt})
    for turn in remembered_turns:
        messages.append({"role": "user", "content": turn["query_text"]})
        if turn.get("response_text"):
            messages.append(
                {"role": "assistant", "content": turn["response_text"]}
            )

    current_user_message = request.query_text
    if rag_active:
        current_user_message = (
            "Use the application-provided RAG excerpts above to answer this "
            "request directly. The excerpts are available to this user. "
            "Cite supporting excerpts as [Source N].\n\n"
            f"Request: {request.query_text}"
        )
    messages.append({"role": "user", "content": current_user_message})

    generation_temperature = (
        min(request.temperature, 0.2) if strict_rag_grounding else request.temperature
    )

    try:
        result = llm.create_chat_completion(
            messages=messages,
            max_tokens=request.max_tokens,
            temperature=generation_temperature,
        )
        content = result["choices"][0]["message"]["content"]
        return str(content or "").strip(), len(remembered_turns)
    except Exception as chat_error:
        prompt_parts: List[str] = []
        if combined_system_prompt:
            prompt_parts.append(f"System: {combined_system_prompt}")
        for turn in remembered_turns:
            prompt_parts.append(f"User: {turn['query_text']}")
            if turn.get("response_text"):
                prompt_parts.append(f"Assistant: {turn['response_text']}")
        prompt_parts.append(f"User: {current_user_message}")
        prompt_parts.append("Assistant:")
        prompt = "\n\n".join(prompt_parts)

        try:
            result = llm(
                prompt,
                max_tokens=request.max_tokens,
                temperature=generation_temperature,
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


app = FastAPI(title="RAGdoll Local RAG API", version="1.4")

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
    # Allow local Tomcat/Eclipse deployments on any localhost port.
    # Without this, the browser reports "Failed to fetch" even when
    # FastAPI is running and returned a response.
    allow_origin_regex=r"https?://(?:localhost|127\.0\.0\.1)(?::\d+)?",
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)


@app.on_event("startup")
def initialize_temporary_admin() -> None:
    """Repair Jane's demo administrator row whenever the API starts."""

    if not DB_ENABLED:
        return
    try:
        DOCUMENT_DATABASE.ensure_admin_identity(DEFAULT_ADMIN_USER_ID)
        print(
            f"Temporary administrator {DEFAULT_ADMIN_USER_ID} "
            "is ready in MySQL.",
            flush=True,
        )
    except Exception as error:
        # Keep the API available when MySQL starts later than Tomcat. Every
        # administrator request retries the same repair automatically.
        print(
            "Temporary administrator initialization will be retried on the "
            f"first admin request: {error}",
            flush=True,
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
        "embedding": EMBEDDER.status(),
        "rag_enabled": RAG_ENABLED,
        "rag_min_similarity": RAG_MIN_SIMILARITY,
        "rag_context_min_similarity": RAG_CONTEXT_MIN_SIMILARITY,
        "rag_score_margin": RAG_SCORE_MARGIN,
        "rag_access_scope": RAG_ACCESS_SCOPE,
    }


@app.get("/api/embedding/status")
def embedding_status() -> Dict[str, Any]:
    return EMBEDDER.status()


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


@app.get("/api/admin/tiers")
def list_admin_tiers(admin_user_id: int) -> Dict[str, Any]:
    try:
        _, model_sync_error = discover_models()
        catalog = ADMIN_DATABASE.list_tiers_and_models(admin_user_id)
        return {**catalog, "model_sync_error": model_sync_error}
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=f"Unable to load pricing and tiers from MySQL: {error}",
        ) from error


@app.post("/api/admin/tiers/{tier_id}")
def update_admin_tier(
    tier_id: int,
    request: TierConfigurationUpdate,
    admin_user_id: int,
) -> Dict[str, Any]:
    try:
        tier = ADMIN_DATABASE.update_tier(
            admin_user_id=admin_user_id,
            tier_id=tier_id,
            price=request.price,
            model_ids=request.model_ids,
        )
        return {"updated": True, "tier": tier}
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to update the tier: {error}",
        ) from error


@app.get("/api/admin/audit-logs")
def list_admin_audit_logs(
    admin_user_id: int,
    limit: int = 100,
) -> Dict[str, Any]:
    try:
        logs = ADMIN_DATABASE.list_audit_logs(admin_user_id, limit)
        return {"logs": logs}
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=f"Unable to load audit logs from MySQL: {error}",
        ) from error


@app.get("/api/admin/documents")
def list_admin_documents(admin_user_id: int) -> Dict[str, Any]:
    try:
        documents = DOCUMENT_DATABASE.list_documents(admin_user_id)
        return {"documents": documents, "embedding": EMBEDDER.status()}
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=f"Unable to load documents from MySQL: {error}",
        ) from error


@app.get("/api/admin/documents/{document_id}/download")
def download_admin_document(
    document_id: int, admin_user_id: int
) -> FileResponse:
    try:
        document = DOCUMENT_DATABASE.get_document(admin_user_id, document_id)
        stored_path = _stored_upload_path(document.get("file_path"))
        if not stored_path.is_file():
            raise FileNotFoundError("The original uploaded file is not available.")
        return FileResponse(
            path=str(stored_path),
            filename=str(document.get("file_name") or stored_path.name),
            media_type="application/octet-stream",
        )
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except (LookupError, FileNotFoundError) as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to download the document: {error}",
        ) from error


@app.delete("/api/admin/documents/{document_id}")
def delete_admin_document(
    document_id: int, admin_user_id: int
) -> Dict[str, Any]:
    try:
        deleted = DOCUMENT_DATABASE.delete_document(admin_user_id, document_id)
        file_deleted, file_delete_error = _remove_stored_upload(
            document_id, deleted.get("file_path")
        )
        try:
            ADMIN_DATABASE.record_audit(
                admin_user_id,
                (
                    f"Admin removed {deleted['file_name']} with "
                    f"{deleted['deleted_chunk_count']} chunk(s)"
                ),
                "REMOVE_DOCUMENT",
            )
        except Exception as audit_error:
            print(f"Unable to record document removal audit log: {audit_error}", flush=True)
        return {
            "deleted": True,
            "document_id": deleted["document_id"],
            "file_name": deleted["file_name"],
            "deleted_chunk_count": deleted["deleted_chunk_count"],
            "file_deleted": file_deleted,
            "file_delete_error": file_delete_error,
        }
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=500,
            detail=f"Unable to remove the document: {error}",
        ) from error


@app.post("/api/admin/documents")
async def upload_admin_document(
    admin_user_id: int = Form(...),
    file: UploadFile = File(...),
) -> Dict[str, Any]:
    safe_name = _safe_upload_name(file.filename or "document")
    extension = Path(safe_name).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported document type. Allowed: {allowed}.",
        )

    contents = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if not contents:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(contents) > MAX_UPLOAD_BYTES:
        limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"The uploaded file exceeds the {limit_mb} MB limit.",
        )

    document_id: Optional[int] = None
    try:
        document_id = DOCUMENT_DATABASE.begin_document(
            admin_user_id=admin_user_id,
            file_name=safe_name,
            file_type=extension.lstrip(".").upper(),
        )
        document_directory = UPLOAD_DIRECTORY / str(document_id)
        document_directory.mkdir(parents=True, exist_ok=True)
        saved_path = document_directory / safe_name
        saved_path.write_bytes(contents)
        DOCUMENT_DATABASE.set_file_path(
            document_id, _project_relative_path(saved_path)
        )

        prepared = prepare_document(saved_path)
        DOCUMENT_DATABASE.complete_document(
            document_id=document_id,
            chunks=prepared.chunks,
            embeddings=prepared.embeddings,
            embedding_model_name=prepared.embedding_model_name,
            embedding_dimension=prepared.embedding_dimension,
        )
        try:
            ADMIN_DATABASE.record_audit(
                admin_user_id,
                (
                    f"Admin uploaded {safe_name} and created "
                    f"{len(prepared.chunks)} chunk(s)"
                ),
                "UPLOAD_DOCUMENT",
            )
        except Exception as audit_error:
            print(f"Unable to record document upload audit log: {audit_error}", flush=True)
        return {
            "document_id": document_id,
            "file_name": safe_name,
            "processing_status": "ready",
            "chunk_count": len(prepared.chunks),
            "embedding_dimension": prepared.embedding_dimension,
            "embedding_model_name": prepared.embedding_model_name,
            "embedding_model_directory": prepared.model_directory,
        }
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error)) from error
    except (DocumentExtractionError, EmbeddingConfigurationError, ValueError) as error:
        if document_id is not None:
            try:
                DOCUMENT_DATABASE.fail_document(document_id, str(error))
            except Exception:
                pass
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        if document_id is not None:
            try:
                DOCUMENT_DATABASE.fail_document(document_id, str(error))
            except Exception:
                pass
        raise HTTPException(
            status_code=500,
            detail=f"Document processing failed: {error}",
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

    query_embedding: List[float] = []
    retrieved_chunks: List[Dict[str, Any]] = []
    rag_error: Optional[str] = None
    rag_context = ""
    rag_metadata: Dict[str, Any] = {
        "candidate_count": 0,
        "top_score": None,
        "minimum_similarity": RAG_MIN_SIMILARITY,
        "score_margin": RAG_SCORE_MARGIN,
        "relevant_chunk_count": 0,
        "skip_reason": None,
    }
    rag_eligible, intent_skip_reason = RAG_DATABASE.should_retrieve(request.query_text)
    if not RAG_ENABLED:
        rag_metadata["skip_reason"] = "rag_disabled"
    elif not rag_eligible:
        rag_metadata["skip_reason"] = intent_skip_reason
        rag_context = (
            "The user's current message is casual conversation rather than a "
            "document question. Reply briefly and naturally. Do not summarize or "
            "mention uploaded documents unless the user explicitly asks about them."
        )
    else:
        try:
            query_embedding, retrieved_chunks, rag_metadata = RAG_DATABASE.retrieve(
                request.query_text, RAG_TOP_K
            )
            rag_context = RAG_DATABASE.build_context(retrieved_chunks)
        except Exception as error:
            # The LLM remains usable when the embedding model or MySQL is offline.
            rag_error = str(error)
            rag_metadata["skip_reason"] = "retrieval_error"

    try:
        llm = LOADED_MODEL.get(model_path)
        started_at = time.perf_counter()
        rag_grounding_retry = False
        rag_extractive_fallback = False
        with LOADED_MODEL.inference_lock:
            response_text, remembered_turn_count = _generate_response(
                llm, request, history, rag_context
            )
            if retrieved_chunks and _looks_like_false_rag_refusal(response_text):
                rag_grounding_retry = True
                # Do not include the earlier conversation on the retry because a
                # prior refusal can cause a small model to repeat the same mistake.
                response_text, _ = _generate_response(
                    llm,
                    request,
                    [],
                    rag_context,
                    strict_rag_grounding=True,
                )
                if _looks_like_false_rag_refusal(response_text):
                    rag_extractive_fallback = True
                    response_text = _build_extractive_rag_answer(retrieved_chunks)
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
            query_embedding=query_embedding,
            retrieved_chunks=retrieved_chunks,
            rag_eligible=rag_eligible,
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
        "rag_enabled": RAG_ENABLED,
        "rag_eligible": rag_eligible,
        "rag_used": bool(retrieved_chunks),
        "rag_skip_reason": rag_metadata.get("skip_reason"),
        "rag_top_score": rag_metadata.get("top_score"),
        "rag_min_similarity": rag_metadata.get("minimum_similarity"),
        "rag_candidate_count": rag_metadata.get("candidate_count", 0),
        "rag_expanded_chunk_count": rag_metadata.get("expanded_chunk_count", 0),
        "rag_access_scope": rag_metadata.get("access_scope", RAG_ACCESS_SCOPE),
        "rag_grounding_retry": rag_grounding_retry,
        "rag_extractive_fallback": rag_extractive_fallback,
        "rag_error": rag_error,
        "retrieved_sources": [
            {
                "document_id": chunk["document_id"],
                "chunk_id": chunk["chunk_id"],
                "file_name": chunk["file_name"],
                "score": round(float(chunk["score"]), 4),
            }
            for chunk in retrieved_chunks
        ],
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("RAGDOLL_API_HOST", "127.0.0.1"),
        port=int(os.getenv("RAGDOLL_API_PORT", "8000")),
    )