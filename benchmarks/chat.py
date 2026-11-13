"""Measure chat turns through FastAPI using an isolated synthetic document."""
import argparse
import csv
import json
import logging
import os
import sys
from collections import defaultdict
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pymongo import MongoClient

from benchmarks.ingestion import synthetic_pdf
from src.api.config import APISettings
from src.api.main import create_app
from src.llms.llm_factory import LLMFactory
from src.observability import get_logger
from src.workers.ingestion import IngestionWorker


class OfflineModel(BaseChatModel):
    """Exercise the tool and citation contract without provider requests."""

    @property
    def _llm_type(self):
        return "benchmark-offline"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, **kwargs):
        result = next(message for message in reversed(messages) if isinstance(message, ToolMessage))
        source = json.loads(result.content.split("\n\n")[0])
        answer = {
            "answer": f"The report summarizes operational results [{source['source']}].",
            "answerability": "answerable",
            "citations": [{"label": source["source"], "quote": source["text"][:120].strip()}],
        }
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=json.dumps(answer)))])


class TurnTimings(logging.Handler):
    def __init__(self):
        super().__init__()
        self.events = defaultdict(list)

    def emit(self, record):
        fields = getattr(record, "fields", {})
        if fields.get("request_id"):
            self.events[fields["request_id"]].append((record.getMessage(), fields))

    def take(self, request_id):
        events = self.events.pop(request_id, [])
        timings = {}
        for name, event in (
            ("llm_setup", "benchmark.llm_setup"),
            ("qdrant", "retrieval.vector_search.completed"),
            ("retrieval", "retrieval.completed"),
            ("llm", "llm.completed"),
        ):
            matches = [fields for label, fields in events if label == event]
            timings[name + "_ms"] = round(sum(item["duration_ms"] for item in matches), 3) if matches else ""
            timings[name + "_calls"] = len(matches)
        budget = next((fields for label, fields in reversed(events)
                       if label == "retrieval.budget_used"), {})
        timings["admitted_passages"] = budget.get("unique_sources", "")
        timings["context_chars"] = budget.get("context_chars", "")
        timings["input_tokens"] = token_count(events, "input_tokens", "prompt_tokens")
        timings["output_tokens"] = token_count(events, "output_tokens", "completion_tokens")
        return timings


def token_count(events, *keys):
    values = [
        usage[key]
        for label, fields in events if label == "llm.completed"
        if isinstance(usage := fields.get("usage"), dict)
        for key in keys if isinstance(usage.get(key), int)
    ]
    return sum(values) if values else ""


def checked(response):
    response.raise_for_status()
    return response.json()


def seed_chat(http, app, mongo, settings, pages):
    chat = checked(http.post("/api/v1/chats", json={"title": "Benchmark seed"}))["id"]
    upload = checked(http.post(
        f"/api/v1/chats/{chat}/documents",
        files=[("files", ("synthetic.pdf", synthetic_pdf(pages), "application/pdf"))],
    ))["items"][0]
    doc_id = upload["document_id"]
    if not doc_id:
        raise RuntimeError("Synthetic PDF upload failed")
    worker = IngestionWorker(app.state.repositories, app.state.storage, app.state.pipeline, settings)
    http.portal.call(worker.run_once)
    document = mongo[settings.mongodb_database].documents.find_one({"_id": doc_id})
    if document["status"] != "ready":
        raise RuntimeError(f"Indexing failed with document status {document['status']}")
    app.state.storage.remove(document["storage_key"])
    if http.get(f"/api/v1/documents/{doc_id}/content").status_code != 404:
        raise RuntimeError("Benchmark original is still available")
    return doc_id


