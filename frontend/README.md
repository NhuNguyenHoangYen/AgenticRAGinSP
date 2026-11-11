# AgenticRAG Next.js frontend

Milestones A–D cover chat navigation, document management, questions and saved citations.
Run FastAPI and the ingestion worker from the repository root using the existing README commands.

Install Node.js 22 or later with npm. Then install the pnpm CLI once in your regular terminal.
The frontend lockfile was generated with pnpm 11.25.0.

```sh
node --version
npm --version
cd frontend
npx --yes pnpm@11.25.0 install --frozen-lockfile
npx --yes pnpm@11.25.0 dev
```

Open http://localhost:3000. The browser calls FastAPI at http://127.0.0.1:8000.
Set `NEXT_PUBLIC_API_BASE_URL` in `.env.local` for another API address.
Set `FRONTEND_ORIGINS` in the backend environment to a comma-separated list of exact origins
if using a different host or port. The two default origins are localhost:3000 and 127.0.0.1:3000 over HTTP.
Restart FastAPI to load its CORS settings. This UI uses the existing local development identity.

Create a chat, choose multiple files and click **Add selected files**. Each batch sends repeated
`files` multipart fields. Review individual receipts and job statuses. Use **Refresh documents**
after an uncertain upload outcome. The worker must run for queued jobs to become ready.
You can retry recoverable failures, remove attachments and download originals.
Open a saved chat by URL and ask a question after its documents become ready.
Choose all ready documents or a subset. Comparison requires at least two ready documents
and one passage slot per source. The conversation refreshes after each question.
