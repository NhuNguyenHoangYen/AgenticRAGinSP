"""Per-request identity and service injection. No frontend-supplied owner IDs."""
from fastapi import Depends, Request

from src.api.errors import APIError
from src.services.chat_service import ChatService


def get_repositories(request: Request):
    return request.app.state.repositories


async def get_current_user(request: Request, repositories=Depends(get_repositories)):
    user = await repositories.users.get(request.app.state.settings.development_user_id)
    if user is None:
        raise APIError(401, "identity_unavailable", "Development identity is unavailable or disabled")
    return user


def get_chat_service(repositories=Depends(get_repositories)):
    return ChatService(repositories)


def get_ingestion_service(request: Request, repositories=Depends(get_repositories)):
    from src.services.document_ingestion import DocumentIngestionService
    return DocumentIngestionService(repositories, request.app.state.storage, request.app.state.pipeline, request.app.state.settings)


def get_qa_service(request: Request, repositories=Depends(get_repositories)):
    from src.services.qa_service import QAService
    return QAService(repositories, request.app.state.pipeline)
