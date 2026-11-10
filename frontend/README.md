# AgenticRAG Next.js frontend

Milestones A–C cover chat navigation, saved conversation history and document management.
Run FastAPI and the ingestion worker from the repository root using the existing README commands.

Install Node.js 22 or later with npm. Then install the pnpm CLI once in your regular terminal.
The frontend lockfile was generated with pnpm 11.25.0.

```sh
node --version
npm --version
npm install -g pnpm@11.25.0
pnpm --version
```

From the repository root:

```sh
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

pnpm creates its package store automatically when installing dependencies. The
`.pnpm-store/` directory seen during development is generated and ignored by Git.
The store location may differ on your machine. Run `pnpm store path` from
`frontend/` to see the actual location.

Open http://localhost:3000. The browser calls FastAPI at http://127.0.0.1:8000.
Set `NEXT_PUBLIC_API_BASE_URL` in `.env.local` for another API address.
Set `FRONTEND_ORIGINS` in the backend environment to a comma-separated list of exact origins
if using a different host or port. The two default origins are localhost:3000 and 127.0.0.1:3000 over HTTP.
Restart FastAPI to load its CORS settings. This UI uses the existing local development identity.

Create a chat, choose multiple files and click **Add selected files**. Each batch sends repeated
`files` multipart fields. Review individual receipts and job statuses. Use **Refresh documents**
after an uncertain upload outcome. The worker must run for queued jobs to become ready.
You can retry recoverable failures, remove attachments and download originals.
Saved conversations and citations are available by chat URL. Use Streamlit to ask new questions
until milestone D adds the composer.
