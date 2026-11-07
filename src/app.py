import os
import sys
from pathlib import Path
import hashlib
from uuid import uuid4

from langchain_cohere import CohereEmbeddings
from langchain_core.messages import HumanMessage

import streamlit as st
from streamlit_pdf_viewer import pdf_viewer

# Streamlit may put only src/ on sys.path when executing this file directly.
# Resolve the project package independently of the launch directory.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.utils import (
    load_document,
    create_embeddings,
    split_documents,
    build_vector_store,
    process_query,
    process_chunks_with_rate_limit_cohere,
    add_chunks_to_vector_store_hf_embeddings,
    reset_memory,
)

from src.llms.llm_config import LLMConfig
from src.document_validation import DocumentValidationError, DocumentValidator
from src.observability import (
    RequestContext, configure_logging, get_logger, request_context,
)

configure_logging()
log = get_logger(__name__)


# Page configuration
st.set_page_config(
    page_title="Document Chatbot",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)


# Set custom CSS styling
with (PROJECT_ROOT / "src" / "style.css").open(encoding="utf-8") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# Main title
st.title("🤖 Document Chatbot")
st.markdown(
    "Upload a document and ask questions grounded in its contents."
)

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []

if "vector_store" not in st.session_state:
    st.session_state.vector_store = None

if "uploaded_file" not in st.session_state:
    st.session_state.uploaded_file = None

if "rendered_pages" not in st.session_state:
    st.session_state.rendered_pages = None

if "show_reasoning" not in st.session_state:
    st.session_state.show_reasoning = False

if "rag_agent_executer" not in st.session_state:
    st.session_state.rag_agent_executer = None

if "docs" not in st.session_state:
    st.session_state.docs = []


# Anonymous identifiers are session-local, not authenticated user identities.
for identity in ("user_id", "chat_id"):
    if identity not in st.session_state:
        st.session_state[identity] = uuid4().hex


# Load message avatars
mohammed_avatar = str(PROJECT_ROOT / "docs" / "Mohammed_avatar.png")
agent_avatar = str(PROJECT_ROOT / "docs" / "agent_avatar.png")


# Sidebar for API key and settings
with st.sidebar:
    st.header("📝 1. Configuration")

    # 1. Cohere API Key
    cohere_api_key = st.text_input(
        "Cohere API Key (required for Cohere embeddings or LLM)",
        value=os.getenv("COHERE_API_KEY", ""),
        type="password",
        placeholder="Enter you Cohere API key",
    )
    if cohere_api_key:
        os.environ["COHERE_API_KEY"] = cohere_api_key

    llm_config_error = None
    try:
        llm_config = LLMConfig.from_env(cohere_api_key=cohere_api_key)
    except ValueError as error:
        llm_config_error = str(error)
    else:
        st.caption(f"Answer generation: {llm_config.provider} (configured in .env)")

    # 2. Select an embedding model
    embeddings_type = st.selectbox(
        "Select an Embedding Model",
        [
            "cohere/embed-v4.0",
            "sentence-transformers/all-mpnet-base-v2",
        ],
        help="**Note**: The `cohere/embed-v4.0` model, when used with a `trial_key`, "
        "is limited to processing **100,000** tokens per minute. This rate limit may "
        "cause **slower** processing for large documents due to enforced waiting "
        "between batches. However, despite the slower throughput, it is much more "
        "efficient and accurate compared to `sentence-transformers/all-mpnet-base-v2`"
        "especially for high-quality semantic embeddings.",
    )

    # Show reasoning steps toggle
    st.session_state.show_reasoning = st.toggle(
        "Show Reasoning Steps",
        st.session_state.show_reasoning,
        help="Controls whether to display the agent's intermediate reasoning "
        "steps—such as decisions and tool calls. When disabled, only the final "
        "answer will be shown.",
    )

    st.subheader("📄 2. Document Upload")

    # File uploader
    uploaded_file = st.file_uploader(
        "Upload a document", type=list(DocumentValidator.supported_extensions),
        help="PDF, DOCX, TXT, Markdown (.md), CSV. Maximum 50 MB. Scanned/image-only files need OCR first.",
    )

    document_id = hashlib.sha256(uploaded_file.getvalue()).hexdigest() if uploaded_file else None
    upload_key = (document_id, uploaded_file.name, embeddings_type) if uploaded_file else None
    if uploaded_file and upload_key != st.session_state.get("upload_key"):
        context = RequestContext.create(
            st.session_state.user_id, st.session_state.chat_id,
            ingestion_id=uuid4().hex, document_id=document_id,
        )
        with request_context(context), st.spinner("Validating and indexing document..."):
            stage = "configuration"
            try:
                log.info("ingestion.started", embedding_model=embeddings_type)
                if embeddings_type.startswith("cohere") and not cohere_api_key:
                    raise ValueError("Please enter your Cohere API key to process the document.")
                stage = "document_validation"
                parsed = load_document(uploaded_file.getvalue(), uploaded_file.name)
                docs = parsed.documents
                for warning in parsed.warnings:
                    st.warning(warning)
                stage = "chunking"
                chunks = split_documents(docs)
                for position, chunk in enumerate(chunks):
                    chunk.metadata.update(document_id=document_id,
                                          chunk_id=f"{document_id}:{position}")
                stage = "embedding_setup"
                embeddings = create_embeddings(embeddings_type, cohere_api_key=cohere_api_key)
                log.info("embedding.initialized", embedding_model=embeddings_type)
                stage = "indexing"
                vector_store = build_vector_store(embeddings)
                if isinstance(embeddings, CohereEmbeddings):
                    process_chunks_with_rate_limit_cohere(chunks, vector_store)
                else:
                    add_chunks_to_vector_store_hf_embeddings(chunks, vector_store)
                # Commit the new active document only after successful indexing.
                st.session_state.messages = []
                st.session_state.chat_id = uuid4().hex
                st.session_state.upload_key = upload_key
                st.session_state.file_type = parsed.extension
                st.session_state.docs = docs
                st.session_state.vector_store = vector_store
                st.session_state.rag_agent_executer = None
                st.session_state.uploaded_file = uploaded_file
                st.session_state.document_id = document_id
                st.session_state.embedding_model = embeddings_type
                log.info("ingestion.completed", section_count=len(docs), chunk_count=len(chunks), file_type=parsed.extension)
                st.success(f"Indexed {parsed.filename} as {len(chunks)} chunks.")
            except DocumentValidationError as error:
                log.warning("ingestion.rejected", stage=stage, message=str(error))
                st.error(str(error))
            except Exception:
                log.exception("ingestion.failed", stage=stage)
                st.error("Could not index the document. Check the application logs for details.")
    # Page controls only apply to the active PDF, including blank original pages.
    st.session_state.rendered_pages = 0
    if st.session_state.get("file_type") == "pdf" and st.session_state.docs:
        page_count = min(st.session_state.docs[0].metadata["total_pages"], 100)
        st.session_state.rendered_pages = st.slider(
            "PDF preview pages", min_value=0, max_value=page_count,
            value=min(30, page_count),
            help="Preview up to 100 original PDF pages. All extractable text is indexed.",
        )

    # Show a status indicator for document loading
    if st.session_state.vector_store is not None:
        st.sidebar.success(f"Active document: {st.session_state.uploaded_file.name}")
    else:
        st.sidebar.warning("⚠️ No document loaded")

    # Clear conversation button
    st.subheader("🗑️ 3. Clear Chat History (Optional)")
    if st.button("Clear Conversation"):
        if len(st.session_state.messages):
            st.session_state.messages = []
            st.success("✅ Conversation cleared successfully!")
            reset_memory()
            st.session_state.chat_id = uuid4().hex
        else:
            st.info("There are no messages to clear!")


