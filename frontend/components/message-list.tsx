"use client";

import { useEffect, useState } from "react";
import { api, contentUrl, errorText, type Message } from "../lib/api";

export function MessageList({ chatId }: { chatId: string }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    api.messages(chatId, controller.signal).then(items => {
      setMessages(items);
      setError("");
    }).catch(error => {
      if (!controller.signal.aborted) setError(errorText(error));
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [chatId, revision]);
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
    <p className="muted">Use Streamlit to send new questions during the migration.</p>
  </section>;
}
