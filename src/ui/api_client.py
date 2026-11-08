"""HTTP transport boundary. Never retry a mutation with an uncertain outcome."""
import os
from uuid import uuid4

import httpx

from src.observability import get_logger, RequestContext, request_context

log = get_logger(__name__)


class APIClientError(Exception):
    def __init__(self, message, code='connection_failed', request_id=None):
        super().__init__(message)
        self.code = code
        self.request_id = request_id


class APIClient:
    def __init__(self, base_url=None, transport=None):
        self.base_url = (base_url or os.getenv('API_BASE_URL', 'http://127.0.0.1:8000')).rstrip('/')
        self.transport = transport

    def request(self, method, path, *, binary=False, **kwargs):
        correlation = uuid4().hex
        parts = path.split('/')
        chat_id = parts[4] if path.startswith('/api/v1/chats/') and len(parts) > 4 else None
        context = RequestContext(user_id='development-ui', chat_id=chat_id, request_id=correlation)
        try:
            with request_context(context), log.operation('ui.api_request', method=method, endpoint=path,
                               client_request_id=correlation):
                with httpx.Client(base_url=self.base_url, transport=self.transport,
                                  timeout=httpx.Timeout(180, connect=5), follow_redirects=False) as client:
                    response = client.request(method, path, headers={'X-Client-Request-ID': correlation}, **kwargs)
        except httpx.RequestError:
            log.warning('ui.api_unavailable', client_request_id=correlation, method=method)
            message = 'Cannot reach the API. Check that FastAPI is running, then refresh.'
            if method != 'GET':
                message += ' The outcome is unknown; refresh documents and conversation before submitting again.'
            raise APIClientError(message) from None
        request_id = response.headers.get('X-Request-ID')
        if not response.is_success:
            try:
                payload = response.json()
                error = payload.get('error', {})
                message = error.get('message', 'The API rejected this request.')
                code = error.get('code', 'api_error')
                request_id = payload.get('request_id') or request_id
            except (ValueError, AttributeError):
                message, code = 'The API returned an unexpected error.', 'api_error'
            emit = log.error if response.status_code >= 500 else log.warning
            emit('ui.api_rejected', status_code=response.status_code, error_code=code,
                        server_request_id=request_id, client_request_id=correlation)
            raise APIClientError(message, code, request_id)
        if binary:
            return response.content
        try:
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError('Expected an object')
            return payload
        except ValueError:
            raise APIClientError('The API returned an invalid response.', 'invalid_response', request_id) from None

    def items(self, path):
        """Read paginated records without silently truncating at the first page."""
        result, offset = [], 0
        while True:
            page = self.request('GET', path, params={'limit': 100, 'offset': offset})
            batch = page['items']
            result.extend(batch)
            offset += len(batch)
            if offset >= page['total'] or not batch:
                return result
            if offset > 10000:
                raise APIClientError('History exceeds the current API pagination limit.', 'pagination_limit')

    def chats(self):
        return self.items('/api/v1/chats')

    def create_chat(self, title):
        return self.request('POST', '/api/v1/chats', json={'title': title})

    def documents(self, chat_id):
        return self.items(f'/api/v1/chats/{chat_id}/documents')

    def messages(self, chat_id):
        return self.items(f'/api/v1/chats/{chat_id}/messages')

    def upload(self, chat_id, files):
        return self.request('POST', f'/api/v1/chats/{chat_id}/documents', files=[
            ('files', (file.name, file.getvalue(), 'application/octet-stream')) for file in files])

    def job(self, job_id):
        return self.request('GET', f'/api/v1/ingestion-jobs/{job_id}')

    def retry(self, job_id):
        return self.request('POST', f'/api/v1/ingestion-jobs/{job_id}/retry')

    def detach(self, chat_id, document_id):
        return self.request('DELETE', f'/api/v1/chats/{chat_id}/documents/{document_id}')

    def content(self, document_id):
        return self.request('GET', f'/api/v1/documents/{document_id}/content', binary=True)

    def ask(self, chat_id, question, scope_mode, document_ids, strategy, k):
        return self.request('POST', f'/api/v1/chats/{chat_id}/messages', json={
            'question': question, 'scope_mode': scope_mode, 'document_ids': document_ids,
            'strategy': strategy, 'k': k})
