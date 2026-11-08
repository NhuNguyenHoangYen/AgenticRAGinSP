"""Milestone B upload/answer transport contracts."""
from datetime import datetime
from typing import Literal
from pydantic import Field, model_validator
from src.api.schemas.foundation import RequestModel, ResponseModel
from src.services.contracts import ProgressEvent, QAResult


class AskQuestionRequest(RequestModel):
    question: str = Field(min_length=1, max_length=10000)
    k: int = Field(default=5, ge=1, le=20)
    scope_mode: Literal['all_ready','selected'] = 'all_ready'
    document_ids: list[str] = Field(default_factory=list,max_length=100)
    strategy: Literal['general','comparison'] = 'general'

    @model_validator(mode='after')
    def validate_scope(self):
        if self.scope_mode=='selected' and not self.document_ids:
            raise ValueError('Selected scope requires at least one document ID')
        if self.scope_mode=='all_ready' and self.document_ids:
            raise ValueError('Use selected scope when supplying document IDs')
        if len(set(self.document_ids))!=len(self.document_ids):
            raise ValueError('Document IDs must be unique')
        if any(not value.strip() or len(value)>128 for value in self.document_ids):
            raise ValueError('Invalid document ID')
        return self


class UploadResponse(ResponseModel):
    document_id: str
    filename: str
    status: str
    chunk_count: int
    index_version: str
    warnings: list[str]
    progress: list[ProgressEvent]
    request_id: str


class UploadItem(ResponseModel):
    filename: str
    document_id: str | None = None
    job_id: str | None = None
    status: str
    deduplicated: bool = False
    error_code: str | None = None
    error: str | None = None


class BatchUploadResponse(ResponseModel):
    items: list[UploadItem]
    accepted: int
    rejected: int
    request_id: str


class AttachDocumentRequest(RequestModel):
    document_id: str = Field(min_length=1, max_length=128)


class AttachmentChangeResponse(ResponseModel):
    document_id: str
    changed: bool
    document_set_version: int


class JobResponse(ResponseModel):
    id: str
    document_id: str
    status: str
    stage: str
    attempt: int
    max_attempts: int
    completed: int
    total: int
    error: str | None
    non_retryable: bool
    warnings: list[str]
    available_at: datetime
    lease_expires_at: datetime | None
    completed_at: datetime | None
