const assert = require("node:assert/strict");
const test = require("node:test");
const { mock } = test;
const migration = require("../scripts/20261111000100-backfill-chat-membership.js");

function fixture(rows, chats = [{ _id: "old", owner_id: "owner" }]) {
  const query = mock.fn(() => ({
    sort: () => (async function* () { yield* rows; })(),
  }));
  const updateOne = mock.fn(async () => {});
  const find = mock.fn(() => (async function* () { yield* chats; })());
  return {
    db: { collection: name => name === "chats" ? { find, updateOne } : { find: query } },
    query, updateOne, find,
  };
}

test("empty database produces no updates", async () => {
  const f = fixture([], []);
  await migration.up(f.db);
  assert.equal(f.updateOne.mock.callCount(), 0);
});

test("backfill scopes by owner, deduplicates and updates only uninitialized chats", async () => {
  const f = fixture([{ document_id: "a" }, { document_id: "b" }, { document_id: "a" }]);
  await migration.up(f.db);
  assert.deepEqual(f.query.mock.calls[0].arguments[0], { chat_id: "old", owner_id: "owner" });
  assert.deepEqual(f.updateOne.mock.calls[0].arguments, [
    { _id: "old", owner_id: "owner", status: { $ne: "deleted" }, membership_initialized: { $ne: true } },
    { $set: { document_ids: ["a", "b"], membership_initialized: true } },
  ]);
});

test("a chat with 101 unique attachments is left unmodified", async () => {
  const f = fixture(Array.from({length: 101}, (_, i) => ({ document_id: String(i) })));
  await assert.rejects(migration.up(f.db), /100-document limit/);
  assert.equal(f.updateOne.mock.callCount(), 0);
});
