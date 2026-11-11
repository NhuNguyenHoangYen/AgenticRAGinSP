# MongoDB migrations

The migration CLI uses Node.js 22 or later and a pinned `migrate-mongo` dependency. Run these commands from the repository root with MongoDB running.

```sh
cd migrations
npx --yes pnpm@11.25.0 install --frozen-lockfile
npx --yes pnpm@11.25.0 run db:status
```

The CLI reads `MONGODB_URI` and `MONGODB_DATABASE` from the root `.env`. Environment variables set in the shell take precedence. The defaults match the Python backend. Use literal values for these settings so Node and Python resolve the same database. Each database records applied scripts in its own `schema_migrations` collection.

Review pending scripts and verify the target database. For a local upgrade, stop FastAPI and the ingestion worker before running the following command, then restart them after it succeeds.

```sh
npx --yes pnpm@11.25.0 run db:up
npx --yes pnpm@11.25.0 run db:status
```

Run one migration process per database. The API still creates collections and indexes on startup. On a fresh database, the membership migration finds no chats, and the API creates the application collections when it starts.

## Chat membership backfill

The first migration copies the owner-matching attachment IDs from `chat_documents` into `chats.document_ids` for legacy chats. It preserves order, removes duplicate IDs, and marks each migrated chat initialized. Chats already initialized keep their authoritative membership. Chat IDs, message records, attachment rows, original files, and Qdrant indexes remain available.

A legacy chat with more than 100 distinct attachments stops the migration. Resolve that chat's membership before rerunning. Earlier successfully updated chats are skipped on retry. This migration is forward-only because later attachment changes make reconstructing the old state ambiguous. Take a MongoDB backup before applying it to a database whose data you need to recover.

## Adding a migration

```sh
npx --yes pnpm@11.25.0 run db:create describe-the-change
```

Add the new script under `scripts/`. Use conditional updates that can be retried after interruption. Review changes on an empty database and a copy with existing records before applying them to shared data. Treat applied migration files as immutable and use a new file for subsequent changes.
