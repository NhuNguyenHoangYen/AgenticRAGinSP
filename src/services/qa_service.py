"""Scoped multi-document QA with persisted messages and validated source references."""
import asyncio
from uuid import uuid4

from src.models.records import DocumentVersion, MessageRecord, utc_now
from src.observability import EvaluationRecorder, RequestContext, get_logger, request_context
from src.observability.context import context_fields
from src.services.chat_service import ChatService
from src.services.contracts import QAResult
from src.services.errors import WorkflowError
from src.services.scope import ScopeResolver
from src.services.rag_pipeline import PROMPT_VERSION

log = get_logger(__name__)


class QAService:
    def __init__(self, repositories, pipeline):
        self.repositories, self.pipeline = repositories, pipeline

    async def ask(self, owner_id, chat_id, question, k=5, scope_mode="all_ready", document_ids=(), strategy="general"):
        context = RequestContext(user_id=owner_id, chat_id=chat_id,
                                 request_id=context_fields().get('request_id') or uuid4().hex,
                                 turn_id=uuid4().hex)
        with request_context(context):
            return await self._ask(owner_id, chat_id, question, k, context.turn_id, context.request_id,
                                   scope_mode,document_ids,strategy)

    async def _ask(self,owner_id,chat_id,question,k,turn_id,request_id,scope_mode,document_ids,strategy):
        scope=await ScopeResolver(self.repositories,self.pipeline).resolve(
            owner_id,chat_id,scope_mode,document_ids,strategy,k)
        allowed={(doc.id,doc.index.index_version) for doc in scope.documents}
        prior=await self.repositories.messages.history(chat_id,owner_id)
        history=[message for message in prior if message.source_snapshot and
                 {(item.document_id,item.index_version) for item in message.source_snapshot}<=allowed]
        log.info('qa.history_filtered',included_messages=len(history),excluded_messages=len(prior)-len(history))
        allocation = await self.repositories.chats.allocate_turn(chat_id, owner_id)
        if allocation is None:
            raise WorkflowError("chat_not_active", "Chat is not active")
        snapshot = [DocumentVersion(document_id=doc.id,index_version=doc.index.index_version) for doc in scope.documents]
        shared = dict(owner_id=owner_id, chat_id=chat_id, turn_id=turn_id, request_id=request_id,
                      source_snapshot=snapshot,document_set_version=scope.document_set_version,
                      scope_mode=scope_mode,retrieval_strategy=strategy,retrieval_k=k,
                      excluded_document_ids=list(scope.excluded_document_ids))
        user_message = MessageRecord(**shared, sequence=allocation['next_message_sequence'],
                                     role='user', content=question, status='completed', completed_at=utc_now())
        assistant = MessageRecord(**shared, sequence=user_message.sequence+1, role='assistant', status='generating')
        await self.repositories.messages.insert(user_message)
        await self.repositories.messages.insert(assistant)
        recorder=EvaluationRecorder(question,dict(
            document_ids=[doc.id for doc in scope.documents],source_snapshot=[item.model_dump() for item in snapshot],
            embedding_profile=self.pipeline.embedding_profile,prompt_version=PROMPT_VERSION,
            scope_mode=scope_mode,strategy=strategy,k=k,document_set_version=scope.document_set_version),
            history=[{'role':m.role,'content':m.content} for m in history])
        log.info('qa.started',history_messages=len(history),scoped_document_ids=[doc.id for doc in scope.documents])
        try:
            result = await asyncio.to_thread(self.pipeline.answer,scope,question,history,k,recorder)
            qa_result = QAResult(**result.model_dump(), turn_id=turn_id, request_id=request_id,
                                 user_message_id=user_message.id, assistant_message_id=assistant.id,
                                 source_snapshot=snapshot,document_set_version=scope.document_set_version,
                                 scope_mode=scope_mode,strategy=strategy,
                                 excluded_document_ids=list(scope.excluded_document_ids))
            saved = await self.repositories.messages.update_owned(
                assistant.id, owner_id, content=result.answer, status='completed', completed_at=utc_now(),
                generation=result.generation.model_dump(mode='python'),
                retrieved_evidence=[item.model_dump(mode='python') for item in result.evidence],
                citations=[item.model_dump(mode='python') for item in result.citations],
                answerability=result.answerability,answer_warnings=result.warnings,retrieval_context_chars=result.context_chars)
            if not saved:
                raise WorkflowError('message_persistence_failed', 'The generated answer could not be saved')
            recorder.record['configuration'].update(result.generation.model_dump(exclude_none=True))
            recorder.finish(output=result.answer)
            log.info('qa.completed', turn=turn_id, retrieved_count=len(result.evidence))
            return qa_result
        except BaseException as error:
            cancelled = isinstance(error, asyncio.CancelledError)
            try:
                await self.repositories.messages.update_owned(assistant.id, owner_id,
                    status='cancelled' if cancelled else 'failed', completed_at=utc_now())
            except Exception:
                log.exception('qa.failure_persistence_failed', turn=turn_id)
            recorder.finish(status='aborted' if cancelled else 'failed', error_type=type(error).__name__)
            if cancelled:
                log.warning('qa.cancelled', turn=turn_id)
                raise
            if not isinstance(error, Exception):
                raise
            if isinstance(error,WorkflowError):
                log.warning('qa.answer_rejected',error_code=error.code,turn=turn_id)
                error.details=[{'turn_id':turn_id,'assistant_message_id':assistant.id}]
                raise
            log.exception('qa.failed', turn=turn_id)
            raise WorkflowError('generation_failed', 'Answer generation failed; check the request ID in the server logs',
                                [{'turn_id':turn_id,'assistant_message_id':assistant.id}]) from error
