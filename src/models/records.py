"""Persistent domain records. Large histories/files live outside parent records."""
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


def utc_now():
    return datetime.now(timezone.utc)


class ValueModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_default=True)


class Record(ValueModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True,
                              validate_default=True, populate_by_name=True)
    id: str = Field(default_factory=lambda: uuid4().hex, alias="_id", min_length=1, max_length=128)
    created_at: AwareDatetime = Field(default_factory=utc_now)
    updated_at: AwareDatetime = Field(default_factory=utc_now)


class UserRecord(Record):
    auth_provider: str = "development"
    auth_subject: str
    display_name: str = Field(min_length=1, max_length=120)
    status: Literal["active", "disabled"] = "active"


class ChatRecord(Record):
    owner_id: str
    title: str = Field(default="New chat", min_length=1, max_length=120)
    status: Literal["active", "archived", "deleted"] = "active"
    document_set_version: int = Field(default=0, ge=0)
    next_message_sequence: int = Field(default=0, ge=0)
    active_document_id: str | None = None  # Legacy B reservation; no longer used for C membership.
    document_ids: list[str] = Field(default_factory=list, max_length=100)
    membership_initialized: bool = True


class DocumentVersion(ValueModel):
    document_id: str
    index_version: str


class SourceReference(DocumentVersion):
    label: str
    chunk_id: str
    filename: str
    page: int | None = Field(default=None, ge=1)
    section: str | None = None


class CitationReference(SourceReference):
    quote: str = Field(min_length=1,max_length=1000)


class EvidenceRecord(SourceReference):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    text: str = Field(max_length=16000)
    truncated: bool = False


class GenerationMetadata(ValueModel):
    provider: str
    model: str | None = None
    deployment: str | None = None
    prompt_version: str
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class MessageRecord(Record):
    owner_id: str
    chat_id: str
    turn_id: str
    request_id: str
    sequence: int = Field(ge=0)
    role: Literal["user", "assistant"]
    content: str = Field(default="", max_length=200000)
    status: Literal["pending", "generating", "completed", "failed", "cancelled"] = "pending"
    document_set_version: int = Field(default=0, ge=0)
    scope_mode: Literal['all_ready','selected'] = 'all_ready'
    retrieval_strategy: Literal['general','comparison'] = 'general'
    retrieval_k: int = Field(default=5,ge=1,le=20)
    excluded_document_ids: list[str] = Field(default_factory=list,max_length=100)
    answerability: Literal['answerable','partial','unanswerable'] | None = None
    answer_warnings: list[str] = Field(default_factory=list,max_length=100)
    retrieval_context_chars: int = Field(default=0,ge=0)
    source_snapshot: list[DocumentVersion] = Field(default_factory=list, max_length=100)
    citations: list[CitationReference] = Field(default_factory=list, max_length=100)
    retrieved_evidence: list[EvidenceRecord] = Field(default_factory=list, max_length=100)
    generation: GenerationMetadata | None = None
    completed_at: AwareDatetime | None = None


class IndexMetadata(ValueModel):
    collection: str
    embedding_profile: str
    parser_version: str
    chunker_version: str
    index_version: str
    chunk_count: int = Field(default=0, ge=0)


class DocumentRecord(Record):
    owner_id: str
    filename: str = Field(min_length=1, max_length=255)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    file_type: Literal["pdf", "docx", "txt", "md", "csv"]
    size_bytes: int = Field(gt=0)
    storage_key: str
    status: Literal["uploaded", "validating", "parsing", "indexing", "ready", "failed", "deleting"] = "uploaded"
    processing_error: str | None = None
    index: IndexMetadata | None = None
    dedup_key: str | None = None
    ingestion_job_id: str | None = None
    submission_request_id: str | None = None
    submission_chat_id: str | None = None
    warnings: list[str] = Field(default_factory=list, max_length=100)
    processing_attempt: int = Field(default=0, ge=0)
    processing_token: str | None = None


class ChatDocumentRecord(Record):
    owner_id: str
    chat_id: str
    document_id: str
    attached_by: str


class IngestionJobRecord(Record):
    owner_id: str
    document_id: str
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"] = "queued"
    stage: str = "queued"
    attempt: int = Field(default=0, ge=0)
    lease_expires_at: AwareDatetime | None = None
    error: str | None = None
    request_id: str | None = None
    chat_id: str | None = None
    embedding_profile: str | None = None
    collection: str | None = None
    parser_version: str | None = None
    chunker_version: str | None = None
    max_attempts: int = Field(default=3, ge=1)
    available_at: AwareDatetime = Field(default_factory=utc_now)
    lease_token: str | None = None
    worker_id: str | None = None
    completed: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    completed_at: AwareDatetime | None = None
    non_retryable: bool = False
    published: bool = False
    enabled: bool = False
    warnings: list[str] = Field(default_factory=list, max_length=100)
