"""UI-independent ingestion and QA contracts."""
from typing import Literal
from pydantic import Field
from src.models.records import ValueModel, DocumentVersion, GenerationMetadata, EvidenceRecord, CitationReference


class ProgressEvent(ValueModel):
    stage: str
    status: Literal["started", "completed", "failed"]
    document_id: str
    completed: int | None = None
    total: int | None = None


class RetrievedEvidence(EvidenceRecord):
    pass


class DocumentCoverage(ValueModel):
    document_id: str
    retrieved: bool
    cited: bool


class PipelineAnswer(ValueModel):
    answer: str = Field(max_length=200000)
    evidence: list[RetrievedEvidence] = Field(default_factory=list, max_length=100)
    generation: GenerationMetadata
    citations: list[CitationReference] = Field(default_factory=list,max_length=100)
    answerability: Literal['answerable','partial','unanswerable'] = 'answerable'
    warnings: list[str] = Field(default_factory=list,max_length=100)
    coverage: list[DocumentCoverage] = Field(default_factory=list,max_length=100)
    context_chars: int = 0


class QAResult(PipelineAnswer):
    turn_id: str
    request_id: str
    user_message_id: str
    assistant_message_id: str
    source_snapshot: list[DocumentVersion]
    document_set_version: int
    scope_mode: Literal['all_ready','selected'] = 'all_ready'
    strategy: Literal['general','comparison'] = 'general'
    excluded_document_ids: list[str] = Field(default_factory=list)


class AnswerEvent(ValueModel):
    """Reserved transport contract; B returns JSON, not simulated token streaming."""
    event: Literal["status", "answer_delta", "completed", "error"]
    request_id: str
    text: str | None = None
    result: QAResult | None = None
    error_code: str | None = None
