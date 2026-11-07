import os
import tempfile
import hashlib
from uuid import uuid4

from langchain_cohere import CohereEmbeddings
from langchain_core.messages import HumanMessage

import streamlit as st
from streamlit_pdf_viewer import pdf_viewer

# local
from utils import (
    load_pdf,
    create_embeddings,
    split_documents,
    build_vector_store,
    process_query,
    process_chunks_with_rate_limit_cohere,
    add_chunks_to_vector_store_hf_embeddings,
    reset_memory,
)

from src.llms.llm_config import LLMConfig
from src.observability import (
    RequestContext, configure_logging, get_logger, request_context,
)

configure_logging()
log = get_logger(__name__)


# Page configuration
st.set_page_config(
    page_title="AI Index Report 2025 - RAG Agent",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)


# Set custom CSS styling
with open("src/style.css") as f:
    st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# Main title
st.title("🤖 AI Index Report 2025 - RAG Agent")
st.markdown(
    "Ask questions about the AI Index Report 2025 and get intelligent responses."
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
mohammed_avatar = "docs/Mohammed_avatar.png"
agent_avatar = "docs/agent_avatar.png"


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
    uploaded_file = st.file_uploader("Upload Your PDF", type="pdf")

    if uploaded_file and (
        st.session_state.uploaded_file is None
        or uploaded_file.name != st.session_state.uploaded_file.name
    ):
        document_id = hashlib.sha256(uploaded_file.getvalue()).hexdigest()
        context = RequestContext.create(
            st.session_state.user_id, st.session_state.chat_id,
            ingestion_id=uuid4().hex, document_id=document_id,
        )
        with request_context(context), st.spinner("Processing PDF..."):
            pdf_path = None
            stage = "configuration"
            try:
                log.info("ingestion.started", embedding_model=embeddings_type)
                if embeddings_type.startswith("cohere") and not cohere_api_key:
                    raise ValueError("Please enter your Cohere API key to process the document.")
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                    tmp_file.write(uploaded_file.getvalue())
                    pdf_path = tmp_file.name
                stage = "pdf_parsing"
                docs = load_pdf(pdf_path)
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
                st.session_state.docs = docs
                st.session_state.vector_store = vector_store
                st.session_state.rag_agent_executer = None
                st.session_state.uploaded_file = uploaded_file
                st.session_state.document_id = document_id
                st.session_state.embedding_model = embeddings_type
                log.info("ingestion.completed", page_count=len(docs), chunk_count=len(chunks))
                st.success(f"Indexed {len(docs)} pages as {len(chunks)} chunks.")
            except Exception:
                log.exception("ingestion.failed", stage=stage)
                st.error("Could not index the document. Check the application logs for details.")
            finally:
                if pdf_path:
                    try:
                        os.unlink(pdf_path)
                    except OSError:
                        log.warning("ingestion.temp_cleanup_failed")

    # Number of rendered pages
    page_count = min(len(st.session_state.docs), 100)
    number_of_rendered_page = st.slider(
        "Number of PDF Rendered Pages",
        min_value=0,
        max_value=max(page_count, 1),
        value=min(30, page_count),
        disabled=page_count == 0,
        help="Limits the number of previewed pages from the uploaded "
        "PDF to improve performance, as rendering more pages takes "
        "longer. A maximum of `100` pages can be previewed.",
    )
    st.session_state.rendered_pages = number_of_rendered_page

    # Show a status indicator for document loading
    if st.session_state.vector_store is not None:
        st.sidebar.success("✅ Document loaded and indexed successfully!")
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
        "⚠️ Please upload the AI Index Report 2025 PDF in the sidebar to continue."
    )


pdf_preview, chat_area = st.columns(2)

# PDF preview container
with pdf_preview:

    if uploaded_file:
        with st.container(border=True):
            binary_data = uploaded_file.getvalue()
            pdf_viewer(
                input=binary_data,
                height=600,
                pages_to_render=[*range(st.session_state.rendered_pages)],
                resolution_boost=2,
                pages_vertical_spacing=1,
                render_text=True,
            )

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
        query = st.chat_input("Ask a question about the AI Index Report 2025...")

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
