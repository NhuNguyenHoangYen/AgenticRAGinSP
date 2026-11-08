"""Shared parse/chunk operations used by the API and legacy UI wrappers."""
from src.observability import get_logger
from src.document_validation import DocumentValidator

log = get_logger(__name__)


class DocumentProcessor:
    def parse(self, content, filename):
        with log.operation("document.parsing"):
            parsed = DocumentValidator().parse(content, filename)
        log.info("document.parsed", section_count=len(parsed.documents), file_type=parsed.extension)
        for warning in parsed.warnings:
            log.warning("document.extraction_warning", message=warning)
        return parsed

    def split(self, documents):
        from src.chunking import TextSplitter
        with log.operation("document.chunking", chunk_size=8000, chunk_overlap=800):
            chunks = TextSplitter().split_documents(documents)
        log.info("document.chunked", chunk_count=len(chunks))
        return chunks
