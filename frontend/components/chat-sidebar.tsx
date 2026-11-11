"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { api, errorText, type Chat, type ChatStatus } from "../lib/api";

export function ChatSidebar() {
  const router = useRouter();
  const { chatId } = useParams<{chatId?: string}>();
  const [status, setStatus] = useState<ChatStatus>("active");
  const [chats, setChats] = useState<Chat[]>([]);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    api.chats(controller.signal, status).then(list => {
      if (controller.signal.aborted) return;
      setChats(list);
      setError("");
    }).catch(error => {
      if (!controller.signal.aborted) setError(errorText(error));
    });
    return () => controller.abort();
  }, [revision, status]);

  useEffect(() => {
    const refresh = () => setRevision(value => value + 1);
    window.addEventListener("agenticrag:chats-changed", refresh);
    return () => window.removeEventListener("agenticrag:chats-changed", refresh);
  }, []);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const title = String(new FormData(form).get("title") || "").trim() || "New chat";
    setBusy(true);
    setError("");
    try {
      const chat = await api.createChat(title);
      setStatus("active");
      setRevision(value => value + 1);
      form.reset();
      router.push(`/chats/${encodeURIComponent(chat.id)}`);
    } catch (error) {
      setError(errorText(error));
    } finally {
      setBusy(false);
    }
  }

  return <aside className="sidebar">
    <Link href="/" className="brand">AgenticRAG</Link>
    <p className="muted">Local development workspace</p>
    <form onSubmit={create}>
      <label htmlFor="chat-title">Chat title</label>
      <input id="chat-title" name="title" maxLength={120} placeholder="New chat" />
      <button disabled={busy}>{busy ? "Creating…" : "Create chat"}</button>
    </form>
    {error && <p role="alert">{error}</p>}
    <button className="secondary" onClick={() => setRevision(value => value + 1)}>Refresh chats</button>
    <label className="chat-filter">Show chats
      <select value={status} onChange={event => {
        setChats([]);
        setStatus(event.target.value as ChatStatus);
      }}>
        <option value="active">Active</option>
        <option value="archived">Archived</option>
      </select>
    </label>
    <nav aria-label="Chats">
      {chats.map(chat => <Link key={chat.id} href={`/chats/${encodeURIComponent(chat.id)}`}
        aria-current={chat.id === chatId ? "page" : undefined}>{chat.title}</Link>)}
    </nav>
  </aside>;
}
