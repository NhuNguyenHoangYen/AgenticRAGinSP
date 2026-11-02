"""Integration checks against Qdrant local memory; no model APIs required."""

import os
import unittest
from unittest.mock import patch

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_qdrant.qdrant import QdrantVectorStoreError
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

from src.indexing import Index


class TopicEmbeddings(Embeddings):
    """Deterministic vectors to test storage and retrieval, not model quality."""

    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text):
        text = text.lower()
        return [float("protein" in text), float("climate" in text), 0.1]


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.client = QdrantClient(":memory:")
        self.embeddings = TopicEmbeddings()

    def tearDown(self):
        self.client.close()

    def make_index(self):
        return Index(self.embeddings, collection_name="test-papers", client=self.client)

    def test_create_collection_with_model_dimension(self):
        self.make_index()
        vectors = self.client.get_collection("test-papers").config.params.vectors
        self.assertEqual(vectors.size, 3)
        self.assertEqual(vectors.distance, Distance.COSINE)

    def test_insert_search_and_preserve_metadata(self):
        index = self.make_index()
        ids = index.add_documents([
            Document(page_content="Protein folding methods", metadata={"page": 7}),
            Document(page_content="Climate research methods", metadata={"page": 2}),
        ])
        result = index.get_vector_store().similarity_search("protein", k=1)
        self.assertEqual(len(ids), 2)
        self.assertEqual(result[0].page_content, "Protein folding methods")
        self.assertEqual(result[0].metadata["page"], 7)

    def test_mmr_retriever_used_by_agent(self):
        index = self.make_index()
        index.add_documents([Document(page_content="Protein study"), Document(page_content="Climate study")])
        retriever = index.get_vector_store().as_retriever(
            search_type="mmr", search_kwargs={"k": 1, "fetch_k": 4}
        )
        self.assertEqual(retriever.invoke("protein")[0].page_content, "Protein study")

    def test_reconnect_keeps_existing_points(self):
        index = self.make_index()
        index.add_documents([Document(page_content="Protein study")])
        reconnected = self.make_index()
        self.assertEqual(self.client.count("test-papers").count, 1)
        self.assertEqual(len(reconnected.get_vector_store().similarity_search("protein", k=1)), 1)

    def test_mismatched_dimension_is_rejected_without_deletion(self):
        self.client.create_collection("test-papers", vectors_config=VectorParams(size=2, distance=Distance.COSINE))
        with self.assertRaises(QdrantVectorStoreError):
            self.make_index()
        self.assertEqual(self.client.get_collection("test-papers").config.params.vectors.size, 2)

    def test_mismatched_distance_is_rejected(self):
        self.client.create_collection("test-papers", vectors_config=VectorParams(size=3, distance=Distance.DOT))
        with self.assertRaises(QdrantVectorStoreError):
            self.make_index()

    def test_url_and_api_key_configuration(self):
        with patch.dict(os.environ, {"QDRANT_URL": "http://localhost:6333", "QDRANT_API_KEY": "test-only"}):
            with patch("src.indexing.QdrantClient", return_value=self.client) as constructor:
                Index(self.embeddings, collection_name="test-papers")
        constructor.assert_called_once_with(url="http://localhost:6333", api_key="test-only", timeout=30)


if __name__ == "__main__":
    unittest.main()
