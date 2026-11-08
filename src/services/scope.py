"""Resolve one immutable membership/index snapshot before touching vector search."""
from dataclasses import dataclass

from src.models.records import DocumentRecord
from src.observability import get_logger
from src.services.chat_service import ChatService
from src.services.errors import WorkflowError

log = get_logger(__name__)


@dataclass(frozen=True)
class RetrievalScope:
    owner_id: str
    chat_id: str
    document_set_version: int
    documents: tuple[DocumentRecord, ...]
    excluded_document_ids: tuple[str, ...]
    scope_mode: str
    strategy: str
    k: int
    context_max_chars: int


class ScopeResolver:
    def __init__(self, repositories, pipeline):
        self.repositories, self.pipeline = repositories, pipeline

    async def resolve(self, owner_id, chat_id, scope_mode, document_ids, strategy, k):
        if (scope_mode not in {'all_ready','selected'} or strategy not in {'general','comparison'} or
            not 1<=k<=20 or len(document_ids)>100 or len(set(document_ids))!=len(document_ids) or
            (scope_mode=='selected' and not document_ids) or (scope_mode=='all_ready' and document_ids)):
            raise WorkflowError('invalid_scope','Invalid document scope or retrieval budget')
        chat = await ChatService(self.repositories).get(owner_id,chat_id)
        if chat.status != 'active':
            raise WorkflowError('chat_not_active','Chat is not active')
        selected = list(document_ids) if scope_mode == 'selected' else list(chat.document_ids)
        if any(identifier not in chat.document_ids for identifier in selected):
            raise WorkflowError('document_not_accessible','One or more requested documents are unavailable in this chat')
        records = await self.repositories.documents.get_many_owned(selected,owner_id)
        if any(identifier not in records for identifier in selected):
            raise WorkflowError('document_not_accessible','One or more requested documents are unavailable in this chat')
        ready, excluded = [], []
        for identifier in selected:
            document = records[identifier]
            if document.status != 'ready' or document.index is None:
                if scope_mode == 'selected':
                    raise WorkflowError('document_not_ready','Every explicitly selected document must be ready')
                excluded.append(identifier)
                continue
            if document.index.embedding_profile != self.pipeline.embedding_profile:
                raise WorkflowError('embedding_profile_changed','Selected ready documents use another embedding profile; select compatible documents or restore their configuration')
            ready.append(document.model_copy(deep=True))
        if not ready:
            raise WorkflowError('no_ready_documents','No ready documents are available in the requested scope')
        if strategy == 'comparison' and len(ready) < 2:
            raise WorkflowError('comparison_requires_documents','Comparison mode requires at least two ready documents')
        if strategy == 'comparison' and (len(ready)>k or self.pipeline.settings.qa_context_max_chars//len(ready)<1024):
            raise WorkflowError('comparison_budget_too_small','Increase k or select fewer documents to provide comparison evidence for each source')
        scope = RetrievalScope(owner_id,chat_id,chat.document_set_version,tuple(ready),tuple(excluded),
                               scope_mode,strategy,k,self.pipeline.settings.qa_context_max_chars)
        log.info('qa.scope_resolved',scope_mode=scope_mode,strategy=strategy,
                 allowed_document_ids=[doc.id for doc in ready],excluded_document_ids=excluded,
                 document_set_version=scope.document_set_version,k=k)
        return scope
