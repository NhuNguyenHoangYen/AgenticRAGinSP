"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState, type FormEvent } from "react";
import { api, errorText, type Chat } from "../lib/api";

export function ChatSidebar() {
  const router = useRouter();
  const { chatId } = useParams<{chatId?: string}>();
  const [chats, setChats] = useState<Chat[]>([]);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    api.chats(controller.signal).then(list => {
      setChats(list);
      setError("");
    }).catch(error => {
      if (!controller.signal.aborted) setError(errorText(error));
    });
    return () => controller.abort();
  }, [revision]);

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const title = String(new FormData(form).get("title") || "").trim() || "New chat";
    setBusy(true);
    setError("");
    try {
      const chat = await api.createChat(title);
      setChats(current => [chat, ...current.filter(item => item.id !== chat.id)]);
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
    <nav aria-label="Chats">
      {chats.map(chat => <Link key={chat.id} href={`/chats/${encodeURIComponent(chat.id)}`}
        aria-current={chat.id === chatId ? "page" : undefined}>{chat.title}</Link>)}
    </nav>
  </aside>;
}
