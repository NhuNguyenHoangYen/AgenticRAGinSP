"""Attachment controls. Membership and processing state are always backend-owned."""
import streamlit as st

from src.observability import get_logger
from src.ui.api_client import APIClientError
from src.ui.document_preview import render_preview, show_error

log = get_logger(__name__)


def render_documents(client, chat_id, documents):
    st.subheader('Documents')
    files = st.file_uploader('Choose documents', type=['pdf', 'docx', 'txt', 'md', 'csv'],
                             accept_multiple_files=True, key=f'uploads_{chat_id}')
    st.caption('Up to 10 files / 100 MiB per batch, 50 MiB each. Files need extractable text.')
    if st.button('Add selected files', disabled=not files, key=f'add_{chat_id}'):
        if len(files) > 10 or any(file.size > 50*1024*1024 for file in files) or sum(f.size for f in files) > 100*1024*1024:
            st.error('Choose at most 10 files, 50 MiB each and 100 MiB in total.')
        else:
            try:
                result = client.upload(chat_id, files)
                st.session_state[f'receipts_{chat_id}'] = result['items']
                log.info('ui.upload_submitted', chat_id=chat_id, accepted=result['accepted'], rejected=result['rejected'])
                st.rerun()
            except APIClientError as error:
                show_error(error)
    for item in st.session_state.get(f'receipts_{chat_id}', []):
        st.caption(f"Submission receipt — {item['filename']}: {item['status']}" + (' (already uploaded)' if item.get('deduplicated') else ''))
        if item.get('error'):
            st.warning(item['error'])
    if not documents:
        st.info('Add documents to this chat to get started.')
    for document in documents:
        doc_id = document['document_id']
        with st.expander(f"{document['filename']} — {document['status']}"):
            st.caption(f"Document: {doc_id}")
            if document.get('chunk_count') is not None:
                st.caption(f"Passages: {document['chunk_count']}")
            for warning in document.get('warnings', []):
                st.warning(warning)
            job_id = document.get('ingestion_job_id')
            if job_id and document['status'] != 'ready':
                try:
                    job = client.job(job_id)
                    st.caption(f"{job['stage']} · attempt {job['attempt']}/{job['max_attempts']}")
                    if job['total']:
                        st.progress(min(1., job['completed']/job['total']))
                    if job.get('error'):
                        st.warning(job['error'])
                    if job['status'] == 'failed' and not job['non_retryable']:
                        if st.button('Retry processing', key=f'retry_{chat_id}_{doc_id}'):
                            client.retry(job_id)
                            log.info('ui.job_retry_requested', chat_id=chat_id, target_document_id=doc_id)
                            st.rerun()
                except APIClientError as error:
                    show_error(error)
            if document.get('processing_error'):
                st.warning(document['processing_error'])
            render_preview(client, doc_id, document['filename'], f'attachment_{chat_id}_{doc_id}')
            st.caption('Remove detaches this document; previous citations and originals are retained.')
            if st.button('Remove from chat', key=f'remove_{chat_id}_{doc_id}'):
                try:
                    client.detach(chat_id, doc_id)
                    log.info('ui.document_detached', chat_id=chat_id, target_document_id=doc_id)
                    st.rerun()
                except APIClientError as error:
                    show_error(error)
