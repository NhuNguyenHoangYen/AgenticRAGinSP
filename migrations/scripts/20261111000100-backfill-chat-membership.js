const legacyChat = {
  status: { $ne: "deleted" },
  membership_initialized: { $ne: true },
};

module.exports = {
  async up(db) {
    const chats = db.collection("chats");
    const attachments = db.collection("chat_documents");

    for await (const chat of chats.find(legacyChat, { projection: { owner_id: 1 } })) {
      const ids = new Set();
      const rows = attachments.find(
        { chat_id: chat._id, owner_id: chat.owner_id },
        { projection: { document_id: 1 } },
      ).sort({ created_at: 1, _id: 1 });

      for await (const row of rows) {
        ids.add(row.document_id);
        if (ids.size > 100) {
          throw new Error(`Chat ${chat._id} exceeds the 100-document limit`);
        }
      }

      await chats.updateOne(
        { ...legacyChat, _id: chat._id, owner_id: chat.owner_id },
        { $set: { document_ids: [...ids], membership_initialized: true } },
      );
    }
  },

  async down() {
    throw new Error("Chat membership is authoritative after this migration. Restore a database backup to revert it.");
  },
};
