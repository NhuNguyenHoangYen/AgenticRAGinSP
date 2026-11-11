"use client";

import { useEffect, useState } from "react";
import { api, contentUrl, errorText, type DocumentItem, type Message } from "../lib/api";

import { QuestionComposer } from "./question-composer";

export function MessageList({ chatId, documents, readOnly }: {
  chatId: string; documents: DocumentItem[]; readOnly: boolean;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const items = await api.messages(chatId, controller.signal);
        if (controller.signal.aborted) return;
        setMessages(items);
        setError("");
        if (items.some(message => message.status === "pending" || message.status === "generating")) {
          timer = setTimeout(refresh, 4000);
        }
      } catch (error) {
        if (!controller.signal.aborted) setError(errorText(error));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [chatId, revision, documents]);
  const pending = messages.some(message => message.status === "pending" || message.status === "generating");
  return <section className="panel">
    <div className="actions"><h2>Conversation history</h2>
      <button className="secondary" onClick={() => setRevision(value => value + 1)}>Refresh</button>
    </div>
    <div className="messages" tabIndex={0} aria-label="Saved messages">
      {loading && <p role="status">Loading messages…</p>}
      {error && <p role="alert">{error}</p>}
      {!loading && !error && !messages.length && <p className="muted">No saved messages yet.</p>}
      {messages.map(message => <article className="message" key={message.id}>
        <strong>{message.role === "user" ? "You" : "Assistant"}</strong>
        {message.status !== "completed" && <span className="badge">{message.status}</span>}
        <p className="message-text">{message.content}</p>
        {message.answer_warnings.map((warning, index) => <p key={index}>{warning}</p>)}
        {message.citations.map(citation => <details key={citation.label}>
          <summary>[{citation.label}] {citation.filename} · {citation.page ? `page ${citation.page}` : citation.section || "Document text"}</summary>
          <blockquote>{citation.quote}</blockquote>
          {!citation.attached && <p className="muted">Removed from this chat</p>}
          <a href={contentUrl(citation.document_id)}>Download source</a>
        </details>)}
      </article>)}
    </div>
    {!readOnly && <QuestionComposer chatId={chatId} documents={documents} pending={pending || loading || !!error}
      onSettled={() => { setLoading(true); setRevision(value => value + 1); }} />}
  </section>;
}
