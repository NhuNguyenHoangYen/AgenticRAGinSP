"""Public API contracts; database-only fields do not leak into responses."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.models.records import GenerationMetadata, CitationReference, DocumentVersion, EvidenceRecord


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CreateChatRequest(RequestModel):
    title: str = Field(default="New chat", min_length=1, max_length=120)


class RenameChatRequest(RequestModel):
    title: str = Field(min_length=1, max_length=120)


class ReusableDocumentResponse(ResponseModel):
    id: str
    filename: str
    file_type: str


class ReusableDocumentPage(ResponseModel):
    items: list[ReusableDocumentResponse]
    total: int
    limit: int
    offset: int


class UserResponse(ResponseModel):
    id: str
    display_name: str
    identity_mode: Literal["development"] = "development"


class ChatResponse(ResponseModel):
    id: str
    title: str
    status: str
    document_set_version: int
    created_at: datetime
    updated_at: datetime


class CitationView(CitationReference):
    attached: bool


class MessageResponse(ResponseModel):
    id: str
    chat_id: str
    turn_id: str
    request_id: str
    sequence: int
    role: str
    content: str
    status: str
    document_set_version: int
    scope_mode: str
    retrieval_strategy: str
    retrieval_k: int
    excluded_document_ids: list[str]
    answerability: str | None
    answer_warnings: list[str]
    retrieval_context_chars: int
    source_snapshot: list[DocumentVersion]
    citations: list[CitationView]
    retrieved_evidence: list[EvidenceRecord]
    generation: GenerationMetadata | None
    created_at: datetime
    completed_at: datetime | None


class AttachedDocumentResponse(ResponseModel):
    attachment_id: str
    document_id: str
    filename: str
    file_type: str
    status: str
    chunk_count: int | None
    attached_at: datetime
    ingestion_job_id: str | None = None
    embedding_profile: str | None = None
    index_version: str | None = None
    processing_error: str | None = None
    warnings: list[str] = Field(default_factory=list)


class ChatPage(ResponseModel):
    items: list[ChatResponse]
    total: int
    limit: int
    offset: int


class MessagePage(ResponseModel):
    items: list[MessageResponse]
    total: int
    limit: int
    offset: int


class DocumentPage(ResponseModel):
    items: list[AttachedDocumentResponse]
    total: int
    limit: int
    offset: int


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: list[dict] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
    request_id: str | None


class HealthResponse(BaseModel):
    status: Literal["ok", "ready"]
    service: str = "agentic-rag-api"
    milestone: str = "E"
    identity_mode: Literal["development"] = "development"
