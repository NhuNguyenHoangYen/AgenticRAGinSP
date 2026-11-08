"""Explicit, bounded PDF previews and original-file downloads via the API."""
import streamlit as st

from src.ui.api_client import APIClientError


def show_error(error):
    st.error(str(error))
    if error.request_id:
        st.caption(f'Request ID: {error.request_id}')


def render_preview(client, document_id, filename, key, page=None):
    # No automatic downloads or large PDF payloads in the browser websocket.
    if st.button('Load original file', key=f'load_{key}'):
        try:
            content = client.content(document_id)
        except APIClientError as error:
            show_error(error)
            return
        st.session_state['loaded_original'] = {'key': key, 'content': content}
    loaded = st.session_state.get('loaded_original', {})
    if loaded.get('key') == key:
        content = loaded['content']
        st.download_button('Download original', content, file_name=filename, key=f'download_{key}')
        if filename.lower().endswith('.pdf'):
            if len(content) > 10 * 1024 * 1024:
                st.info('Download this PDF to view it; inline preview is limited to 10 MiB.')
                return
            try:
                from streamlit_pdf_viewer import pdf_viewer
                pdf_viewer(input=content, height=450, pages_to_render=[page or 1],
                           resolution_boost=1, key=f'pdf_{key}')
            except Exception:
                from src.observability import get_logger
                get_logger(__name__).exception('ui.preview_failed', target_document_id=document_id)
                st.warning('Preview unavailable. Use the original-file download instead.')
