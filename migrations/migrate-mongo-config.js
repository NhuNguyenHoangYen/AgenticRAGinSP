const { existsSync } = require("node:fs");
const { resolve } = require("node:path");

const envPath = resolve(__dirname, "../.env");
if (existsSync(envPath)) process.loadEnvFile(envPath);

const databaseName = process.env.MONGODB_DATABASE ?? "agentic_rag";
if (!/^[A-Za-z0-9_-]{1,64}$/.test(databaseName) || ["admin", "local", "config"].includes(databaseName)) {
  throw new Error("MONGODB_DATABASE must name an application database");
}

module.exports = {
  mongodb: {
    url: process.env.MONGODB_URI ?? "mongodb://127.0.0.1:27017",
    databaseName,
    options: { serverSelectionTimeoutMS: Number(process.env.MONGODB_TIMEOUT_MS ?? 5000) },
  },
  migrationsDir: resolve(__dirname, "scripts"),
  changelogCollectionName: "schema_migrations",
  lockCollectionName: "schema_migrations_lock",
  lockTtl: 0,
  migrationFileExtension: ".js",
  useFileHash: false,
  moduleSystem: "commonjs",
};
