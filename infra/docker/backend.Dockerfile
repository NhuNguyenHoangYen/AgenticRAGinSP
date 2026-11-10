# syntax=docker/dockerfile:1.7
#
# Backend image shared by the FastAPI service and the ingestion worker.
# Both run the same code; only the start command differs (see CMD below).
#
# Build from the repository root so that src/ is inside the build context:
#   docker build -f infra/docker/backend.Dockerfile -t agentic-rag-backend .

FROM python:3.11-slim

# ---------------------------------------------------------------------------
# Runtime defaults
#   PYTHONDONTWRITEBYTECODE  no .pyc files inside the image
#   PYTHONUNBUFFERED         logs reach `docker logs` immediately
#   HF_HOME                  Hugging Face model cache, owned by the app user;
#                            mount a volume here to avoid re-downloading models
# ---------------------------------------------------------------------------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HF_HOME=/home/app/.cache/huggingface

WORKDIR /app

# Unprivileged user. Files written at runtime (logs, uploads, model cache)
# stay owned by a normal user instead of root.
RUN groupadd --system app \
    && useradd --system --gid app --create-home --home-dir /home/app app

# ---------------------------------------------------------------------------
# Dependencies
# Installed before the source code is copied, so code-only changes reuse the
# cached layers and do not reinstall PyTorch.
#
# PyTorch is installed first from the CPU-only index. The default PyPI wheel
# bundles CUDA libraries (several GB) that a CPU server never uses. The pinned
# version must match requirements-rag.txt so pip treats it as satisfied.
# ---------------------------------------------------------------------------
ARG TORCH_VERSION=2.7.0
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install "torch==${TORCH_VERSION}" --index-url "${TORCH_INDEX_URL}"

COPY requirements-backend.txt requirements-rag.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements-backend.txt

# ---------------------------------------------------------------------------
# Application code
# The settings resolve paths from the project root (/app): logs/ and
# var/uploads/ are created here and handed to the app user.
# ---------------------------------------------------------------------------
COPY src ./src

RUN mkdir -p logs var/uploads "${HF_HOME}" \
    && chown -R app:app logs var /home/app

USER app

# ---------------------------------------------------------------------------
# Default command: FastAPI on all interfaces inside the container.
# The worker reuses this image with:
#   python -m src.workers.ingestion
# Health checks are defined per service in Compose, because the API and the
# worker need different checks.
# ---------------------------------------------------------------------------
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
