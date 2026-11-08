"""MongoDB lifetime, collection validation and indexes for the backend."""
from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.errors import CollectionInvalid, OperationFailure
from time import perf_counter

from src.observability import get_logger

log = get_logger(__name__)


class MongoDatabase:
    def __init__(self, settings):
        self.client = AsyncMongoClient(
            settings.mongodb_uri, tz_aware=True,
            serverSelectionTimeoutMS=settings.mongodb_timeout_ms,
            connectTimeoutMS=settings.mongodb_timeout_ms,
            timeoutMS=settings.mongodb_timeout_ms,
        )
        self.database = self.client[settings.mongodb_database]

    async def ping(self):
        started = perf_counter()
        await self.database.command("ping")
        log.debug("mongodb.ping_completed", duration_ms=round((perf_counter() - started) * 1000, 2))

    async def initialize(self):
        with log.operation("mongodb.initialize", database_name=self.database.name):
            await self._initialize()

    async def _initialize(self):
        await self.ping()
        log.info("mongodb.connected", database_name=self.database.name)
        required = {
            "users": ["auth_provider", "auth_subject", "display_name", "status"],
            "chats": ["owner_id", "title", "status", "document_set_version", "next_message_sequence"],
            "messages": ["owner_id", "chat_id", "turn_id", "request_id", "sequence", "role", "content", "status"],
            "documents": ["owner_id", "filename", "content_hash", "file_type", "size_bytes", "storage_key", "status"],
            "chat_documents": ["owner_id", "chat_id", "document_id", "attached_by"],
            "ingestion_jobs": ["owner_id", "document_id", "status", "stage", "attempt"],
        }
        numeric = {"sequence", "document_set_version", "next_message_sequence", "size_bytes", "attempt"}
        existing = set(await self.database.list_collection_names())
        for name, fields in required.items():
            if name in existing:
                log.debug("mongodb.collection_reused", collection=name)
                continue  # Existing validators need an explicit migration, not silent replacement.
            properties = {field: {"bsonType": ["int", "long"] if field in numeric else "string"}
                          for field in fields}
            properties.update(_id={"bsonType": "string"}, created_at={"bsonType": "date"},
                              updated_at={"bsonType": "date"})
            validator = {"$jsonSchema": {"bsonType": "object", "required": ["_id", "created_at", "updated_at", *fields],
                                         "properties": properties}}
            try:
                await self.database.create_collection(name, validator=validator)
                log.info("mongodb.collection_created", collection=name)
            except OperationFailure as error:
                if error.code != 48:  # NamespaceExists during concurrent startup.
                    raise
            except CollectionInvalid:
                pass  # Another API worker may have created it during startup.
        log.info("mongodb.indexes_started")
        await self.database.users.create_index(
            [("auth_provider", ASCENDING), ("auth_subject", ASCENDING)], unique=True)
        await self.database.chats.create_index(
            [("owner_id", ASCENDING), ("status", ASCENDING), ("updated_at", DESCENDING), ("_id", DESCENDING)])
        await self.database.messages.create_index([("chat_id", ASCENDING), ("sequence", ASCENDING)], unique=True)
        await self.database.messages.create_index([("owner_id", ASCENDING), ("chat_id", ASCENDING), ("sequence", ASCENDING)])
        await self.database.documents.create_index([("owner_id", ASCENDING), ("created_at", DESCENDING)])
        await self.database.documents.create_index([("owner_id", ASCENDING), ("content_hash", ASCENDING)])
        await self.database.chat_documents.create_index([("chat_id", ASCENDING), ("document_id", ASCENDING)], unique=True)
        await self.database.chat_documents.create_index([("owner_id", ASCENDING), ("chat_id", ASCENDING), ("created_at", ASCENDING), ("_id", ASCENDING)])
        await self.database.chat_documents.create_index("document_id")
        await self.database.ingestion_jobs.create_index([("status", ASCENDING), ("created_at", ASCENDING)])
        await self.database.documents.create_index("dedup_key", unique=True,
            partialFilterExpression={"dedup_key": {"$type": "string"}})
        await self.database.documents.create_index([("status", ASCENDING), ("ingestion_job_id", ASCENDING)])
        await self.database.ingestion_jobs.create_index([
            ("embedding_profile", ASCENDING), ("collection", ASCENDING),
            ("status", ASCENDING), ("available_at", ASCENDING), ("lease_expires_at", ASCENDING)])
        await self.database.chats.create_index("document_ids")
        log.info("mongodb.indexes_ready")

    async def close(self):
        with log.operation("mongodb.close"):
            await self.client.close()
