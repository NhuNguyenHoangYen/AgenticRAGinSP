"""Durable document endpoints and scoped multi-document QA."""
from pathlib import Path

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from fastapi.responses import FileResponse

from src.api.dependencies import get_current_user, get_ingestion_service, get_qa_service, get_repositories
from src.api.errors import APIError
from src.api.schemas.workflows import (
    AskQuestionRequest, AttachmentChangeResponse, AttachDocumentRequest, BatchUploadResponse,
    JobResponse, UploadItem,
)
from src.document_validation import DocumentValidator
from src.observability import get_logger
from src.services.chat_service import ChatService
from src.services.contracts import QAResult
from src.services.errors import WorkflowError

router = APIRouter()
log = get_logger(__name__)


@router.post('/chats/{chat_id}/documents', response_model=BatchUploadResponse,
             status_code=status.HTTP_202_ACCEPTED, tags=['documents'])
async def upload_documents(chat_id: str, request: Request,
    files: list[UploadFile] | None = File(default=None), file: UploadFile | None = File(default=None),
    user=Depends(get_current_user), service=Depends(get_ingestion_service)):
    uploaded = list(files or []) + ([file] if file is not None else [])
    try:
        await service.require_active_chat(user.id, chat_id)
        form = await request.form()
        if (files and file) or not uploaded or not set(form.keys()) <= {'file','files'}:
            raise APIError(422,'invalid_upload_fields','Use repeated files fields, or one legacy file field')
        if len(uploaded) > service.settings.upload_max_files:
            raise APIError(422,'too_many_files',f'Upload at most {service.settings.upload_max_files} files per request')
        if file is not None and len(form.getlist('file')) != 1:
            raise APIError(422,'invalid_upload_fields','Use files for multiple uploads')
        items, total_bytes = [], 0
        for upload in uploaded:
            filename = Path(upload.filename or '').name
            try:
                if total_bytes >= service.settings.upload_batch_bytes:
                    raise WorkflowError('batch_too_large','No remaining upload budget in this batch')
                content = bytearray()
                while chunk := await upload.read(1024*1024):
                    total_bytes += len(chunk)
                    if total_bytes > service.settings.upload_batch_bytes:
                        raise WorkflowError('batch_too_large','Batch exceeds the configured upload size limit')
                    content.extend(chunk)
                    if len(content) > DocumentValidator.max_bytes:
                        raise WorkflowError('upload_too_large','File exceeds the 50 MiB limit')
                document, job, duplicate = await service.submit(user.id, chat_id, filename, bytes(content))
                items.append(UploadItem(filename=document.filename, document_id=document.id, job_id=job.id,
                                        status=job.status, deduplicated=duplicate,
                    error_code='document_failed' if job.status=='failed' else None,
                    error=job.error if job.status=='failed' else None))
            except WorkflowError as error:
                log.warning('upload.file_rejected', error_code=error.code)
                items.append(UploadItem(filename=filename,status='rejected',error_code=error.code,error=str(error)))
            except APIError:
                raise
            except Exception:
                log.exception('upload.submission_failed')
                items.append(UploadItem(filename=filename,status='rejected',error_code='submission_failed',
                                        error='Submission could not be completed; replay the upload to recover'))
        accepted = sum(item.document_id is not None for item in items)
        log.info('upload.batch_submitted', accepted=accepted,rejected=len(items)-accepted)
        return BatchUploadResponse(items=items,accepted=accepted,rejected=len(items)-accepted,
                                   request_id=request.state.request_id)
    finally:
        for upload in uploaded:
            await upload.close()


@router.post('/chats/{chat_id}/attachments',response_model=AttachmentChangeResponse,tags=['documents'])
async def attach_existing(chat_id: str,body: AttachDocumentRequest,
                          user=Depends(get_current_user),service=Depends(get_ingestion_service)):
    changed = await service.attach(user.id,chat_id,body.document_id)
    chat = await ChatService(service.repositories).get(user.id,chat_id)
    return AttachmentChangeResponse(document_id=body.document_id,changed=changed,
                                    document_set_version=chat.document_set_version)


@router.delete('/chats/{chat_id}/documents/{document_id}',response_model=AttachmentChangeResponse,tags=['documents'])
async def detach_document(chat_id: str,document_id: str,
                           user=Depends(get_current_user),service=Depends(get_ingestion_service)):
    changed = await service.detach(user.id,chat_id,document_id)
    chat = await ChatService(service.repositories).get(user.id,chat_id)
    return AttachmentChangeResponse(document_id=document_id,changed=changed,
                                    document_set_version=chat.document_set_version)


@router.get('/ingestion-jobs/{job_id}',response_model=JobResponse,tags=['ingestion'])
async def get_job(job_id: str,user=Depends(get_current_user),repositories=Depends(get_repositories)):
    job = await repositories.jobs.get_owned(job_id,user.id)
    if job is None:
        raise WorkflowError('job_not_found','Ingestion job not found')
    return job


@router.post('/ingestion-jobs/{job_id}/retry',response_model=JobResponse,
             status_code=status.HTTP_202_ACCEPTED,tags=['ingestion'])
async def retry_job(job_id: str,user=Depends(get_current_user),service=Depends(get_ingestion_service)):
    return await service.retry(user.id,job_id)


@router.get('/documents/{document_id}/content',tags=['documents'])
async def download_original(document_id: str,request: Request,
                             user=Depends(get_current_user),repositories=Depends(get_repositories)):
    document = await repositories.documents.get_owned(document_id,user.id)
    if document is None:
        raise WorkflowError('document_not_found','Document not found')
    try:
        path = request.app.state.storage.path_for_download(document.storage_key)
    except (FileNotFoundError,ValueError):
        raise WorkflowError('original_unavailable','Original file unavailable')
    log.info('document.original_downloaded', downloaded_document_id=document.id)
    return FileResponse(path,filename=document.filename,media_type='application/octet-stream',
                        headers={'X-Content-Type-Options':'nosniff'})


@router.post('/chats/{chat_id}/messages',response_model=QAResult,tags=['messages'])
async def ask_question(chat_id: str,body: AskQuestionRequest,
                       user=Depends(get_current_user),service=Depends(get_qa_service)):
    return await service.ask(user.id,chat_id,body.question,body.k,body.scope_mode,body.document_ids,body.strategy)
