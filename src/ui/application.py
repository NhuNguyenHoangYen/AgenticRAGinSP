"""UI composition and transient session/navigation state."""
from pathlib import Path

import streamlit as st

from src.observability import RequestContext, request_context
from src.ui.api_client import APIClient, APIClientError
from src.ui.conversation import render_conversation
from src.ui.document_panel import render_documents
from src.ui.document_preview import show_error


@st.fragment(run_every='4s')
def poll_documents(client, chat_id, previous):
    """Only refresh the full UI when persisted attachment status changes."""
    try:
        current = client.documents(chat_id)
        signature = [(d['document_id'], d['status']) for d in current]
        if signature != previous:
            st.rerun()
        pending = [d for d in current if d['status'] not in ('ready', 'failed')]
        if pending:
            st.caption('Processing documents… Status refreshes every four seconds. The ingestion worker must be running.')
        for document in pending:
            if document.get('ingestion_job_id'):
                job = client.job(document['ingestion_job_id'])
                st.caption(f"{document['filename']}: {job['stage']} · attempt {job['attempt']}")
                if job['total']:
                    st.progress(min(1., job['completed']/job['total']))
    except APIClientError as error:
        show_error(error)


def select_chat():
    st.query_params['chat'] = st.session_state['active_chat']
    st.session_state.pop('loaded_original', None)


def run():
    st.set_page_config(page_title='Document Chatbot', page_icon='📚', layout='wide')
    style = Path(__file__).resolve().parents[1] / 'style.css'
    if style.exists():
        st.markdown(f'<style>{style.read_text()}</style>', unsafe_allow_html=True)
    st.title('Document Chatbot')
    st.caption('Ask evidence-based questions across documents in a chat.')
    client = APIClient()
    try:
        chats = client.chats()
    except APIClientError as error:
        show_error(error)
        st.info('Start FastAPI and the ingestion worker. API_BASE_URL sets the backend address.')
        st.button('Reconnect')
        return
    with st.sidebar:
        st.header('Chats')
        st.caption('Development identity: chats are shared by this backend identity. User sign-in is not implemented.')
        with st.form('new_chat'):
            title = st.text_input('Chat title', value='New chat', max_chars=120)
            create = st.form_submit_button('Create chat')
        if create:
            try:
                chat = client.create_chat(title.strip() or 'New chat')
                st.query_params['chat'] = chat['id']
                st.session_state['active_chat'] = chat['id']
                st.rerun()
            except APIClientError as error:
                show_error(error)
        if not chats:
            st.info('Create a chat to begin.')
            return
        lookup = {chat['id']: chat for chat in chats}
        requested = st.query_params.get('chat')
        if requested in lookup and st.session_state.get('active_chat') != requested:
            st.session_state['active_chat'] = requested
        if st.session_state.get('active_chat') not in lookup:
            st.session_state['active_chat'] = chats[0]['id']
        chat_id = st.selectbox('Open chat', list(lookup), key='active_chat',
                               format_func=lambda value: f"{lookup[value]['title']} ({value[:8]})", on_change=select_chat)
        st.query_params['chat'] = chat_id
        st.button('Refresh documents and conversation')
    try:
        documents = client.documents(chat_id)
    except APIClientError as error:
        show_error(error)
        return
    left, right = st.columns([1, 2])
    with request_context(RequestContext.create('development-ui', chat_id)), left:
        render_documents(client, chat_id, documents)
        poll_documents(client, chat_id, [(d['document_id'], d['status']) for d in documents])
    with request_context(RequestContext.create('development-ui', chat_id)), right:
        render_conversation(client, chat_id, documents)
