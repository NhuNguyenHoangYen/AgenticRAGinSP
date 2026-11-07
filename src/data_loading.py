"""Load supported documents through the shared content validator."""
from pathlib import Path

from src.document_validation import DocumentValidator


class DataLoader:
    """Read PDF, DOCX, TXT, Markdown or CSV and return LangChain documents."""
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)

    def get_docs(self):
        return DocumentValidator().parse(
            self.file_path.read_bytes(), self.file_path.name
        ).documents
