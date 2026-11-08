"""Validate and parse supported uploads before embedding or database writes."""
import csv
import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree

import fitz
from langchain_core.documents import Document


class DocumentValidationError(ValueError):
    """An actionable upload error safe to display in the UI."""


@dataclass
class ParsedDocument:
    filename: str
    extension: str
    documents: list[Document]
    warnings: list[str] = field(default_factory=list)


class DocumentValidator:
    """Parse actual content, not just its extension. OCR is not implemented."""
    supported_extensions = ("pdf", "docx", "txt", "md", "csv")
    max_bytes = 50 * 1024 * 1024
    max_expanded_bytes = 100 * 1024 * 1024

    def validate_upload(self, content: bytes, filename: str):
        filename = Path(filename).name
        extension = Path(filename).suffix.lower().lstrip(".")
        if len(filename) > 255:
            raise DocumentValidationError("Filename must be no longer than 255 characters")
        if extension not in self.supported_extensions:
            raise DocumentValidationError("Unsupported format. Upload PDF, DOCX, TXT, Markdown (.md), or CSV.")
        if not content:
            raise DocumentValidationError("The file is empty. Choose a document containing readable text.")
        if len(content) > self.max_bytes:
            raise DocumentValidationError("The file exceeds the 50 MB upload limit.")
        return filename, extension

    def parse(self, content: bytes, filename: str) -> ParsedDocument:
        filename, extension = self.validate_upload(content, filename)
        try:
            parser = getattr(self, f"_parse_{extension}", self._parse_text)
            documents, warnings = parser(content, filename)
        except DocumentValidationError:
            raise
        except Exception as error:
            raise DocumentValidationError(
                f"The {extension.upper()} file could not be parsed. It may be damaged or incorrectly named."
            ) from error
        documents = [doc for doc in documents if doc.page_content.strip()]
        if not documents:
            raise DocumentValidationError("No readable text was found. Image-only documents need OCR before uploading.")
        for document in documents:
            document.metadata.update(source=filename, filename=filename, file_type=extension)
        return ParsedDocument(filename, extension, documents, warnings)

    def _parse_pdf(self, content, filename):
        if b"%PDF-" not in content[:1024]:
            raise DocumentValidationError("The file contents are not a PDF, even though its name ends in .pdf.")
        with fitz.open(stream=content, filetype="pdf") as pdf:
            if pdf.needs_pass:
                raise DocumentValidationError("This PDF is password-protected. Upload an unlocked copy.")
            if not pdf.page_count:
                raise DocumentValidationError("This PDF contains no pages.")
            documents = [Document(page_content=page.get_text(),
                                  metadata={"page": page.number, "total_pages": pdf.page_count})
                         for page in pdf]
            blank = sum(not document.page_content.strip() for document in documents)
            if blank == pdf.page_count:
                raise DocumentValidationError("This PDF has no extractable text. Run OCR on scanned pages before uploading.")
            warnings = [f"{blank} page(s) have no extractable text and will not be indexed; scanned text and images require OCR."] if blank else []
            return documents, warnings

    def _parse_docx(self, content, filename):
        if not zipfile.is_zipfile(io.BytesIO(content)):
            raise DocumentValidationError("This is not a valid DOCX file. Save it as .docx from your word processor.")
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            infos = archive.infolist()
            if len(infos) > 10000 or sum(info.file_size for info in infos) > self.max_expanded_bytes:
                raise DocumentValidationError("The DOCX expanded contents are too large to process.")
            if "word/document.xml" not in archive.namelist() or "[Content_Types].xml" not in archive.namelist():
                raise DocumentValidationError("This archive is not a Word DOCX document.")
            xml = archive.read("word/document.xml")
            if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                raise DocumentValidationError("This DOCX contains unsupported XML declarations.")
            root = ElementTree.fromstring(xml)
            ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            if root.tag != ns + "document" or root.find(ns + "body") is None:
                raise DocumentValidationError("The DOCX body is missing or invalid.")
            paragraphs = []
            for paragraph in root.iter(ns + "p"):
                parts = []
                for node in paragraph.iter():
                    if node.tag == ns + "t":
                        parts.append(node.text or "")
                    elif node.tag == ns + "tab":
                        parts.append("\t")
                    elif node.tag in (ns + "br", ns + "cr"):
                        parts.append("\n")
                if "".join(parts).strip():
                    paragraphs.append("".join(parts))
        return [Document(page_content="\n\n".join(paragraphs))], [
            "DOCX body paragraphs and table-cell text are indexed. Images, headers, footers and page layout are not extracted."
        ]

    def _decode_text(self, content):
        if content.startswith((b"%PDF-", b"PK\x03\x04")):
            raise DocumentValidationError("The contents do not match a plain-text file. Use the original PDF or DOCX extension.")
        try:
            encoding = "utf-16" if content.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
            text = content.decode(encoding)
        except UnicodeError as error:
            raise DocumentValidationError("Text files must use UTF-8 or UTF-16 with a byte-order mark. Resave the file as UTF-8.") from error
        if any(ord(character) < 32 and character not in "\n\r\t" for character in text):
            raise DocumentValidationError("The file contains binary/control data instead of readable text.")
        return text

    def _parse_text(self, content, filename):
        return [Document(page_content=self._decode_text(content))], []

    def _parse_csv(self, content, filename):
        text = self._decode_text(content)
        rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
        if not any(any(cell.strip() for cell in row) for row in rows):
            raise DocumentValidationError("The CSV contains no readable values.")
        return [Document(page_content=text)], []
