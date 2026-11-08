"""Persisted conversation rendering and explicit per-question retrieval scope."""
import streamlit as st

from src.observability import get_logger
from src.ui.api_client import APIClientError
from src.ui.document_preview import render_preview, show_error

log = get_logger(__name__)


def render_conversation(client, chat_id, documents):
    st.subheader('Conversation')
    try:
        messages = client.messages(chat_id)
    except APIClientError as error:
        show_error(error)
        return
    for message in messages:
        with st.chat_message(message['role']):
            if message['content']:
                st.markdown(message['content'])
            if message['status'] != 'completed':
                st.warning(f"Answer status: {message['status']}. Refresh before resubmitting a question.")
            for warning in message.get('answer_warnings', []):
                st.warning(warning)
            if message.get('answerability') in ('partial', 'unanswerable'):
                st.caption(f"Answer coverage: {message['answerability']}")
            for index, citation in enumerate(message.get('citations', [])):
                location = f"page {citation['page']}" if citation.get('page') else citation.get('section') or 'Document text'
                with st.expander(f"[{citation['label']}] {citation['filename']} · {location}"):
                    st.caption(f"Document: {citation['document_id']} · index: {citation['index_version']}")
                    if not citation.get('attached', True):
                        st.caption('This document has been removed from the current chat.')
                    st.text(citation['quote'])
                    render_preview(client, citation['document_id'], citation['filename'],
                                   f"citation_{message['id']}_{index}", citation.get('page'))
    ready = {doc['document_id']: doc for doc in documents if doc['status'] == 'ready'}
    mode = st.radio('Use documents', ['All ready documents', 'Select documents'], key=f'scope_{chat_id}', horizontal=True)
    ids = []
    if mode == 'Select documents':
        selection_key = f'selected_{chat_id}'
        if selection_key in st.session_state:
            st.session_state[selection_key] = [doc_id for doc_id in st.session_state[selection_key] if doc_id in ready]
        ids = st.multiselect('Documents for this question', list(ready), key=selection_key,
                             format_func=lambda doc_id: f"{ready[doc_id]['filename']} ({doc_id[:12]})")
    strategy = st.selectbox('Question approach', ['general', 'comparison'], key=f'strategy_{chat_id}',
                            help='Comparison reserves evidence for each document in the chosen scope.')
    k = st.slider('Maximum evidence passages', 1, 20, 6, key=f'k_{chat_id}')
    count = len(ids) if mode == 'Select documents' else len(ready)
    blocked = not count or (strategy == 'comparison' and (count < 2 or k < count))
    if blocked:
        st.info('Choose ready documents. Comparison needs at least two documents and one evidence passage per document.')
    pending = any(message['status'] in ('pending', 'generating') for message in messages)
    query = st.chat_input('Ask about your documents…', disabled=blocked or pending, key=f'question_{chat_id}')
    if query:
        try:
            with st.spinner('Retrieving evidence and preparing the answer…'):
                result = client.ask(chat_id, query, 'selected' if mode == 'Select documents' else 'all_ready',
                                    ids, strategy, k)
            log.info('ui.answer_received', chat_id=chat_id, server_request_id=result['request_id'],
                     server_turn_id=result['turn_id'], citation_count=len(result['citations']))
            st.rerun()
        except APIClientError as error:
            show_error(error)
            st.info('Refresh the conversation to recover the saved turn. Requests are not automatically resubmitted.')
