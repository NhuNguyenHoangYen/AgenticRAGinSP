"""Chat foundation workflows, independent of FastAPI and Streamlit rendering."""
from src.services.errors import AttachmentInconsistent, ChatNotFound, WorkflowError
from src.models.records import ChatRecord
from src.observability import get_logger

log = get_logger(__name__)


class ChatService:
    def __init__(self, repositories):
        self.repositories = repositories

    async def create(self, owner_id, title):
        with log.operation("chat.create"):
            chat = await self.repositories.chats.insert(ChatRecord(owner_id=owner_id, title=title))
        log.info("chat.created", created_chat_id=chat.id)
        return chat

    async def list(self, owner_id, limit, offset, status="active"):
        with log.operation("chat.list", limit=limit, offset=offset):
            items, total = await self.repositories.chats.list_owned(owner_id, limit, offset, status)
        log.info("chat.listed", returned_count=len(items), total=total)
        return items, total

    async def get(self, owner_id, chat_id):
        chat = await self.repositories.chats.get_visible(chat_id, owner_id)
        if chat is None:
            # Do not reveal whether another owner has a matching chat.
            raise ChatNotFound()
        log.debug("chat.loaded", loaded_chat_id=chat.id)
        return chat

    async def rename(self, owner_id, chat_id, title):
        chat = await self.repositories.chats.update_active_title(chat_id, owner_id, title)
        if chat is None:
            await self.get(owner_id, chat_id)
            raise WorkflowError("chat_not_active", "Restore the chat before renaming it")
        log.info("chat.renamed", renamed_chat_id=chat_id)
        return chat

    async def set_archived(self, owner_id, chat_id, archived):
        expected, target = ("active", "archived") if archived else ("archived", "active")
        chat = await self.repositories.chats.transition(chat_id, owner_id, expected, target)
        if chat is not None:
            log.info("chat.status_changed", changed_chat_id=chat_id, status=target)
            return chat
        chat = await self.get(owner_id, chat_id)
        if chat.status == target:
            return chat
        raise WorkflowError("chat_status_conflict", "The chat status changed. Refresh and try again.")

    async def messages(self, owner_id, chat_id, limit, offset):
        chat=await self.get(owner_id,chat_id)
        with log.operation("chat.messages_list", limit=limit, offset=offset):
            items, total = await self.repositories.messages.list_for_chat(chat_id, owner_id, limit, offset)
        log.info("chat.messages_listed", returned_count=len(items), total=total)
        views=[{**message.model_dump(), 'citations':[
            {**citation.model_dump(),'attached':citation.document_id in chat.document_ids}
            for citation in message.citations]} for message in items]
        return views,total

    async def documents(self, owner_id, chat_id, limit, offset):
        await self.get(owner_id, chat_id)
        log.info("chat.documents_list_started", limit=limit, offset=offset)
        attachments, total = await self.repositories.attachments.list_for_chat(chat_id, owner_id, limit, offset)
        documents = await self.repositories.documents.get_many_owned(
            [item.document_id for item in attachments], owner_id)
        items = []
        for attachment in attachments:
            document = documents.get(attachment.document_id)
            if document is None:
                raise AttachmentInconsistent()
            items.append(dict(
                attachment_id=attachment.id, document_id=document.id, filename=document.filename,
                file_type=document.file_type, status=document.status,
                chunk_count=document.index.chunk_count if document.index else None,
                attached_at=attachment.created_at, ingestion_job_id=document.ingestion_job_id,
                processing_error=document.processing_error, warnings=document.warnings,
                embedding_profile=document.index.embedding_profile if document.index else None,
                index_version=document.index.index_version if document.index else None,
            ))
        log.info("chat.documents_listed", returned_count=len(items), total=total)
        return items, total
