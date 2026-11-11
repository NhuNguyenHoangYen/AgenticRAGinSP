"use client";

import { useEffect, useState, type FormEvent } from "react";
import { api, errorText, type Chat, type DocumentItem } from "../lib/api";
import { DocumentPanel } from "./document-panel";
import { MessageList } from "./message-list";

export function ChatWorkspace({ chatId }: { chatId: string }) {
  const [chat, setChat] = useState<Chat | null>(null);
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    api.chat(chatId, controller.signal).then(result => {
      if (!controller.signal.aborted) {
        setChat(result);
        setError("");
      }
    }).catch(error => {
      if (!controller.signal.aborted) setError(errorText(error));
    });
    return () => controller.abort();
  }, [chatId, revision]);

  async function update(action: () => Promise<Chat>) {
    setBusy(true);
    setError("");
    try {
      setChat(await action());
      window.dispatchEvent(new Event("agenticrag:chats-changed"));
    } catch (error) {
      setError(errorText(error));
    } finally {
      setBusy(false);
    }
  }

  function rename(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const title = String(new FormData(event.currentTarget).get("title") ?? "").trim();
    if (title && title !== chat?.title) void update(() => api.renameChat(chatId, title));
  }

  if (!chat) return <section className="panel">
    {error ? <><p role="alert">{error}</p>
      <button onClick={() => setRevision(value => value + 1)}>Reload chat</button></>
      : <p role="status">Loading chat…</p>}
  </section>;

  const archived = chat.status === "archived";
  return <>
    <section className="panel chat-header">
      <h1>{chat.title}</h1>
      {archived ? <p>Archived chat. Restore it to edit or ask questions.</p>
        : <form key={chat.title} className="rename-form" onSubmit={rename}>
          <label>Chat title <input name="title" defaultValue={chat.title} maxLength={120} required /></label>
          <button className="secondary" disabled={busy}>Rename</button>
        </form>}
      <button className="secondary" disabled={busy}
        onClick={() => void update(() => api.setArchived(chatId, !archived))}>
        {archived ? "Restore chat" : "Archive chat"}
      </button>
      {error && <p role="alert">{error}</p>}
    </section>
    <div className="chat-grid">
      <DocumentPanel chatId={chatId} documents={documents} setDocuments={setDocuments} readOnly={archived} />
      <MessageList chatId={chatId} documents={documents} readOnly={archived} />
    </div>
  </>;
}
