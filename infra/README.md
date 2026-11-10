# Infrastructure

Container images and deployment setup for the AgenticRAG stack. Application code stays in
`src/` and `frontend/`; everything needed to package and run it lives under `infra/`.

## Status

The application stack is not final yet (the frontend is being migrated from Streamlit to
Next.js). Parts are added in small branches, one concern each.

| Part | State |
| --- | --- |
| `docker/backend.Dockerfile` | Ready: FastAPI API and ingestion worker |
| `docker/streamlit.Dockerfile` | Placeholder UI until the frontend stack is settled |
| `compose/compose.yaml` | Ready: data stores, API, worker and UI on one host |
| Next.js image | Not started; added once `frontend/` is complete |
| Reverse proxy, ops scripts, CI/CD | Planned in follow-up branches |

## Layout

```
infra/
├── README.md
├── .gitignore                 # keeps real env files out of Git
├── compose/
│   └── compose.yaml           # the whole stack
├── docker/
│   ├── backend.Dockerfile
│   ├── backend.Dockerfile.dockerignore
│   ├── streamlit.Dockerfile
│   └── streamlit.Dockerfile.dockerignore
└── env/
    └── stack.env.example      # copy to stack.env and fill in secrets
```

## Architecture

```
            host 127.0.0.1:8501
                    │
 ┌──────────────────┼──────────────── network: agentic-rag_default ──┐
 │                  ▼                                                │
 │   ui (Streamlit) ──HTTP──▶ api (FastAPI :8000) ──┬──▶ mongodb     │
 │                                                  └──▶ qdrant      │
 │   worker (ingestion) ────────────────────────────┬──▶ mongodb     │
 │                                                  └──▶ qdrant      │
 └───────────────────────────────────────────────────────────────────┘
   volumes: mongo_data  qdrant_data  uploads (api + worker)  hf_cache  api_logs  worker_logs
```

- Only the UI is published, on the host loopback interface. Docker-published ports bypass
  `ufw`, so data stores are never published.
- The API and the worker run the same backend image and share the `uploads` volume: the API
  stores originals, the worker reads them. They also share `hf_cache`, so the embedding model
  is downloaded once.
- Logs use one volume per service. The application names log files by PID, and the API and
  the worker get the same PID inside their containers.

## Images

| Image | Runs | Port |
| --- | --- | --- |
| backend | `uvicorn src.api.main:app` by default; the worker overrides the command with `python -m src.workers.ingestion` | 8000 |
| streamlit | `streamlit run src/app.py` | 8501 |

Both images run as an unprivileged `app` user. Each Dockerfile has its own allowlist ignore
file next to it (`<name>.Dockerfile.dockerignore`), so builds use the repository root as
context but each image only sees the files it copies.

The backend installs PyTorch from the CPU-only index. Override the `TORCH_INDEX_URL` and
`TORCH_VERSION` build arguments only for a GPU host, keeping the version aligned with
`requirements-rag.txt`.

## Run the stack

From the repository root:

```sh
cp infra/env/stack.env.example infra/env/stack.env
chmod 600 infra/env/stack.env          # then set OPENAI_API_KEY (or another provider)

docker compose -f infra/compose/compose.yaml --env-file infra/env/stack.env up -d --build
docker compose -f infra/compose/compose.yaml --env-file infra/env/stack.env ps
```

`stack.env` is used twice: Compose reads it (`--env-file`) for image tags, ports and resource
limits, and the api and worker containers load it for provider credentials.

The first start takes a few minutes: the images build, then the API and the worker download
the embedding model into `hf_cache`. Follow progress with:

```sh
docker compose -f infra/compose/compose.yaml logs -f worker
```

Open the UI through an SSH tunnel from your machine:

```sh
ssh -L 8501:127.0.0.1:8501 <user>@<server>
# then browse to http://localhost:8501
```

Stop without losing data with `docker compose ... stop` or `down`. `down -v` deletes the
volumes, including every chat, document and vector.

## Deployment constraints

The target server is a VMware VM without AVX. MongoDB 5.0 and later require AVX, so the stack
uses `mongo:4.4.30` (end of life, therefore kept internal). PyTorch and Qdrant run without AVX;
embedding throughput is lower, roughly 1.5 s per full-length chunk on two cores.
