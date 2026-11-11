"""Typed persistence operations. Services enforce parent ownership and workflows."""
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from datetime import timedelta
from uuid import uuid4, uuid5, NAMESPACE_URL
from src.observability import get_logger

log = get_logger(__name__)

from src.models.records import (
    ChatDocumentRecord, ChatRecord, DocumentRecord, IngestionJobRecord,
    MessageRecord, UserRecord, utc_now,
)


class RecordRepository:
    model = None
    collection_name = ""

    def __init__(self, database):
        self.collection = database[self.collection_name]

    async def insert(self, record):
        if not isinstance(record, self.model):
            raise TypeError(f"Expected {self.model.__name__}")
        with log.operation("mongodb.record_insert", collection=self.collection_name, record_id=record.id):
            await self.collection.insert_one(record.model_dump(mode="python", by_alias=True))
        return record

    async def get_owned(self, record_id, owner_id):
        data = await self.collection.find_one({"_id": record_id, "owner_id": owner_id})
        return self.model.model_validate(data) if data else None

    async def update_owned(self, record_id, owner_id, **fields):
        immutable = {"id", "_id", "owner_id", "created_at"}
        if immutable.intersection(fields) or not set(fields).issubset(self.model.model_fields):
            raise ValueError("Invalid record update")
        fields["updated_at"] = utc_now()
        result = await self.collection.update_one(
            {"_id": record_id, "owner_id": owner_id}, {"$set": fields})
        log.debug("mongodb.record_updated", collection=self.collection_name,
                  record_id=record_id, matched=result.matched_count)
        return result.matched_count == 1


class UserRepository(RecordRepository):
    model = UserRecord
    collection_name = "users"

    async def ensure_development_user(self, settings):
        user = UserRecord(id=settings.development_user_id, auth_subject=settings.development_user_id,
                          display_name=settings.development_user_name)
        log.info("identity.bootstrap_started", identity_mode="development")
        result = await self.collection.update_one(
            {"_id": user.id}, {"$setOnInsert": user.model_dump(mode="python", by_alias=True)}, upsert=True,
        )
        stored = UserRecord.model_validate(await self.collection.find_one({"_id": user.id}))
        if stored.auth_provider != "development" or stored.auth_subject != user.auth_subject or stored.status != "active":
            raise ValueError("DEV_USER_ID conflicts with an existing or disabled identity")
        log.info("identity.bootstrap_completed", identity_mode="development", created=result.upserted_id is not None)
        return stored

    async def get(self, user_id):
        data = await self.collection.find_one({"_id": user_id, "status": "active"})
        return UserRecord.model_validate(data) if data else None


