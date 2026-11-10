# Infrastructure

Container images and, in later steps, the deployment setup for the AgenticRAG stack.
Application code stays in `src/` and `frontend/`; everything needed to package and run it
lives under `infra/`.

## Status

This is a skeleton. The application stack is not final yet (the frontend is being migrated
from Streamlit to Next.js), so only the images are defined for now.

| Part | State |
| --- | --- |
| `docker/backend.Dockerfile` | Ready: FastAPI API and ingestion worker |
| `docker/streamlit.Dockerfile` | Placeholder UI until the frontend stack is settled |
| Next.js image | Not started; added once `frontend/` is complete |
| Compose stack, reverse proxy, scripts, CI/CD | Planned in follow-up branches |

## Layout

```
infra/
├── README.md
└── docker/
    ├── backend.Dockerfile
    ├── backend.Dockerfile.dockerignore
    ├── streamlit.Dockerfile
    └── streamlit.Dockerfile.dockerignore
```

Each Dockerfile has its own ignore file next to it (`<name>.Dockerfile.dockerignore`, a
BuildKit feature). Builds still use the repository root as context, but each image only sees
the files it copies.

## Images

| Image | Runs | Port |
| --- | --- | --- |
| backend | `uvicorn src.api.main:app` by default; the worker overrides the command with `python -m src.workers.ingestion` | 8000 |
| streamlit | `streamlit run src/app.py` | 8501 |

Both images run as an unprivileged `app` user and keep runtime data in `/app/logs`,
`/app/var/uploads` (backend) and `/home/app/.cache/huggingface` (model cache). Mount volumes
on those paths so data survives container recreation; the API and the worker must share the
uploads volume.

The backend installs PyTorch from the CPU-only index. Override `TORCH_INDEX_URL` and
`TORCH_VERSION` build arguments only for a GPU host, keeping the version aligned with
`requirements-rag.txt`.

## Build

Run from the repository root (BuildKit is the default builder in current Docker releases):

```sh
docker build -f infra/docker/backend.Dockerfile -t agentic-rag-backend .
docker build -f infra/docker/streamlit.Dockerfile -t agentic-rag-streamlit .
```

## Deployment constraints

The target server is a VMware VM without AVX. MongoDB 5.0 and later require AVX, so the stack
uses `mongo:4.4.30`; see the `infra/mongo44-compat` branch for the related query change.
PyTorch and Qdrant run without AVX, with slower embedding throughput.
