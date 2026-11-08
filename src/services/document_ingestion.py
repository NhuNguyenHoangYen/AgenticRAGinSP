"""Durable upload submission and chat attachments; parsing runs in the worker."""
import asyncio
import hashlib
from uuid import NAMESPACE_URL, uuid5

from src.document_validation import DocumentValidationError, DocumentValidator
from src.models.records import DocumentRecord, IndexMetadata, IngestionJobRecord
from src.observability import get_logger
from src.observability.context import context_fields
from src.services.chat_service import ChatService
from src.services.errors import WorkflowError
from src.services.rag_pipeline import PARSER_VERSION, CHUNKER_VERSION

log = get_logger(__name__)


def make_job(document, settings, chat_id=None, request_id=None):
    index = document.index
    return IngestionJobRecord(
        id=document.ingestion_job_id, owner_id=document.owner_id, document_id=document.id,
        request_id=request_id or document.submission_request_id, chat_id=chat_id or document.submission_chat_id, max_attempts=settings.ingestion_max_attempts,
        embedding_profile=index.embedding_profile, collection=index.collection,
        parser_version=index.parser_version, chunker_version=index.chunker_version)


class DocumentIngestionService:
    def __init__(self, repositories, storage, pipeline, settings):
        self.repositories, self.storage, self.pipeline, self.settings = repositories, storage, pipeline, settings

    async def require_active_chat(self, owner_id, chat_id):
        chat = await ChatService(self.repositories).get(owner_id, chat_id)
        if chat.status != 'active':
            raise WorkflowError('chat_not_active', 'Chat is not active')
        return chat

    async def attach(self, owner_id, chat_id, document_id):
        await self.require_active_chat(owner_id, chat_id)
        document = await self.repositories.documents.get_owned(document_id, owner_id)
        if document is None:
            raise WorkflowError('document_not_found', 'Document not found')
        changed = await self.repositories.chats.attach(chat_id, owner_id, document_id)
        current = await self.require_active_chat(owner_id, chat_id)
        if document_id not in current.document_ids:
            raise WorkflowError('attachment_limit', 'The chat supports at most 100 attached documents')
        try:
            await self.repositories.attachments.project_attachment(chat_id, owner_id, document_id, refresh=changed)
        except Exception:
            # Replay repairs missing metadata; membership/version remain authoritative.
            log.exception('attachment.metadata_projection_failed', attached_document_id=document_id)
        if document.ingestion_job_id:
            await self.repositories.jobs.enable(document.ingestion_job_id,owner_id)
        log.info('document.attached', attached_document_id=document_id, changed=changed,
                 document_set_version=current.document_set_version)
        return changed

    async def detach(self, owner_id, chat_id, document_id):
        await self.require_active_chat(owner_id, chat_id)
        if await self.repositories.documents.get_owned(document_id, owner_id) is None:
            raise WorkflowError('document_not_found', 'Document not found')
        changed = await self.repositories.chats.detach(chat_id, owner_id, document_id)
        try:
            await self.repositories.attachments.remove_for_document(chat_id, owner_id, document_id)
        except Exception:
            log.exception('attachment.metadata_cleanup_failed', detached_document_id=document_id)
        log.info('document.detached', detached_document_id=document_id, changed=changed)
        return changed

    async def submit(self, owner_id, chat_id, filename, content):
        chat = await self.require_active_chat(owner_id, chat_id)
        try:
            filename, extension = DocumentValidator().validate_upload(content, filename)
        except DocumentValidationError as error:
            raise WorkflowError('invalid_document', str(error)) from error
        digest = hashlib.sha256(content).hexdigest()
        fingerprint = '|'.join((owner_id, digest, extension, self.pipeline.embedding_profile,
                                self.pipeline.collection, PARSER_VERSION, CHUNKER_VERSION))
        dedup_key = hashlib.sha256(fingerprint.encode()).hexdigest()
        identifier = uuid5(NAMESPACE_URL, 'agentic-rag-document:' + dedup_key).hex
        if len(chat.document_ids)>=100 and identifier not in chat.document_ids:
            raise WorkflowError('attachment_limit','The chat supports at most 100 attached documents')
        job_id = uuid5(NAMESPACE_URL, 'agentic-rag-job:' + dedup_key).hex
        document = await self.repositories.documents.get_owned(identifier, owner_id)
        duplicate = document is not None
        if document is None:
            key = await asyncio.to_thread(self.storage.save_once, identifier, extension, content)
            index = IndexMetadata(collection=self.pipeline.collection,
                embedding_profile=self.pipeline.embedding_profile, parser_version=PARSER_VERSION,
                chunker_version=CHUNKER_VERSION, index_version=uuid5(NAMESPACE_URL, dedup_key).hex)
            document, created = await self.repositories.documents.ensure(DocumentRecord(
                id=identifier, owner_id=owner_id, filename=filename, content_hash=digest,
                file_type=extension, size_bytes=len(content), storage_key=key,
                dedup_key=dedup_key, ingestion_job_id=job_id, index=index,
                submission_request_id=context_fields().get('request_id'), submission_chat_id=chat_id))
            duplicate = not created
        if document is None:
            raise WorkflowError('ingestion_failed', 'Document submission could not be persisted')
        job = await self.repositories.jobs.ensure(make_job(document, self.settings, chat_id,
                                                          context_fields().get('request_id')))
        await self.attach(owner_id, chat_id, document.id)
        log.info('ingestion.queued', queued_document_id=document.id, job_id=job.id,
                 reused=duplicate, job_status=job.status)
        return document, job, duplicate

    async def retry(self, owner_id, job_id):
        job = await self.repositories.jobs.get_owned(job_id, owner_id)
        if job is None:
            raise WorkflowError('job_not_found', 'Ingestion job not found')
        if job.status != 'failed' or job.non_retryable:
            raise WorkflowError('job_not_retryable', 'Retry failed processing jobs after resolving the cause; upload corrected content for invalid files')
        retried = await self.repositories.jobs.retry_failed(job, self.settings.ingestion_max_attempts)
        if retried is None:
            raise WorkflowError('job_not_retryable', 'Job state changed; refresh its status')
        await self.repositories.documents.update_owned(job.document_id, owner_id,
            status='uploaded', processing_error=None)
        log.info('ingestion.retry_requested', job_id=job.id, queued_document_id=job.document_id)
        return retried