# Disprning if necessary components are missing
if llm_config_error:
    st.warning(llm_config_error)

elif not st.session_state.vector_store:
    st.warning(
        "⚠️ Please upload a supported document in the sidebar to continue."
    )


pdf_preview, chat_area = st.columns(2)

# Preview the successfully indexed document, not a rejected replacement.
with pdf_preview:
    active_file = st.session_state.uploaded_file
    if active_file:
        st.caption(f"Active document: {active_file.name}")
        with st.container(border=True):
            if st.session_state.get("file_type") == "pdf":
                if st.session_state.rendered_pages:
                    try:
                        pdf_viewer(
                            input=active_file.getvalue(), height=600,
                            pages_to_render=list(range(1, st.session_state.rendered_pages + 1)),
                            resolution_boost=2, pages_vertical_spacing=1, render_text=True,
                        )
                    except Exception:
                        log.exception("document.preview_failed")
                        st.warning("The PDF preview could not be rendered; you can still ask questions about its extracted text.")
            else:
                preview = "\n\n".join(doc.page_content for doc in st.session_state.docs)
                st.text_area("Extracted text preview", preview[:20000], height=600, disabled=True)
                if len(preview) > 20000:
                    st.caption("Preview limited to 20,000 characters; all extracted text is indexed.")

# Chat container
if st.session_state.vector_store:
    with chat_area:
        chat_container = st.container(height=585, border=False)

        # Display chat history
        with chat_container:
            for message in st.session_state.messages:
                if isinstance(message, HumanMessage):
                    with st.chat_message("user", avatar=mohammed_avatar):
                        st.markdown(message.content)
                else:
                    with st.chat_message("assistant", avatar=agent_avatar):
                        st.markdown(message.content)

        # Chat input
        query = st.chat_input("Ask a question about your document...")

        if query:
            # Display user message
            with chat_container:
                with st.chat_message("user", avatar=mohammed_avatar):
                    st.markdown(query)

                # user message to session state
                st.session_state.messages.append(HumanMessage(content=query))

                # Process the query
                context = RequestContext.create(
                    st.session_state.user_id, st.session_state.chat_id,
                    turn_id=uuid4().hex,
                    document_id=st.session_state.get("document_id"),
                )
                with request_context(context):
                    process_query(query, cohere_api_key, agent_avatar)
