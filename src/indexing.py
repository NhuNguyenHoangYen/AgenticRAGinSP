"""Create and reuse a Qdrant collection for LangChain document retrieval."""

import os
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_qdrant import QdrantVectorStore
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams


from src.observability import get_logger

log = get_logger(__name__)

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


class Index:
    """Manage a Qdrant vector store without recreating existing collections.

    URL, collection and optional credentials default to QDRANT_URL,
    QDRANT_COLLECTION_NAME and QDRANT_API_KEY in .env. Use a separate collection
    for each embedding model, even if two models have the same vector size.
    """

    def __init__(
        self,
        embeddings: Embeddings,
        url: Optional[str] = None,
        collection_name: Optional[str] = None,
        client: Optional[QdrantClient] = None,
    ):
        self.collection_name = (
            collection_name
            or os.getenv("QDRANT_COLLECTION_NAME")
            or "index-ai-report-2025"
        )
        self.client = client if client is not None else QdrantClient(
            url=url or os.getenv("QDRANT_URL") or "http://localhost:6333",
            api_key=os.getenv("QDRANT_API_KEY") or None,
            timeout=30,
        )

        collection_exists = self.client.collection_exists(self.collection_name)
        log.info("qdrant.collection_checked", collection=self.collection_name, exists=collection_exists)
        if not collection_exists:
            # Ask the selected embedding provider rather than hardcoding a size.
            vector_size = len(embeddings.embed_documents(["embedding dimension probe"])[0])
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )

            log.info("qdrant.collection_created", collection=self.collection_name, vector_size=vector_size)

        self.vector_store = QdrantVectorStore(
            client=self.client,
            collection_name=self.collection_name,
            embedding=embeddings,
            distance=Distance.COSINE,
            # Existing collections must match the model's dimension and distance.
            # New collections were just created from these embeddings.
            validate_collection_config=collection_exists,
        )

    def add_documents(self, docs: List[Document]) -> List[str]:
        """Embed and store passages with their metadata; return point IDs."""
        return self.vector_store.add_documents(documents=docs)

    def get_vector_store(self) -> QdrantVectorStore:
        """Return the LangChain adapter used for insertion and MMR retrieval."""
        return self.vector_store
