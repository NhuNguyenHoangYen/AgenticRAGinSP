# syntax=docker/dockerfile:1.7
#
# Streamlit UI image. It only talks to the API over HTTP (API_BASE_URL), so it
# needs the UI and logging packages, not the RAG or database stack.
#
# Placeholder until the team settles the frontend stack: the Next.js frontend
# in frontend/ is still being migrated and will get its own image.
#
# Build from the repository root:
#   docker build -f infra/docker/streamlit.Dockerfile -t agentic-rag-streamlit .

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN groupadd --system app \
    && useradd --system --gid app --create-home --home-dir /home/app app

# ---------------------------------------------------------------------------
# Dependencies (cached separately from the code, as in the backend image)
# ---------------------------------------------------------------------------
COPY requirements-ui.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements-ui.txt

# ---------------------------------------------------------------------------
# Application code: only the modules the UI imports.
# ---------------------------------------------------------------------------
COPY src/__init__.py src/app.py src/style.css ./src/
COPY src/ui ./src/ui
COPY src/observability ./src/observability

RUN mkdir -p logs && chown -R app:app logs

USER app

# ---------------------------------------------------------------------------
# Streamlit must listen on all interfaces inside the container. Headless mode
# and disabled usage stats avoid interactive prompts and outbound telemetry.
# ---------------------------------------------------------------------------
EXPOSE 8501
CMD ["python", "-m", "streamlit", "run", "src/app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", \
     "--server.headless=true", "--browser.gatherUsageStats=false"]
