# AgenticRAG - AI-Powered Agent with Smart Conversation and Retrieval-Augmented Generation

## 🚀 Overview

**AgenticRAG** is an advanced **AI-powered retrieval-augmented generation (RAG) Agent** designed to provide users with an interactive and intelligent conversational experience. Built using **LangChain**, it leverages an intelligent agent capable of retrieving relevant chunks from a custom `AI index Report 2025` based on the user's query. The agent is equipped with **memory** to handle ongoing conversations and can determine whether to perform a RAG process based on the query’s nature.

The application allows users to interact with the AI agent, either by asking questions or engaging in casual conversation. The agent responds promptly and smartly, while using RAG for information retrieval only when needed, ensuring efficiency.

## 📒 DeepWiki Explanation
<a href="https://deepwiki.com/MohammedAly22/AgenticRAG" target="_blank">
  <img src="https://img.shields.io/badge/Open%20in-DeepWiki-blue?logo=readthedocs&style=for-the-badge" alt="Open in DeepWiki"/>
</a>

## 📜 Table of Contents

- [Architecture](#-architecture)
- [Features](#-features)
- [Installation & Setup](#-installation--setup)
- [Usage](#-usage)
- [Technologies Used](#-technologies-used)
- [Future Enhancements](#-future-enhancements)

---

## 🏗️ Architecture
![AgenticRAG-Architecuture-3](https://github.com/user-attachments/assets/814b3ba3-a708-43da-98b9-4a98bf7a4f05)

The system follows a **Retrieval-Augmented Generation (RAG)** architecture that combines both conversational AI and information retrieval, powered by LangChain. The process involves:

1. **Agent Creation**: The LangChain agent is set up with the ability to perform multiple tasks: casual conversation or RAG, depending on the query type.
2. **Memory & Context**: The agent is designed to remember prior interactions, allowing it to engage in context-aware conversations.
3. **Query Analysis**: When a user submits a query, the agent first analyzes whether it’s a general conversational query or one that requires retrieving detailed data (e.g., "Provide the table of contents of this report"). In addition, there is a query re-formulation part for better retrieval.
4. **RAG Execution**: If the query demands more specific information, the agent performs RAG to retrieve relevant document chunks from the **AI Index Report 2025**.
5. **Reasoning Steps**: The agent can provide detailed reasoning steps for RAG queries, depending on the user's preference. The agent decides whether to show intermediate results or skip to the final answer.

---
### **Basic RAG Architecture**

The RAG system is composed of:
- **Memory**: Stores prior interactions and updates context.
- **Retrieval Tool**: Retrieves relevant document chunks from the `AI Index Report 2025`.
- **Generation Tool**: Uses LLMs for generating responses, either as final answers or with reasoning steps.
  
---

## ✨ Features

✅ **Agentic RAG System**: The agent intelligently decides whether to perform a RAG process based on the query.\
✅ **Smart Memory**: The agent remembers previous interactions, allowing for context-aware conversations.\
✅ **Conditional RAG Execution**: If the query requires it, the agent performs RAG by retrieving relevant chunks from the AI Index Report 2025.\
✅ **Reasoning Steps**: Users can opt to see the intermediate reasoning steps used by the agent when processing the query.\
✅ **Natural Conversations**: The agent can handle casual conversational queries (e.g., "Hello, how are you?") without performing RAG.\
✅ **User-Controlled Reasoning**: The user can control whether to view the reasoning steps or just the final answer, providing flexibility in how the agent responds.\
✅ **Streamlit Interface**: A user-friendly interface that shows the agent’s responses and reasoning steps interactively.

---

## 🔧 Installation & Setup

### **1️⃣ Clone the Repository**

```sh
git clone https://github.com/MohammedAly22/AgenticRAG.git
cd AgenticRAG
```

### **2️⃣ Create and Activate Virtual Environment**
```sh
python -m venv agentic-rag-env
source agentic-rag-env/bin/activate  # On macOS/Linux
agentic-rag-env\Scripts\activate  # On Windows
```

### **3️⃣ Install Dependencies**
```sh
pip install -r requirements.txt
```

### Configure the answer-generation model

The project loads `.env` from the repository root. Existing shell environment
variables take precedence. Copy `.env.example` to `.env` if needed, then edit:

```dotenv
LLM_PROVIDER=openai
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4.1-mini
COHERE_API_KEY=
COHERE_MODEL=command-a-03-2025
```

To use Cohere for answers, set `LLM_PROVIDER=cohere` and supply `COHERE_API_KEY`.
Without LLM_PROVIDER, the code defaults to Cohere for backward compatibility.
Restart Streamlit after changing `.env`. The local `.env` is ignored by Git;
`.env.example` contains only configuration placeholders.

The LLM provider and embedding provider are independent. With OpenAI answers,
choose Hugging Face embeddings in the sidebar to avoid requiring a Cohere key.
Cohere embeddings still require `COHERE_API_KEY`. OpenAI API usage is billed
separately from ChatGPT subscriptions. The default OpenAI model supports tool
calling: https://developers.openai.com/api/docs/models/gpt-4.1-mini

### Start the Qdrant vector database

With Docker Desktop running, start the local Qdrant service from the project root:

```sh
docker compose up -d qdrant
```

The client connects to `http://localhost:6333` by default. Configure `.env` with:

```dotenv
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION_NAME=index-ai-report-2025
QDRANT_API_KEY=
```

Leave QDRANT_API_KEY empty for this local service. Document embeddings are still
generated by the chosen Cohere or Hugging Face model; Qdrant stores and searches
them. Data persists in the Docker volume `qdrant_data` across container restarts.
The service is bound to this laptop's loopback address.

If Qdrant is already running on port 6333, use that service and skip the Compose
startup. The dependency pins and Compose image target Qdrant 1.14 and support the
project's Python 3.9 environments. An existing Qdrant 1.20 server passed the
indexing/retrieval smoke test, but the older client emits a compatibility warning.
For a 1.20 deployment, use Python 3.10+ and a matching qdrant-client version:

```sh
python -m pip install qdrant-client==1.20.0
```


The application creates a missing collection using the embedding model's actual
vector size and cosine distance. Existing collections are reused and validated,
never automatically deleted. Use a different QDRANT_COLLECTION_NAME when changing
embedding models, including models with identical vector dimensions.

Existing Chroma data is not migrated. Re-upload the PDF to index it in Qdrant.
The current collection contains all documents uploaded to it, so use separate
collections if document isolation is needed. Restart Streamlit after changing .env.

Run the indexing integration checks without calling embedding APIs:

```sh
python -m unittest discover -s tests -v
```

### **4️⃣ Run the Application**
```sh
streamlit run src/app.py
```

### **5️⃣ View the Interface**
After following the above instructions, you may expect to see this interface:

![image](https://github.com/user-attachments/assets/0fcd80b4-f649-4b43-85b4-58ebfc89449a)


## 📖 Usage
1. Open the app in your browser (default: http://localhost:8501).

2. Enter your `COHERE_API_KEY` in its proper place; both `trial` and `production` keys work properly.

![image](https://github.com/user-attachments/assets/84c8d8d1-8605-48c9-8d62-23d2bd14a536)

3. Select an **Embedding Model**  - Note: The `cohere/embed-v4.0` model, when used with a `trial_key`, is limited to processing `100,000` tokens per minute. This rate limit may cause slower processing for large documents like the `AI Index Report 2025` due to enforced waiting between batches. However, despite the slower throughput, it is much more efficient and accurate compared to `sentence-transformers/all-mpnet-base-v2`, especially for high-quality semantic embeddings.

4. Upload the `2025 AI Index Report` in the file uploader area. Once you upload it, it starts processing the PDF, splitting it, creating chunks, and indexing it into the `Qdrant` vector store.

![image](https://github.com/user-attachments/assets/40203fca-c876-4cb0-b856-548cad33db63)


5. Select how many pages you want to render in the UI. Limits the number of previewed pages from the uploaded PDF to improve performance, as rendering more pages takes longer. A maximum of **100** pages can be previewed.

6. Engage in a conversation with the AI agent or ask it to retrieve information from the AI Index Report 2025.


**Examples**:

- **Casual Conversation**: If you ask, *“Hello, how are you?”*, the agent will greet you without performing any RAG.

![image](https://github.com/user-attachments/assets/423be581-04a5-46c1-9829-5560f8febc68)

- **Specific Query**:
  - If you ask, *“Provide me with the complete welcome message from the co-directors of the report”*, the agent will perform RAG, retrieve relevant chunks, and generate an appropriate response.

![image](https://github.com/user-attachments/assets/e759d61b-c25b-4cd6-9912-2ef4e2c5c881)

  - Here is the same example but with `Show Reasoning Steps` enabled:

![image](https://github.com/user-attachments/assets/df3c6c33-b51d-4fb7-bc58-44af10780bda)
    


## 🔧 Technologies Used
- **LangChain** - For building the intelligent agent with memory and retrieval-augmented generation capabilities.

- **Cohere** - LLM used for generation and embedding tasks (providing *responses*).

- **Qdrant** - Vector database for storing and retrieving document chunks.

- **Streamlit** - Interactive UI for easy user interaction.

## 🔮 Future Enhancements
- ✅ Multi-model support for more flexible generation (e.g., OpenAI GPT models).

- ✅ Multi-modal support for chatting with images and tables.

- ✅ Enhanced memory management for long-term, context-aware conversations.

- ✅ Fine-tuned retrieval with advanced filtering and re-ranking techniques.

- ✅ Multi-turn conversations with long-term memory and reasoning enhancements.

## 💬 Have Questions?
Reach out on GitHub or open an issue!

---
🎯 AgenticRAG - Your Intelligent AI Agent for Smart Conversations and Data Retrieval! 🚀
