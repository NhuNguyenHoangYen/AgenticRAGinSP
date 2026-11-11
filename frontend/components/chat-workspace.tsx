"use client";

import { useState } from "react";
import type { DocumentItem } from "../lib/api";
import { DocumentPanel } from "./document-panel";
import { MessageList } from "./message-list";

export function ChatWorkspace({ chatId }: { chatId: string }) {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  return <div className="chat-grid">
    <DocumentPanel chatId={chatId} documents={documents} setDocuments={setDocuments} />
    <MessageList chatId={chatId} documents={documents} />
  </div>;
}
