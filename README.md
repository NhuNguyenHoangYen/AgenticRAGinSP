# AgenticRAG — Document Chatbot

AgenticRAG helps users understand documents and obtain evidence-based answers. Create a chat, upload several documents, and ask questions across all ready documents or a selected subset. Answers include source labels, supporting quotes and document locations.

This is a local development application. Chats persist, but the backend currently uses one shared development identity. User sign-in and authenticated multi-user access are not implemented.

## What the application supports

- Multiple chats with persisted messages and document attachments.
- Uploading PDF, DOCX, TXT, Markdown (`.md`) and CSV files; adding more documents later.
- Background document validation, parsing, chunking, embedding and indexing.
- Processing status, per-file failures and retries for retryable jobs.
- Questions across all ready documents or explicitly selected documents.
- A comparison mode that reserves evidence capacity for each scoped document.
- Citations identifying the document, supporting quote, and page or section.
- Original-file downloads and a bounded PDF preview, including cited pages.
- Removing a document from a chat while retaining historical citations and originals.
- Configurable OpenAI, Azure OpenAI or Cohere answer generation, independent of the embedding provider.
- Rotating structured operational logs and optional evaluation captures.

Documents need extractable text. Scanned/image-only documents require OCR before upload; the app does not perform OCR. It does not provide image understanding or token-streamed answers in the current UI.

## How it works

```mermaid
flowchart LR
    UI[Streamlit UI] -->|HTTP requests| API[FastAPI]
    API --> DB[(MongoDB)]
    API --> Files[Local original files]
    Worker[Ingestion worker] -->|Claim jobs and publish status| DB
    Worker -->|Read original files| Files
    Worker --> Parse[Validate, parse and chunk]
    Parse --> Embed[Embedding model]
    Embed --> Q[(Qdrant)]
    API -->|Scoped retrieval| Q
    API --> LLM[Configured chat model]
```

**Ingestion:** upload → save original and queue job → worker validates/parses → recursive text splitting → embeddings → Qdrant → document marked ready.

**Question answering:** freeze the selected document/index scope → retrieve passages within that scope → assemble evidence and scoped conversation history → generate an answer → validate citation labels and quotes → persist the result → display it in Streamlit. The agent can refine retrieval within the same scope and evidence budget.

| Component | Responsibility | Default local address |
| --- | --- | --- |
| Streamlit | Upload controls, chat navigation, document selection and answer display | `http://localhost:8501` |
| FastAPI | Application services, access checks, document/chat APIs and QA | `http://127.0.0.1:8000` |
| Ingestion worker | Background parsing, embeddings, indexing and job recovery | Separate Python process |
| MongoDB | Chats, messages, document metadata, attachments and jobs | `mongodb://127.0.0.1:27017` |
| Qdrant | Passage vectors and searchable metadata | `http://localhost:6333` |
| Local storage | Uploaded original documents | `var/uploads/` |

The UI does not connect directly to databases or model providers. The API and worker must share the same configuration, MongoDB database and upload directory.

## Prerequisites

- Python **3.11**: the dependency sets were verified with this Python version.
- Docker Desktop running, with Docker Compose available, or separately running compatible MongoDB and Qdrant services.
- Credentials for one supported chat provider and access to a chat model supporting tool calling.
- Internet access for dependency installation, provider requests and the first Hugging Face model download when uncached.

The commands below target macOS/Linux and must be run from the project root. VS Code is an editor; it does not replace the Python environments or the running services.

## First-time setup

### 1. Open the project

```bash
cd /AI_Engineering/DocumentBot/AgenticRAG
python3.11 --version
docker compose version
```

If the project is elsewhere, substitute its actual path. Open that folder in VS Code and use its integrated terminals if preferred.

### 2. Install backend and frontend dependencies separately

```bash
# API and ingestion worker environment:
python3.11 -m venv .venv-api
.venv-api/bin/python -m pip install --upgrade pip
.venv-api/bin/python -m pip install -r requirements-backend.txt

# Lightweight Streamlit environment:
python3.11 -m venv .venv-ui
.venv-ui/bin/python -m pip install --upgrade pip
.venv-ui/bin/python -m pip install -r requirements-ui.txt
```

