"use client";

import { useState, type FormEvent } from "react";
import { api, errorText, type DocumentItem, type Question } from "../lib/api";

export function QuestionComposer({ chatId, documents, pending, onSettled }: {
  chatId: string;
  documents: DocumentItem[];
  pending: boolean;
  onSettled: () => void;
}) {
  const [draft, setDraft] = useState("");
  const [scope, setScope] = useState<Question["scope_mode"]>("all_ready");
  const [strategy, setStrategy] = useState<Question["strategy"]>("general");
  const [selected, setSelected] = useState<string[]>([]);
  const [budget, setBudget] = useState(6);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const ready = documents.filter(doc => doc.status === "ready");
  const ids = ready.filter(doc => selected.includes(doc.document_id)).map(doc => doc.document_id);
  const count = scope === "all_ready" ? ready.length : ids.length;
  let hint = "";
  if (count === 0) hint = scope === "selected" && ready.length
    ? "Select at least one ready document." : "Upload a document and wait until it is ready.";
  else if (strategy === "comparison" && count < 2) hint = "Comparison needs at least two ready documents.";
  else if (strategy === "comparison" && count > budget) hint = "Increase the passage budget or select fewer documents.";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const question = draft.trim();
    if (!question || sending || pending || hint) return;
    setSending(true);
    setError("");
    try {
      await api.ask(chatId, {
        question, scope_mode: scope, strategy, k: budget,
        document_ids: scope === "selected" ? ids : [],
      });
      setDraft("");
    } catch (error) {
      setError(errorText(error));
    } finally {
      onSettled();
      setSending(false);
    }
  }

  return <form className="composer" onSubmit={submit}>
    <fieldset disabled={sending}>
      <div className="composer-options">
        <label>Sources
          <select value={scope} onChange={event => setScope(event.target.value as Question["scope_mode"])}>
            <option value="all_ready">All ready documents</option>
            <option value="selected">Select documents</option>
          </select>
        </label>
        <label>Approach
          <select value={strategy} onChange={event => setStrategy(event.target.value as Question["strategy"])}>
            <option value="general">General</option>
            <option value="comparison">Comparison</option>
          </select>
        </label>
        <label>Passages
          <select value={budget} onChange={event => setBudget(Number(event.target.value))}>
            {Array.from({length: 20}, (_, index) => index + 1).map(value =>
              <option key={value} value={value}>{value}</option>)}
          </select>
        </label>
      </div>
      {scope === "selected" && <div className="source-options">
        {ready.map(doc => <label key={doc.document_id}>
          <input type="checkbox" checked={ids.includes(doc.document_id)}
            onChange={event => {
              const checked = event.target.checked;
              setSelected(current => checked ? [...current, doc.document_id] : current.filter(id => id !== doc.document_id));
            }} />
          {doc.filename} <small>({doc.document_id.slice(0, 8)})</small>
        </label>)}
      </div>}
      <label htmlFor="question">Question</label>
      <textarea id="question" rows={3} maxLength={10000} value={draft}
        onChange={event => setDraft(event.target.value)} placeholder="Ask about your documents…" />
    </fieldset>
    {hint && <p className="muted">{hint}</p>}
    {error && <p role="alert">{error}</p>}
    {(sending || pending) && <p role="status">{sending ? "Preparing an answer…" : "Waiting for conversation history…"}</p>}
    <button disabled={!draft.trim() || !!hint || sending || pending}>Send question</button>
  </form>;
}