class ChatRepository(RecordRepository):
    model = ChatRecord
    collection_name = "chats"

    async def get_visible(self, chat_id, owner_id):
        query = {"_id": chat_id, "owner_id": owner_id, "status": {"$ne": "deleted"}}
        data = await self.collection.find_one(query)
        if data is None:
            return None
        if not data.get("membership_initialized"):
            # One-time migration of B attachments; restart old API writers before C.
            attachments = [item async for item in self.collection.database.chat_documents.find(
                {"chat_id": chat_id, "owner_id": owner_id}).sort([("created_at", 1), ("_id", 1)]).limit(101)]
            ids = list(dict.fromkeys(item['document_id'] for item in attachments))
            if len(ids) > 100:
                raise ValueError("Chat exceeds the supported attachment limit; explicit migration required")
            migrated = await self.collection.find_one_and_update(
                {**query, "membership_initialized": {"$ne": True}},
                {"$set": {"document_ids": ids, "membership_initialized": True}},
                return_document=ReturnDocument.AFTER)
            data = migrated or await self.collection.find_one(query)
            log.info("chat.membership_migrated", migrated_chat_id=chat_id, document_count=len(ids))
        return ChatRecord.model_validate(data) if data else None

    async def attach(self, chat_id, owner_id, document_id):
        await self.get_visible(chat_id, owner_id)
        result = await self.collection.update_one(
            {"_id": chat_id, "owner_id": owner_id, "status": "active", "document_ids": {"$ne": document_id},
             "$expr": {"$lt": [{"$size": "$document_ids"}, 100]}},
            {"$addToSet": {"document_ids": document_id}, "$inc": {"document_set_version": 1},
             "$set": {"updated_at": utc_now()}})
        return result.modified_count == 1

    async def detach(self, chat_id, owner_id, document_id):
        await self.get_visible(chat_id, owner_id)
        result = await self.collection.update_one(
            {"_id": chat_id, "owner_id": owner_id, "status": "active", "document_ids": document_id},
            {"$pull": {"document_ids": document_id}, "$inc": {"document_set_version": 1},
             "$set": {"updated_at": utc_now()}})
        return result.modified_count == 1

    async def list_owned(self, owner_id, limit, offset, status="active"):
        query = {"owner_id": owner_id, "status": status}
        cursor = self.collection.find(query).sort([("updated_at", -1), ("_id", -1)]).skip(offset).limit(limit)
        chats = []
        async for item in cursor:
            chat = await self.get_visible(item["_id"], owner_id)
            if chat is not None and chat.status == status:
                chats.append(chat)
        return chats, await self.collection.count_documents(query)

    async def update_active_title(self, chat_id, owner_id, title):
        data = await self.collection.find_one_and_update(
            {"_id": chat_id, "owner_id": owner_id, "status": "active"},
            {"$set": {"title": title, "updated_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )
        return ChatRecord.model_validate(data) if data else None

    async def transition(self, chat_id, owner_id, expected, target):
        data = await self.collection.find_one_and_update(
            {"_id": chat_id, "owner_id": owner_id, "status": expected},
            {"$set": {"status": target, "updated_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )
        return ChatRecord.model_validate(data) if data else None

    async def has_active_attachment(self, owner_id, document_id):
        return await self.collection.find_one(
            {"owner_id": owner_id, "status": "active", "document_ids": document_id},
            projection={"_id": 1},
        ) is not None

    async def allocate_message_sequence(self, chat_id, owner_id):
        """Atomic allocation; gaps after a failed write are valid, duplicates are not."""
        data = await self.collection.find_one_and_update(
            {"_id": chat_id, "owner_id": owner_id, "status": "active"},
            {"$inc": {"next_message_sequence": 1}}, return_document=ReturnDocument.BEFORE,
        )
        log.debug("chat.sequence_allocated", allocated_chat_id=chat_id, found=data is not None)
        return data["next_message_sequence"] if data else None

    async def reserve_document(self, chat_id, owner_id, document_id):
        result = await self.collection.update_one(
            {"_id": chat_id, "owner_id": owner_id, "status": "active", "active_document_id": None},
            {"$set": {"active_document_id": document_id, "updated_at": utc_now()}})
        return result.modified_count == 1

    async def release_document(self, chat_id, owner_id, document_id):
        await self.collection.update_one(
            {"_id": chat_id, "owner_id": owner_id, "active_document_id": document_id},
            {"$set": {"active_document_id": None, "updated_at": utc_now()}})

    async def document_attached(self, chat_id, owner_id, document_id):
        result = await self.collection.update_one(
            {"_id": chat_id, "owner_id": owner_id, "active_document_id": document_id},
            {"$inc": {"document_set_version": 1}, "$set": {"updated_at": utc_now()}})
        return result.matched_count == 1

    async def allocate_turn(self, chat_id, owner_id):
        return await self.collection.find_one_and_update(
            {"_id": chat_id, "owner_id": owner_id, "status": "active"},
            {"$inc": {"next_message_sequence": 2}, "$set": {"updated_at": utc_now()}},
            return_document=ReturnDocument.BEFORE)


class MessageRepository(RecordRepository):
    model = MessageRecord
    collection_name = "messages"

    async def list_for_chat(self, chat_id, owner_id, limit, offset):
        query = {"chat_id": chat_id, "owner_id": owner_id}
        cursor = self.collection.find(query).sort("sequence", 1).skip(offset).limit(limit)
        return [MessageRecord.model_validate(item) async for item in cursor], await self.collection.count_documents(query)

    async def history(self, chat_id, owner_id):
        cursor = self.collection.find({"chat_id": chat_id, "owner_id": owner_id, "status": "completed"}).sort("sequence", -1).limit(40)
        records = [MessageRecord.model_validate(item) async for item in cursor]
        answered = {item.turn_id for item in records if item.role == "assistant"}
        history, remaining = [], 40000
        for item in records:
            if item.turn_id not in answered:
                continue
            if len(item.content) > remaining:
                break
            history.append(item)
            remaining -= len(item.content)
        # Retain only full question/answer pairs in the bounded history.
        user_turns = {item.turn_id for item in history if item.role == "user"}
        return list(reversed([item for item in history if item.turn_id in user_turns]))


class DocumentRepository(RecordRepository):
    model = DocumentRecord
    collection_name = "documents"

    async def list_reusable(self, owner_id, profile, limit, offset):
        query = {"owner_id": owner_id, "status": "ready", "index.embedding_profile": profile}
        cursor = self.collection.find(query).sort(
            [("created_at", -1), ("_id", -1)]
        ).skip(offset).limit(limit)
        return [DocumentRecord.model_validate(item) async for item in cursor], await self.collection.count_documents(query)

    async def get_many_owned(self, document_ids, owner_id):
        cursor = self.collection.find({"_id": {"$in": document_ids}, "owner_id": owner_id})
        return {item["_id"]: DocumentRecord.model_validate(item) async for item in cursor}

    async def ensure(self, document):
        created = False
        try:
            result = await self.collection.update_one({"_id": document.id},
                {"$setOnInsert": document.model_dump(mode="python", by_alias=True)}, upsert=True)
            created = result.upserted_id is not None
        except DuplicateKeyError:
            pass
        return await self.get_owned(document.id, document.owner_id), created

    async def prepare_attempt(self, job):
        return (await self.collection.update_one(
            {"_id": job.document_id, "owner_id": job.owner_id, "ingestion_job_id": job.id,
             "status": {"$ne": "ready"}, "$or": [{"processing_attempt": {"$lt": job.attempt}},
                                                    {"processing_attempt": {"$exists": False}}]},
            {"$set": {"processing_attempt": job.attempt, "processing_token": job.lease_token,
                      "status": "validating", "processing_error": None, "updated_at": utc_now()}})).modified_count == 1

    async def attempt_update(self, job, **fields):
        fields['updated_at'] = utc_now()
        return (await self.collection.update_one(
            {"_id": job.document_id, "owner_id": job.owner_id, "ingestion_job_id": job.id,
             "processing_token": job.lease_token, "status": {"$ne": "ready"}}, {"$set": fields})).matched_count == 1

    async def finalize_job(self, job):
        status = 'ready' if job.status == 'succeeded' else 'failed'
        result = await self.collection.update_one(
            {"_id": job.document_id, "owner_id": job.owner_id, "ingestion_job_id": job.id,
             "status": {"$nin": list({status, "ready", "deleting"})}, "processing_attempt": {"$lte": job.attempt}},
            {"$set": {"status": status, "processing_error": None if status == 'ready' else job.error,
                      "warnings": job.warnings, "processing_token": None, "updated_at": utc_now()}})
        return result.modified_count == 1


class AttachmentRepository(RecordRepository):
    model = ChatDocumentRecord
    collection_name = "chat_documents"

    async def list_for_chat(self, chat_id, owner_id, limit, offset):
        chat = await ChatRepository(self.collection.database).get_visible(chat_id, owner_id)
        if chat is None:
            return [], 0
        ids = chat.document_ids[offset:offset+limit]
        records = {item['document_id']: ChatDocumentRecord.model_validate(item)
                   async for item in self.collection.find({"chat_id": chat_id, "owner_id": owner_id,
                                                           "document_id": {"$in": ids}})}
        return [records.get(identifier) or ChatDocumentRecord(
            id=uuid5(NAMESPACE_URL, f"{chat_id}:{identifier}").hex, owner_id=owner_id, chat_id=chat_id,
            document_id=identifier, attached_by=owner_id, created_at=chat.updated_at)
            for identifier in ids], len(chat.document_ids)

    async def project_attachment(self, chat_id, owner_id, document_id, refresh=False):
        record = ChatDocumentRecord(id=uuid5(NAMESPACE_URL, f"{chat_id}:{document_id}").hex,
            owner_id=owner_id, chat_id=chat_id, document_id=document_id, attached_by=owner_id)
        fields = record.model_dump(mode='python', by_alias=True)
        identifier = fields.pop('_id')
        update = ({"$set": fields, "$setOnInsert": {"_id": identifier}} if refresh else
                  {"$setOnInsert": {"_id": identifier, **fields}})
        await self.collection.update_one({"chat_id": chat_id, "document_id": document_id}, update, upsert=True)

    async def remove_for_document(self, chat_id, owner_id, document_id):
        await self.collection.delete_one({"chat_id": chat_id, "owner_id": owner_id, "document_id": document_id})


class IngestionJobRepository(RecordRepository):
    model = IngestionJobRecord
    collection_name = "ingestion_jobs"

    async def ensure(self, job):
        try:
            await self.collection.update_one({"_id": job.id},
                {"$setOnInsert": job.model_dump(mode='python', by_alias=True)}, upsert=True)
        except DuplicateKeyError:
            pass
        return await self.get_owned(job.id, job.owner_id)

    async def enable(self, job_id, owner_id):
        await self.collection.update_one({"_id":job_id,"owner_id":owner_id,"status":"queued"},
                                         {"$set":{"enabled":True,"updated_at":utc_now()}})

    async def claim(self, profile, worker_id, lease_seconds):
        now = utc_now()
        data = await self.collection.find_one_and_update(
            {**profile, "enabled": True, "$expr": {"$lt": ["$attempt", "$max_attempts"]}, "$or": [
                {"status": "queued", "available_at": {"$lte": now}},
                {"status": "running", "lease_expires_at": {"$lte": now}}]},
            {"$set": {"status": "running", "stage": "validating", "worker_id": worker_id,
                      "lease_token": uuid4().hex, "lease_expires_at": now+timedelta(seconds=lease_seconds),
                      "updated_at": now}, "$inc": {"attempt": 1}},
            sort=[("created_at", 1)], return_document=ReturnDocument.AFTER)
        return IngestionJobRecord.model_validate(data) if data else None

    def _claim_filter(self, job):
        return {"_id": job.id, "owner_id": job.owner_id, "status": "running",
                "lease_token": job.lease_token, "lease_expires_at": {"$gt": utc_now()}}

    async def leased_update(self, job, **fields):
        fields['updated_at'] = utc_now()
        result = await self.collection.update_one(self._claim_filter(job), {"$set": fields})
        return result.matched_count == 1

    async def renew(self, job, seconds):
        return await self.leased_update(job, lease_expires_at=utc_now()+timedelta(seconds=seconds))

    async def exhaust_one(self, profile):
        now = utc_now()
        data = await self.collection.find_one_and_update(
            {**profile, "status": "running", "lease_expires_at": {"$lte": now},
             "$expr": {"$gte": ["$attempt", "$max_attempts"]}},
            {"$set": {"status": "failed", "error": "Worker lease expired after the maximum attempts",
                      "stage": "failed", "updated_at": now, "completed_at": now}},
            return_document=ReturnDocument.AFTER)
        return IngestionJobRecord.model_validate(data) if data else None

    async def retry_failed(self, job, max_attempts):
        data = await self.collection.find_one_and_update(
            {"_id": job.id, "owner_id": job.owner_id, "status": "failed", "non_retryable": False},
            {"$set": {"status": "queued", "stage": "queued", "available_at": utc_now(),
                      "max_attempts": job.attempt+max_attempts, "enabled": True, "error": None, "completed_at": None,
                      "lease_token": None, "lease_expires_at": None, "published": False, "updated_at": utc_now()}},
            return_document=ReturnDocument.AFTER)
        return IngestionJobRecord.model_validate(data) if data else None


class Repositories:
    def __init__(self, database):
        self.users = UserRepository(database)
        self.chats = ChatRepository(database)
        self.messages = MessageRepository(database)
        self.documents = DocumentRepository(database)
        self.attachments = AttachmentRepository(database)
        self.jobs = IngestionJobRepository(database)
