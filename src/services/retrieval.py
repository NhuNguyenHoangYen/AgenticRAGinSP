"""Request-local retrieval budgets, strict source filtering and evidence rendering."""
import json
from collections import defaultdict
from typing import Any

import numpy as np
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores.utils import maximal_marginal_relevance
from qdrant_client.models import Filter, FieldCondition, MatchValue

from src.observability import get_logger
from src.services.contracts import RetrievedEvidence
from src.services.errors import WorkflowError

log = get_logger(__name__)


def render_evidence(evidence):
    return json.dumps(dict(source=evidence.label,document_id=evidence.document_id,
        index_version=evidence.index_version,chunk_id=evidence.chunk_id,filename=evidence.filename,
        page=evidence.page,section=evidence.section,text=evidence.text,truncated=evidence.truncated),
        ensure_ascii=False,separators=(',',':'))


class RetrievalSession:
    def __init__(self,scope,client,embeddings):
        if any(doc.owner_id!=scope.owner_id for doc in scope.documents):
            raise WorkflowError('invalid_scope','Document ownership does not match the request scope')
        self.scope,self.client,self.embeddings=scope,client,embeddings
        self.allowed={(doc.id,doc.index.index_version,doc.index.collection):doc for doc in scope.documents}
        self.evidence={}
        self.context_chars=0
        self.document_chars=defaultdict(int)
        self.document_counts=defaultdict(int)
        self.calls=0
        self.quotas={doc.id:scope.k//len(scope.documents)+(index<scope.k%len(scope.documents))
                     for index,doc in enumerate(scope.documents)}

    def _filter(self,documents):
        pairs=[Filter(must=[FieldCondition(key='metadata.document_id',match=MatchValue(value=doc.id)),
                           FieldCondition(key='metadata.index_version',match=MatchValue(value=doc.index.index_version))])
               for doc in documents]
        return Filter(must=[FieldCondition(key='metadata.owner_id',match=MatchValue(value=self.scope.owner_id)),
                            Filter(should=pairs)])

    def _candidates(self,query_vector,documents,budget):
        grouped=defaultdict(list)
        for doc in documents:grouped[doc.index.collection].append(doc)
        candidates=[]
        seen=set()
        for collection,group in grouped.items():
            with log.operation('retrieval.vector_search',collection=collection,allowed_count=len(group)):
                points=self.client.query_points(collection_name=collection,query=query_vector,
                    query_filter=self._filter(group),limit=max(4,budget*4),with_payload=True,with_vectors=True).points
            for point in points:
                payload=point.payload or {};metadata=payload.get('metadata',{})
                key=(metadata.get('document_id'),metadata.get('index_version'),collection)
                if metadata.get('owner_id')!=self.scope.owner_id or key not in self.allowed:
                    raise WorkflowError('retrieval_scope_violation','Vector search returned evidence outside the allowed scope')
                if not isinstance(point.vector,list) or not metadata.get('chunk_id'):
                    raise WorkflowError('retrieval_scope_violation','Retrieved vector/source metadata is invalid')
                chunk_key=(*key,str(metadata['chunk_id']))
                if chunk_key in seen:continue
                seen.add(chunk_key)
                text=payload.get('page_content')
                if not isinstance(text,str) or not text.strip():continue
                candidates.append((Document(page_content=text,metadata=dict(metadata,_collection=collection)),point.vector))
        if not candidates:return []
        selected=maximal_marginal_relevance(np.asarray(query_vector,dtype=np.float32),
                    [vector for _,vector in candidates],k=min(len(candidates),max(budget*2,4)))
        return [candidates[index][0] for index in selected]

    def _admit(self,document):
        meta=document.metadata
        source=self.allowed[(meta['document_id'],meta['index_version'],meta['_collection'])]
        key=(source.id,source.index.index_version,str(meta['chunk_id']))
        existing=self.evidence.get(key)
        available=self.scope.context_max_chars-self.context_chars
        if self.scope.strategy=='comparison':
            available=min(available,self.scope.context_max_chars//len(self.scope.documents)-self.document_chars[source.id])
        if existing is not None:
            rendered=render_evidence(existing)
            if len(rendered)+2>available:return None
            evidence=existing
        else:
            if len(self.evidence)>=self.scope.k:return None
            if self.scope.strategy=='comparison' and self.document_counts[source.id]>=self.quotas[source.id]:return None
            page=meta.get('page')
            total_pages=meta.get('total_pages')
            if source.file_type=='pdf' and (type(page) is not int or page<0 or
                (type(total_pages) is int and page>=total_pages)):
                raise WorkflowError('retrieval_scope_violation','PDF evidence has invalid page metadata')
            evidence=RetrievedEvidence(label=f'S{len(self.evidence)+1}',document_id=source.id,
                index_version=source.index.index_version,chunk_id=str(meta['chunk_id']),filename=source.filename,
                page=page+1 if type(page) is int else None,
                section=None if type(page) is int else str(meta.get('section') or 'Document text'),text='')
            # JSON escaping can expand text. Binary search keeps the rendered block within budget.
            text=document.page_content
            low,high=0,min(len(text),16000)
            while low<high:
                middle=(low+high+1)//2
                candidate=evidence.model_copy(update={'text':text[:middle],'truncated':middle<len(text)})
                if len(render_evidence(candidate))+2<=available:low=middle
                else:high=middle-1
            if low==0:return None
            evidence=evidence.model_copy(update={'text':text[:low],'truncated':low<len(text)})
            rendered=render_evidence(evidence)
            self.evidence[key]=evidence
            self.document_counts[source.id]+=1
        self.context_chars+=len(rendered)+2
        self.document_chars[source.id]+=len(rendered)+2
        return Document(page_content=evidence.text,metadata={
            **meta,'source_label':evidence.label,'filename':evidence.filename,
            'rendered_evidence':rendered,'truncated':evidence.truncated})

    def retrieve(self,query):
        first=self.calls==0
        self.calls+=1
        query_vector=self.embeddings.embed_query(query)
        results=[]
        if self.scope.strategy=='comparison':
            for source in self.scope.documents:
                budget=1 if first else self.quotas[source.id]
                added=0
                for candidate in self._candidates(query_vector,[source],budget):
                    admitted=self._admit(candidate)
                    if admitted:
                        results.append(admitted);added+=1
                    if added>=budget:break
        else:
            budget=max(1,self.scope.k//2) if first else self.scope.k
            for candidate in self._candidates(query_vector,self.scope.documents,self.scope.k):
                admitted=self._admit(candidate)
                if admitted:results.append(admitted)
                if len(results)>=budget:break
        log.info('retrieval.budget_used',strategy=self.scope.strategy,returned_count=len(results),
                 unique_sources=len(self.evidence),context_chars=self.context_chars,
                 context_max_chars=self.scope.context_max_chars,search_number=self.calls)
        if not results:log.warning('retrieval.no_evidence_admitted')
        return results

    def missing_documents(self):
        retrieved={item.document_id for item in self.evidence.values()}
        return [doc.id for doc in self.scope.documents if doc.id not in retrieved]


class ScopedRetriever(BaseRetriever):
    session: Any

    def _get_relevant_documents(self,query,*,run_manager):
        return self.session.retrieve(query)
