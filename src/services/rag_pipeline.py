"""Blocking provider operations; async services run these outside the API loop."""
import hashlib
import os
from threading import RLock

from src.observability import get_logger
from src.services.contracts import PipelineAnswer, RetrievedEvidence
from src.models.records import GenerationMetadata

log = get_logger(__name__)
PROMPT_VERSION = "document-v3-scoped-citations"
PARSER_VERSION = "document-validator-v1"
CHUNKER_VERSION = "recursive-8000-800-v1"


class EvidenceCapture:
    def __init__(self):
        self.retrieval_calls = []
        self.retrieval_context = []
        self.tools_called = []
        self.documents = []

    def retrieval(self, call):
        self.retrieval_calls.append(call)
        self.retrieval_context.extend(call['passages'])
        self.documents.extend(zip(call['passages'], call.get('sources', []), call['chunk_ids']))

    def tool(self, call):
        self.tools_called.append(call)


class RAGPipeline:
    def __init__(self, settings):
        self.settings = settings
        self._embedding = None
        self._lock = RLock()
        self.embedding_profile = f"{settings.embedding_provider}:{settings.embedding_model}"
        suffix = hashlib.sha256(self.embedding_profile.encode()).hexdigest()[:12]
        self.collection = f"{settings.qdrant_collection_prefix}-{suffix}"

    def embeddings(self):
        with self._lock:
            if self._embedding is None:
                from src.embeddings.embeddings_factory import EmbeddingsFactory
                kwargs = {"model_name": self.settings.embedding_model}
                if self.settings.embedding_provider == "cohere":
                    key = os.getenv("COHERE_API_KEY")
                    if not key:
                        raise ValueError("COHERE_API_KEY is required for Cohere embeddings")
                    kwargs["cohere_api_key"] = key
                with log.operation("embedding.initialize", embedding_profile=self.embedding_profile):
                    self._embedding = EmbeddingsFactory.create_embeddings(
                        self.settings.embedding_provider, **kwargs).get_embeddings()
        return self._embedding

    def _client(self):
        from qdrant_client import QdrantClient
        return QdrantClient(url=os.getenv("QDRANT_URL", "http://localhost:6333"),
                            api_key=os.getenv("QDRANT_API_KEY") or None, timeout=30)

    def index(self, chunks, progress=None, guard=None):
        from src.indexing import Index
        client = self._client()
        try:
            store = Index(self.embeddings(), collection_name=self.collection, client=client).get_vector_store()
            # Keep Cohere calls small. Durable throttling/retry policy belongs to C.
            batch_size = 8 if self.settings.embedding_provider == "cohere" else 32
            for start in range(0, len(chunks), batch_size):
                if guard:
                    guard()
                batch = chunks[start:start + batch_size]
                with log.operation("indexing.batch", chunk_count=len(batch), collection=self.collection):
                    from uuid import NAMESPACE_URL, uuid5
                    ids = [str(uuid5(NAMESPACE_URL, chunk.metadata['chunk_id'])) for chunk in batch]
                    store.add_documents(batch, ids=ids)
                if progress:
                    progress(min(start + batch_size, len(chunks)), len(chunks))
            from qdrant_client.models import Filter, FieldCondition, MatchValue
            metadata = chunks[0].metadata
            scope = Filter(must=[FieldCondition(key=f"metadata.{key}", match=MatchValue(value=metadata[key]))
                                 for key in ("owner_id", "document_id", "index_version")])
            stored = client.count(self.collection, count_filter=scope, exact=True).count
            if stored != len(chunks):
                raise RuntimeError("Vector count verification failed")
            log.info("indexing.verified", chunk_count=stored, collection=self.collection)
        finally:
            client.close()

    def answer(self,scope,question,history,k,evaluation_recorder=None):
        from langchain_core.messages import AIMessage,HumanMessage
        from src.llms.llm_config import LLMConfig
        from src.llms.llm_factory import LLMFactory
        from src.observability.callbacks import AgentLoggingCallback
        from src.services.retrieval import RetrievalSession,ScopedRetriever
        from src.services.scoped_agent import ScopedQAAgent
        from src.services.citations import CitationValidator
        from src.services.contracts import DocumentCoverage

        config=LLMConfig.from_env()
        configuration=dict(provider=config.provider,model=config.model_name,deployment=config.deployment,
            prompt_version=PROMPT_VERSION,embedding_profile=self.embedding_profile,k=k,
            scope_mode=scope.scope_mode,strategy=scope.strategy,
            scoped_document_ids=[doc.id for doc in scope.documents])
        capture=EvidenceCapture()
        callback=AgentLoggingCallback(capture,configuration)
        client=self._client()
        try:
            session=RetrievalSession(scope,client,self.embeddings())
            retriever=ScopedRetriever(session=session)
            messages=[(HumanMessage if message.role=='user' else AIMessage)(content=message.content) for message in history]
            wrapper=LLMFactory.create_llm(config=config)
            agent=ScopedQAAgent(wrapper.get_llm(),retriever,scope,messages,callback)
            try:
                with log.operation('qa.agent_execution',**configuration):
                    raw=agent.invoke(question)
            finally:
                # Includes exactly rendered evidence even when generation/validation fails.
                if evaluation_recorder is not None:
                    for call in capture.retrieval_calls:evaluation_recorder.retrieval(call)
                    for call in capture.tools_called:evaluation_recorder.tool(call)
            evidence=list(session.evidence.values())
            answer,citations=CitationValidator().validate(raw,evidence,scope)
            retrieved={item.document_id for item in evidence}
            cited={item.document_id for item in citations}
            warnings=[]
            if scope.excluded_document_ids:
                warnings.append('Non-ready attachments were excluded from the all-ready scope.')
            if scope.strategy=='comparison' and session.missing_documents():
                warnings.append('Some comparison documents supplied no admissible evidence; a complete comparison is unavailable.')
            coverage=[DocumentCoverage(document_id=doc.id,retrieved=doc.id in retrieved,cited=doc.id in cited)
                      for doc in scope.documents]
            log.info('qa.source_coverage',retrieved_document_ids=sorted(retrieved),
                     cited_document_ids=sorted(cited),context_chars=session.context_chars)
            return PipelineAnswer(answer=answer.answer,answerability=answer.answerability,citations=citations,
                evidence=evidence,warnings=warnings,coverage=coverage,context_chars=session.context_chars,
                generation=GenerationMetadata(provider=config.provider,model=config.model_name,
                                               deployment=config.deployment,prompt_version=PROMPT_VERSION))
        finally:
            client.close()
