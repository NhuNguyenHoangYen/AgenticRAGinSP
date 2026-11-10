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
| `compose/compose.yaml` | Ready: data stores, API, worker, UI and proxy on one host |
| `proxy/nginx.conf` | Ready: single entry point with Basic Auth |
| Next.js image | Not started; added once `frontend/` is complete |
| Ops scripts, CI/CD | Planned in follow-up branches |

## Layout

```
infra/
├── README.md
├── .gitattributes             # LF line endings for everything here
├── .gitignore                 # keeps env files and htpasswd out of Git
├── compose/
│   └── compose.yaml           # the whole stack
├── docker/
│   ├── backend.Dockerfile
│   ├── backend.Dockerfile.dockerignore
│   ├── streamlit.Dockerfile
│   └── streamlit.Dockerfile.dockerignore
├── env/
│   └── stack.env.example      # copy to stack.env and fill in secrets
├── proxy/
│   └── nginx.conf             # htpasswd is created next to it, untracked
└── scripts/
    └── create-htpasswd.sh
```

## Architecture

```
         PROXY_BIND:PROXY_PORT  (default 127.0.0.1:8080)
                    │  Basic Auth
 ┌──────────────────┼──────────────────── network: agentic-rag_default ──┐
 │                  ▼                                                    │
 │   proxy (nginx) ──/──────────▶ ui (Streamlit :8501)                   │
 │                 ──/api/, /health/──▶ api (FastAPI :8000) ──┬──▶ mongodb│
 │                                                            └──▶ qdrant │
 │   ui ──HTTP──▶ api                                                     │
 │   worker (ingestion) ──────────────────────────────────────┬──▶ mongodb│
 │                                                            └──▶ qdrant │
 └────────────────────────────────────────────────────────────────────────┘
   volumes: mongo_data  qdrant_data  uploads (api + worker)  hf_cache  api_logs  worker_logs
```

- The proxy is the only published service. Docker-published ports bypass `ufw`, so nothing
  else is published, and the proxy binds to loopback unless `PROXY_BIND` says otherwise.
- The application has no sign-in yet (one shared development identity), so the proxy requires
  HTTP Basic Auth on every route except its own `/healthz`.
- `/api/` is routed already so the browser-based Next.js frontend can call the API from the
  same origin, without CORS.
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
| proxy | `nginxinc/nginx-unprivileged` with `proxy/nginx.conf` | 8080 |

All images run as unprivileged users. Each Dockerfile has its own allowlist ignore file next
to it (`<name>.Dockerfile.dockerignore`), so builds use the repository root as context but each
image only sees the files it copies.

The backend installs PyTorch from the CPU-only index. Override the `TORCH_INDEX_URL` and
`TORCH_VERSION` build arguments only for a GPU host, keeping the version aligned with
`requirements-rag.txt`.

## Run the stack

From the repository root:

```sh
# 1. Configuration and secrets
cp infra/env/stack.env.example infra/env/stack.env
chmod 600 infra/env/stack.env          # then set OPENAI_API_KEY (or another provider)

# 2. At least one Basic Auth user for the proxy
infra/scripts/create-htpasswd.sh mentor

# 3. Build and start
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

### Access

With the default `PROXY_BIND=127.0.0.1`, open an SSH tunnel from your machine:

```sh
ssh -L 8080:127.0.0.1:8080 <user>@<server>
# then browse to http://localhost:8080
```

To serve the LAN directly, set `PROXY_BIND=0.0.0.0` and recreate the proxy
(`docker compose ... up -d proxy`). Traffic is plain HTTP, so Basic Auth credentials cross the
network unencrypted: use this only on a trusted network, or put TLS in front.

After adding or changing users, reload the proxy:

```sh
docker compose -f infra/compose/compose.yaml exec proxy nginx -s reload
```

### Behind an existing host nginx

If the host already runs nginx on port 80 (as on the current server), keep `PROXY_BIND` on
loopback and add a host site that forwards to it. This needs root on the host:

```nginx
server {
    listen 80;
    server_name agentic-rag.example.internal;
    client_max_body_size 110m;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 1h;
    }
}
```

### Stop

`docker compose ... stop` or `down` keeps the data. `down -v` deletes the volumes, including
every chat, document and vector.

## Deployment constraints

The target server is a VMware VM without AVX. MongoDB 5.0 and later require AVX, so the stack
uses `mongo:4.4.30` (end of life, therefore kept internal). PyTorch and Qdrant run without AVX;
embedding throughput is lower, roughly 1.5 s per full-length chunk on two cores.
