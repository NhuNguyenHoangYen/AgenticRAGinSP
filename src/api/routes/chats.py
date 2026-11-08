"""Thin chat routes; document upload and generation arrive in later milestones."""
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from src.api.dependencies import get_chat_service, get_current_user
from src.api.schemas.foundation import (
    ChatPage, ChatResponse, CreateChatRequest, DocumentPage, MessagePage, UserResponse,
)

router = APIRouter()
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=10000)]


@router.get("/users/me", response_model=UserResponse, tags=["identity"])
async def current_user(user=Depends(get_current_user)):
    return user


@router.post("/chats", response_model=ChatResponse, status_code=status.HTTP_201_CREATED, tags=["chats"])
async def create_chat(body: CreateChatRequest, user=Depends(get_current_user), service=Depends(get_chat_service)):
    chat = await service.create(user.id, body.title)
    return chat


@router.get("/chats", response_model=ChatPage, tags=["chats"])
async def list_chats(limit: Limit = 20, offset: Offset = 0,
                     user=Depends(get_current_user), service=Depends(get_chat_service)):
    items, total = await service.list(user.id, limit, offset)
    return dict(items=items, total=total, limit=limit, offset=offset)


@router.get("/chats/{chat_id}", response_model=ChatResponse, tags=["chats"])
async def get_chat(chat_id: str, user=Depends(get_current_user), service=Depends(get_chat_service)):
    return await service.get(user.id, chat_id)


@router.get("/chats/{chat_id}/messages", response_model=MessagePage, tags=["messages"])
async def list_messages(chat_id: str, limit: Limit = 50, offset: Offset = 0,
                        user=Depends(get_current_user), service=Depends(get_chat_service)):
    items, total = await service.messages(user.id, chat_id, limit, offset)
    return dict(items=items, total=total, limit=limit, offset=offset)


@router.get("/chats/{chat_id}/documents", response_model=DocumentPage, tags=["documents"])
async def list_documents(chat_id: str, limit: Limit = 20, offset: Offset = 0,
                         user=Depends(get_current_user), service=Depends(get_chat_service)):
    items, total = await service.documents(user.id, chat_id, limit, offset)
    return dict(items=items, total=total, limit=limit, offset=offset)
