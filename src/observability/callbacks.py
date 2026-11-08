"""LangChain instrumentation for actual agent model/tool/retriever calls."""
from threading import RLock
from time import perf_counter

from langchain_core.callbacks import BaseCallbackHandler

from .context import context_fields
from .logger import get_logger

log = get_logger(__name__)


class AgentLoggingCallback(BaseCallbackHandler):
    # Run in the caller's context for async callbacks as well.
    run_inline = True

    def __init__(self, recorder, configuration):
        self.recorder = recorder
        self.configuration = configuration
        self.pending = {}
        self.lock = RLock()
        # Callback worker threads need explicit request identity propagation.
        self.identity = context_fields()

    def _begin(self, kind, run_id, **fields):
        with self.lock:
            self.pending[str(run_id)] = dict(kind=kind, started=perf_counter(), **fields)

    def _end(self, run_id):
        with self.lock:
            data = self.pending.pop(str(run_id), {})
        return data, round((perf_counter() - data.get("started", perf_counter())) * 1000, 2)

    def on_retriever_start(self, serialized, query, *, run_id, **kwargs):
        self._begin("retrieval", run_id, query=query)

    def on_retriever_end(self, documents, *, run_id, **kwargs):
        state, elapsed = self._end(run_id)
        passages = [doc.metadata.get("rendered_evidence",doc.page_content) for doc in documents]
        ids = [doc.metadata.get("chunk_id", doc.metadata.get("_id")) for doc in documents]
        self.recorder.retrieval(dict(
            retrieval_call_id=str(run_id), query=state.get("query"), passages=passages,
            chunk_ids=ids,
            sources=[dict(document_id=doc.metadata.get("document_id"),
                          page=doc.metadata.get("page"), section=doc.metadata.get("section"),
                          index_version=doc.metadata.get("index_version"),filename=doc.metadata.get("filename"),
                          source_label=doc.metadata.get("source_label"),truncated=doc.metadata.get("truncated",False)) for doc in documents],
        ))
        self._log("retrieval.completed", retrieval_call_id=str(run_id),
                  returned_count=len(documents), chunk_ids=ids, duration_ms=elapsed)
        if not documents:
            self._log("retrieval.empty", level="warning")

    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self._begin("llm", run_id)
        self._log("llm.started", llm_call_id=str(run_id), **self.configuration)

    def on_llm_start(self, serialized, prompts, *, run_id, **kwargs):
        self._begin("llm", run_id)

    def on_llm_end(self, response, *, run_id, **kwargs):
        _, elapsed = self._end(run_id)
        usage = (response.llm_output or {}).get("token_usage")
        if not usage and response.generations:
            message = getattr(response.generations[0][0], "message", None)
            usage = getattr(message, "usage_metadata", None)
        finish_reason = None
        if response.generations and response.generations[0]:
            generation = response.generations[0][0]
            metadata = getattr(getattr(generation, "message", None), "response_metadata", {}) or {}
            finish_reason = (generation.generation_info or {}).get("finish_reason") or metadata.get("finish_reason")
        self._log("llm.completed", llm_call_id=str(run_id), duration_ms=elapsed,
                  usage=usage, finish_reason=finish_reason, **self.configuration)

    def on_tool_start(self, serialized, input_str, *, run_id, **kwargs):
        self._begin("tool", run_id, name=(serialized or {}).get("name"), input=input_str)

    def on_tool_end(self, output, *, run_id, **kwargs):
        state, elapsed = self._end(run_id)
        self.recorder.tool(dict(tool_call_id=str(run_id), name=state.get("name"),
                                input=state.get("input"),
                                output=getattr(output, "content", str(output))))
        self._log("tool.completed", tool_call_id=str(run_id),
                  tool_name=state.get("name"), duration_ms=elapsed)

    def on_llm_error(self, error, *, run_id, **kwargs):
        self._end(run_id)

    def on_retriever_error(self, error, *, run_id, **kwargs):
        self._end(run_id)

    def on_tool_error(self, error, *, run_id, **kwargs):
        self._end(run_id)

    def _log(self, event, level="info", **fields):
        # Explicit binding also covers callbacks dispatched to a worker thread.
        from .context import RequestContext, request_context
        if self.identity:
            with request_context(RequestContext(**self.identity)):
                getattr(log, level)(event, **fields)
        else:
            getattr(log, level)(event, **fields)
