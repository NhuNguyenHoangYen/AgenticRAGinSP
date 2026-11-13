"""Benchmark PDF parsing, chunking and optional real vector indexing."""
import argparse
import csv
import hashlib
import sys
from dataclasses import replace
from statistics import median
from time import perf_counter
from uuid import uuid4

import fitz

from src.api.config import APISettings
from src.observability import configure_logging
from src.services.document_processing import DocumentProcessor
from src.services.rag_pipeline import RAGPipeline

PAGE_COUNTS = (5, 10, 50, 100, 150, 200, 500, 1000)
PARAGRAPH = (
    "The report summarizes the observed response times, sample sizes and operational results. "
    "Each measurement was collected under the same conditions. The observations provide a "
    "reference for comparing outcomes across reporting periods."
)


def synthetic_pdf(page_count):
    with fitz.open() as pdf:
        for number in range(1, page_count + 1):
            page = pdf.new_page()
            text = f"Benchmark report, page {number}\n\n" + "\n\n".join([PARAGRAPH] * 9)
            if page.insert_textbox(fitz.Rect(48, 48, 547, 794), text, fontsize=10) < 0:
                raise RuntimeError("Benchmark text did not fit the page")
        return pdf.tobytes()


def measure(content, processor, pipeline=None):
    started = perf_counter()
    hashlib.sha256(content).hexdigest()
    fingerprinted = perf_counter()
    parsed = processor.parse(content, "benchmark.pdf")
    parsed_at = perf_counter()
    chunks = processor.split(parsed.documents)
    chunked_at = perf_counter()
    index_ms = None
    if pipeline:
        document_id = uuid4().hex
        for position, chunk in enumerate(chunks):
            chunk.metadata.update(owner_id="benchmark", document_id=document_id,
                                  index_version=document_id, chunk_id=f"{document_id}:{position}")
        index_started = perf_counter()
        pipeline.index(chunks)
        index_ms = (perf_counter() - index_started) * 1000
    return {
        "readable_pages": len(parsed.documents),
        "text_chars": sum(len(page.page_content) for page in parsed.documents),
        "chunks": len(chunks),
        "hash_ms": (fingerprinted - started) * 1000,
        "parse_ms": (parsed_at - fingerprinted) * 1000,
        "chunk_ms": (chunked_at - parsed_at) * 1000,
        "index_ms": index_ms,
        "measured_total_ms": (perf_counter() - started) * 1000,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", nargs="+", type=int, default=PAGE_COUNTS)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--index", action="store_true", help="Use configured embeddings and Qdrant")
    parser.add_argument("--allow-paid-embeddings", action="store_true")
    args = parser.parse_args()
    if args.repeats < 1 or any(pages < 1 for pages in args.pages):
        parser.error("Page counts and repeats must be positive")
    settings = APISettings.from_env()
    if args.index and settings.embedding_provider == "cohere" and not args.allow_paid_embeddings:
        parser.error("Cohere indexing requires --allow-paid-embeddings")
    configure_logging()
    pipeline = None
    if args.index:
        pipeline = RAGPipeline(replace(settings, qdrant_collection_prefix=f"bench-{uuid4().hex}"))

    processor = DocumentProcessor()
    writer = None
    try:
        # Warm the parser. For indexing, also initialize embeddings and the scratch collection.
        warmup = measure(synthetic_pdf(1), processor, pipeline)
        print(f"Warm-up: {warmup['measured_total_ms']:.2f} ms", file=sys.stderr)
        for pages in args.pages:
            content = synthetic_pdf(pages)
            samples = [measure(content, processor, pipeline) for _ in range(args.repeats)]
            summary = {"pages": pages, "pdf_bytes": len(content), "repeats": args.repeats}
            for key in samples[0]:
                values = [sample[key] for sample in samples if sample[key] is not None]
                summary[key] = round(median(values), 3) if values else ""
            if writer is None:
                writer = csv.DictWriter(sys.stdout, fieldnames=summary.keys())
                writer.writeheader()
            writer.writerow(summary)
            sys.stdout.flush()
    finally:
        if pipeline:
            client = pipeline._client()
            try:
                if client.collection_exists(pipeline.collection):
                    client.delete_collection(pipeline.collection)
            finally:
                client.close()


if __name__ == "__main__":
    main()