`requirements-backend.txt` includes `requirements-rag.txt` for the provider, parsing and embedding stack. `requirements-ui.txt` contains the frontend dependencies. Use these files for the current application; the older `requirements.txt` is a legacy environment snapshot and includes platform-specific packages.

Activation is optional because these commands explicitly select the environment's Python. This avoids installing packages into one environment and running another. Keep `.env`, local documents, generated data and virtual-environment folders out of commits, including `.venv-ui/`.

### 3. Configure `.env`

If `.env` does not exist, create it from the template:

```bash
cp -n .env.example .env
```

Edit the existing `.env` rather than replacing your saved credentials. For public OpenAI answers with local Hugging Face embeddings, configure:

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=YOUR_OPENAI_API_KEY
OPENAI_MODEL=gpt-4.1-mini

API_EMBEDDING_PROVIDER=huggingface
API_EMBEDDING_MODEL=sentence-transformers/all-mpnet-base-v2
API_QDRANT_COLLECTION_PREFIX=agentic-rag-api
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=

MONGODB_URI=mongodb://127.0.0.1:27017
MONGODB_DATABASE=agentic_rag
UPLOAD_DIR=var/uploads
APP_ENV=development
API_BASE_URL=http://127.0.0.1:8000
```

Choose a tool-capable model available to your provider account. The shown model name is the repository default. The Hugging Face embedding model runs locally and may download weights on first use; the selected chat provider receives retrieved evidence for answer generation.

Alternatively, configure **Azure OpenAI** for answers:

```dotenv
LLM_PROVIDER=azure_openai
AZURE_OPENAI_API_KEY=YOUR_AZURE_RESOURCE_KEY
AZURE_OPENAI_ENDPOINT=https://YOUR_RESOURCE.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=YOUR_CHAT_DEPLOYMENT_NAME
AZURE_OPENAI_API_VERSION=YOUR_SUPPORTED_API_VERSION
```

Use the resource root endpoint, your Azure deployment name and an API version supported by that resource. The Azure key is separate from the public `OPENAI_API_KEY`.

For **Cohere** answers, set `LLM_PROVIDER=cohere`, `COHERE_API_KEY` and `COHERE_MODEL`. To use Cohere embeddings independently of the chat provider, set `API_EMBEDDING_PROVIDER=cohere`, `API_EMBEDDING_MODEL=embed-v4.0` and `COHERE_API_KEY`.

The backend uses `API_QDRANT_COLLECTION_PREFIX` plus an embedding-profile hash for its collections. `QDRANT_COLLECTION_NAME` in the template belongs to the older direct path and does not choose the current backend collection. Changing embedding settings does not automatically migrate existing documents: keep the API/worker settings aligned and upload documents under the intended profile.

All processes load `.env` from the project root; existing shell environment variables take precedence. Restart the affected processes after configuration changes. Keys and model settings are configured here, not in the Streamlit sidebar. Some template comments still refer to the older UI; the instructions above describe the current application.

### 4. Start the databases

**Fresh setup without an existing Qdrant service:**

```bash
docker compose up -d mongodb qdrant
docker compose ps
```

**If you already have a Qdrant container with your data:** start that existing container and keep `QDRANT_URL` pointed at it. Start only MongoDB from this Compose project:

```bash
docker compose up -d mongodb
```

Do not launch a second Qdrant service on the same port. An image listed in Docker Desktop is not enough: its container must be running. The checked-in Compose file defines its own Qdrant image and volume; reusing your current container avoids switching to a different data volume unintentionally.

Confirm Qdrant responds:

```bash
curl --fail http://localhost:6333/
```

The Qdrant dashboard is at **http://localhost:6333/dashboard**. Compose-managed databases retain data in named volumes across ordinary restarts. Keep any existing database/client versions unless you deliberately plan a separate compatibility change.

## Run the application

Open **three terminals**, each in the project root. Start the API first, then the worker and UI.

**Terminal 1 — FastAPI**

```bash
.venv-api/bin/python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
```

**Terminal 2 — ingestion worker**

```bash
.venv-api/bin/python -m src.workers.ingestion
```

**Terminal 3 — Streamlit**

```bash
.venv-ui/bin/python -m streamlit run src/app.py
```

Open **http://localhost:8501**. API documentation is at **http://127.0.0.1:8000/docs**.

The API does not launch the worker automatically. Uploads can be accepted while the worker is stopped, but they remain queued until a matching worker starts. Start with one worker locally.

For later runs, you only need to start Docker/the database containers and these three processes; dependency installation is a one-time setup unless requirements change. Stop Python processes with `Ctrl+C`. For Compose-managed databases, `docker compose stop` stops containers without deleting their volumes. Avoid `docker compose down -v` when you want to preserve data.

**Windows:** use Python 3.11 and create environments with `py -3.11 -m venv .venv-api` and `py -3.11 -m venv .venv-ui`. Replace `.venv-api/bin/python` and `.venv-ui/bin/python` in the commands with `.venv-api\Scripts\python.exe` and `.venv-ui\Scripts\python.exe`. Use `Copy-Item .env.example .env` only if `.env` is absent. The current verification was performed on macOS; Windows setup has not been verified here.

## First conversation

1. Create a chat and give it a title.
2. Choose one or more documents, then click **Add selected files**. Merely selecting files does not upload them.
3. Wait for processing to finish. Status is polled every four seconds. Ready documents can be queried while another file is still processing or has failed.
4. Choose **All ready documents** or **Select documents** for the question.
5. Choose `general` or `comparison`, then set the maximum evidence passages. Comparison needs at least two ready documents and at least one evidence passage per document.
6. Ask a question. Expand citations to inspect quotes, document IDs and page/section locations. Use **Load original file** for a download or bounded PDF preview.
7. Add more files later using the same upload button, or **Remove from chat** to exclude a document from subsequent questions.

Example questions: “Summarize the main findings with citations,” “How do the two reports differ?” or “According to the selected document, what evidence supports this conclusion?”

Use the chat selector to reopen saved conversations. The `?chat=CHAT_ID` URL restores a chat after reload. Removal detaches a document; it does not delete its originals/vectors or rewrite past answers. An answer already in progress uses its frozen source snapshot. Other file formats offer original downloads; inline previews are limited to one PDF page and PDFs up to 10 MiB.

Default upload limits are **10 files / 100 MiB per batch**, **50 MiB per file** and **100 attachments per chat**. `UPLOAD_MAX_FILES` and `UPLOAD_BATCH_BYTES` configure backend batch limits; the current UI enforces the default 10-file/100-MiB limits. Parsing failures are shown per file; retryable processing failures expose **Retry processing**.

## Verify startup and troubleshoot

```bash
curl --fail http://127.0.0.1:8000/health
curl --fail http://127.0.0.1:8000/health/ready
curl --fail http://localhost:6333/
```

`/health` checks the API response; `/health/ready` checks MongoDB connectivity. Neither proves the worker, Qdrant, model credentials or model downloads are working. A small text-document upload that reaches `ready`, followed by a cited answer, verifies the broader workflow.

| Symptom | What to check |
| --- | --- |
| `streamlit: command not found` | Use `.venv-ui/bin/python -m streamlit run src/app.py`. Install `requirements-ui.txt` with that same interpreter. |
| `No module named src` | Launch from the repository root using the commands above. Avoid running internal service modules as standalone files. |
| UI cannot reach API | Start FastAPI and verify `API_BASE_URL` and `/health`. Check the API terminal for startup errors. |
| API fails on MongoDB startup | Start MongoDB, verify `MONGODB_URI`, and inspect `docker compose logs --tail=100 mongodb` if Compose-managed. |
| Documents stay queued | Start the worker; check its logs and ensure it uses the same database, upload directory and embedding profile as the API. |
| Embedding is slow on first use | Hugging Face weights may be downloading. Check worker logs and network access before retrying. |
| Qdrant connection refused | Start its container, check port 6333 and `QDRANT_URL`; an installed image alone is insufficient. |
| Qdrant client/server compatibility warning | Compare installed client and running server versions. This warning is not a successful connection/write check; resolve compatibility deliberately rather than simply suppressing it. |
| Invalid PDF or no extractable text | Upload a valid text-based document; perform OCR separately for scanned PDFs. Permanent content failures require corrected input. |
| Upload or question timed out | Refresh documents/conversation first. The server may have saved the operation; the UI does not automatically replay uncertain mutations. |
| Missing provider key or deployment error | Check the selected provider's `.env` values and the API logs; restart API/worker after changes. |
| Citation validation error | Inspect the request ID and logs. OpenAI/Azure use JSON mode, and malformed answer formats receive one bounded repair attempt using the same evidence. Repaired output must still pass citation checks; invalid citations are not served as a successful answer. Restart FastAPI after pulling this fix. |
| Port already in use | Reuse or stop the existing service. If changing the API port, update `API_BASE_URL` and restart the UI. |

## Logging and stored data

| Location | Contents |
| --- | --- |
| MongoDB database selected by `MONGODB_DATABASE` | Chat history, document metadata, memberships and ingestion jobs |
| Qdrant collections prefixed by `API_QDRANT_COLLECTION_PREFIX` | Embedded passages and retrieval metadata |
| `UPLOAD_DIR` (default `var/uploads/`) | Uploaded original files |
| `logs/app.<PID>.jsonl` | Structured operational events at the configured level, including INFO/WARNING/ERROR |
| `logs/error.<PID>.jsonl` | ERROR events |
| `logs/rag_runs.<PID>.jsonl` | Full QA evaluation captures, only when enabled |

Operational logs rotate using `LOG_MAX_BYTES` (default 10 MiB) and `LOG_BACKUP_COUNT` (default 5). Each process has its own PID-suffixed files. UI requests carry a `client_request_id`, recorded by the API alongside its server request ID for correlation. Operational events avoid raw document text and answer content.

`EVALUATION_CAPTURE_ENABLED=false` is the default. Enabling it stores full questions, answers, history and retrieval evidence in evaluation captures; treat those files as document data. Chat messages and originals persist independently of this setting.

## Code map

| Path | Responsibility |
| --- | --- |
| `src/app.py` | Streamlit entry point |
| `src/ui/` | API client, page composition, document controls, conversation and previews |
| `src/api/` | FastAPI routes, request/response contracts, settings and error handling |
| `src/services/` | Ingestion, QA, scope resolution, retrieval and citation validation |
| `src/workers/ingestion.py` | Durable background processing and retries |
| `src/models/` and `src/repositories/` | Persistent records and MongoDB access |
| `src/storage/` | Original-file storage |
| `src/llms/` | Shared LLM configuration, factory and provider wrappers |
| `src/observability/` | Logging, request context and evaluation captures |
| `src/document_validation.py` | Supported-input validation and parsing |
| `multidoc.md` | Detailed implementation plan and milestone history |

## Verification and current boundaries

Milestones A–E are implemented. The UI/API flow was checked using Streamlit AppTest, real local MongoDB/Qdrant, deterministic embeddings and an offline tool-capable LLM. Those checks cover uploads, failed-file isolation, selection, comparison, citations, removal, chat recovery and request correlation; they do not establish live-provider answer quality.

Citation validation checks labels and quote provenance, not semantic correctness of every claim. Authenticated multi-user access, automatic physical data cleanup, OCR and token streaming remain outside the current implementation.

Milestone F was omitted at the user's request. Existing `src/test_llm.py` and `test_case/` assets have not been migrated to the new multi-document API. Evaluation captures remain available for future evaluation work; this README does not present the older DeepEval runner as a verified test for the current flow.
