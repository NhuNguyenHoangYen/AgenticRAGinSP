"""Backend settings independent of Streamlit and model-provider initialization."""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class APISettings:
    mongodb_uri: str = field(default="mongodb://127.0.0.1:27017", repr=False)
    mongodb_database: str = "agentic_rag"
    mongodb_timeout_ms: int = 5000
    environment: str = "development"
    development_user_id: str = "development-user"
    development_user_name: str = "Local developer"
    upload_directory: Path = PROJECT_ROOT / "var" / "uploads"
    embedding_provider: str = "huggingface"
    embedding_model: str = "sentence-transformers/all-mpnet-base-v2"
    qdrant_collection_prefix: str = "agentic-rag-api"
    ingestion_max_attempts: int = 3
    ingestion_lease_seconds: float = 90
    ingestion_poll_seconds: float = 2
    ingestion_retry_seconds: float = 5
    ingestion_timeout_seconds: float = 900
    upload_max_files: int = 10
    upload_batch_bytes: int = 100 * 1024 * 1024
    qa_context_max_chars: int = 48000

    def __post_init__(self):
        if not 2048 <= self.qa_context_max_chars <= 200000:
            raise ValueError("QA_CONTEXT_MAX_CHARS must be between 2048 and 200000")
        if self.ingestion_max_attempts < 1 or self.ingestion_lease_seconds < 3:
            raise ValueError("Ingestion attempts must be positive and lease duration at least 3 seconds")
        if min(self.ingestion_poll_seconds, self.ingestion_retry_seconds, self.ingestion_timeout_seconds) <= 0:
            raise ValueError("Worker polling and retry delays must be positive")
        if not 1 <= self.upload_max_files <= 100 or self.upload_batch_bytes <= 0:
            raise ValueError("Invalid upload batch limits")
        if self.embedding_provider not in {"huggingface", "cohere"}:
            raise ValueError("API_EMBEDDING_PROVIDER must be huggingface or cohere")
        if not self.embedding_model.strip():
            raise ValueError("API_EMBEDDING_MODEL must not be empty")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", self.qdrant_collection_prefix):
            raise ValueError("API_QDRANT_COLLECTION_PREFIX must contain only letters, digits, underscores or hyphens")
        if not self.mongodb_uri.startswith(("mongodb://", "mongodb+srv://")):
            raise ValueError("MONGODB_URI must use mongodb:// or mongodb+srv://")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", self.mongodb_database):
            raise ValueError("MONGODB_DATABASE must contain 1-64 letters, digits, underscores or hyphens")
        if self.mongodb_database in {"admin", "local", "config"}:
            raise ValueError("Use an application database, not a MongoDB system database")
        if self.mongodb_timeout_ms <= 0:
            raise ValueError("MONGODB_TIMEOUT_MS must be positive")
        if self.environment not in {"development", "testing"}:
            raise ValueError("The fixed-identity API supports development/testing only; implement authentication before production")
        if not self.development_user_id.strip() or len(self.development_user_id) > 128:
            raise ValueError("DEV_USER_ID must contain 1-128 characters")
        if not self.development_user_name.strip() or len(self.development_user_name) > 120:
            raise ValueError("DEV_USER_NAME must contain 1-120 characters")

    @classmethod
    def from_env(cls):
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        return cls(
            mongodb_uri=os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017"),
            mongodb_database=os.getenv("MONGODB_DATABASE", "agentic_rag"),
            mongodb_timeout_ms=int(os.getenv("MONGODB_TIMEOUT_MS", "5000")),
            environment=os.getenv("APP_ENV", "development"),
            development_user_id=os.getenv("DEV_USER_ID", "development-user"),
            development_user_name=os.getenv("DEV_USER_NAME", "Local developer"),
            upload_directory=PROJECT_ROOT / Path(os.getenv("UPLOAD_DIR", "var/uploads")),
            embedding_provider=os.getenv("API_EMBEDDING_PROVIDER", "huggingface"),
            embedding_model=os.getenv("API_EMBEDDING_MODEL") or (
                "embed-v4.0" if os.getenv("API_EMBEDDING_PROVIDER") == "cohere"
                else "sentence-transformers/all-mpnet-base-v2"),
            qdrant_collection_prefix=os.getenv("API_QDRANT_COLLECTION_PREFIX", "agentic-rag-api"),
            ingestion_max_attempts=int(os.getenv("INGESTION_MAX_ATTEMPTS", "3")),
            ingestion_lease_seconds=float(os.getenv("INGESTION_LEASE_SECONDS", "90")),
            ingestion_poll_seconds=float(os.getenv("INGESTION_POLL_SECONDS", "2")),
            ingestion_retry_seconds=float(os.getenv("INGESTION_RETRY_SECONDS", "5")),
            ingestion_timeout_seconds=float(os.getenv("INGESTION_TIMEOUT_SECONDS", "900")),
            upload_max_files=int(os.getenv("UPLOAD_MAX_FILES", "10")),
            upload_batch_bytes=int(os.getenv("UPLOAD_BATCH_BYTES", str(100*1024*1024))),
            qa_context_max_chars=int(os.getenv("QA_CONTEXT_MAX_CHARS", "48000")),
        )