def run_turns(http, timings, doc_id, budgets, turns, mode):
    writer = None
    for chat_number, budget in enumerate(budgets, start=1):
        chat = checked(http.post("/api/v1/chats", json={"title": f"Budget {budget}"}))["id"]
        checked(http.post(f"/api/v1/chats/{chat}/attachments",
                          json={"document_id": doc_id, "ready_only": True}))
        for turn in range(1, turns + 1):
            started = perf_counter()
            response = http.post(f"/api/v1/chats/{chat}/messages", json={
                "question": "What does the report summarize? Answer in one short sentence.",
                "strategy": "general",
                "k": budget,
            })
            elapsed = (perf_counter() - started) * 1000
            result = response.json()
            row = {
                "mode": mode, "chat_number": chat_number, "turn": turn, "requested_k": budget,
                "status": response.status_code, "error_code": result.get("error", {}).get("code", ""),
                "response_ms": round(elapsed, 3),
                **timings.take(response.headers.get("X-Request-ID")),
            }
            if writer is None:
                writer = csv.DictWriter(sys.stdout, fieldnames=row.keys())
                writer.writeheader()
            writer.writerow(row)
            sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=50)
    parser.add_argument("--budgets", nargs="+", type=int, default=[2, 8, 20])
    parser.add_argument("--turns", type=int, default=3)
    parser.add_argument("--live-llm", action="store_true", help="Use the configured provider. Requests may be billed.")
    parser.add_argument("--allow-paid-embeddings", action="store_true")
    args = parser.parse_args()
    if args.pages < 1 or args.turns < 1 or any(not 1 <= k <= 20 for k in args.budgets):
        parser.error("Use positive pages and turns, and budgets from 1 to 20")
    settings = APISettings.from_env()
    if settings.embedding_provider == "cohere" and not args.allow_paid_embeddings:
        parser.error("Cohere embedding requests require --allow-paid-embeddings")

    run_id = uuid4().hex
    create_llm = LLMFactory.create_llm

    def timed_factory(*factory_args, **kwargs):
        started = perf_counter()
        wrapper = (create_llm(*factory_args, **kwargs) if args.live_llm
                   else SimpleNamespace(get_llm=lambda: OfflineModel()))
        get_logger(__name__).info("benchmark.llm_setup", duration_ms=(perf_counter() - started) * 1000)
        return wrapper

    environment = {"LOG_LEVEL": "INFO", "EVALUATION_CAPTURE_ENABLED": "false"}
    if not args.live_llm:
        environment.update(LLM_PROVIDER="openai", OPENAI_API_KEY="benchmark-offline")
    with TemporaryDirectory(prefix="agentic-chat-benchmark-") as directory:
        environment["LOG_DIR"] = str(Path(directory) / "logs")
        settings = replace(
            settings, mongodb_database=f"agentic_bench_{run_id}", environment="testing",
            upload_directory=Path(directory) / "uploads", qdrant_collection_prefix=f"bench-{run_id}",
        )
        with patch.dict(os.environ, environment), patch.object(LLMFactory, "create_llm", side_effect=timed_factory):
            app = create_app(settings)
            with MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=settings.mongodb_timeout_ms) as mongo:
                try:
                    with TestClient(app) as http:
                        doc_id = seed_chat(http, app, mongo, settings, args.pages)
                        logger = logging.getLogger("agentic_rag")
                        timings = TurnTimings()
                        previous_handlers = logger.handlers[:]
                        logger.handlers = [timings, *[handler for handler in previous_handlers
                                                   if handler.level >= logging.ERROR]]
                        diagnostic = logging.StreamHandler(sys.stderr)
                        diagnostic.setLevel(logging.ERROR)
                        diagnostic.setFormatter(previous_handlers[0].formatter)
                        logger.addHandler(diagnostic)
                        try:
                            run_turns(http, timings, doc_id, args.budgets, args.turns,
                                      "live" if args.live_llm else "offline")
                        finally:
                            logger.handlers = previous_handlers
                finally:
                    try:
                        pipeline = getattr(app.state, "pipeline", None)
                        if pipeline:
                            client = pipeline._client()
                            try:
                                if client.collection_exists(pipeline.collection):
                                    client.delete_collection(pipeline.collection)
                            finally:
                                client.close()
                    finally:
                        mongo.drop_database(settings.mongodb_database)


if __name__ == "__main__":
    main()
