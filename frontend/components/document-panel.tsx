"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { api, contentUrl, errorText, type DocumentItem, type Job, type Receipt, type ReusableDocument } from "../lib/api";

export function DocumentPanel({ chatId, documents, setDocuments, readOnly }: {
  chatId: string;
  documents: DocumentItem[];
  readOnly: boolean;
  setDocuments: (documents: DocumentItem[]) => void;
}) {
  const [library, setLibrary] = useState<ReusableDocument[] | null>(null);
  const [jobs, setJobs] = useState<Record<string, Job>>({});
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pollError, setPollError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    let pending = false;
    async function refresh() {
      try {
        const list = await api.documents(chatId, controller.signal);
        if (controller.signal.aborted) return;
        setDocuments(list);
        pending = list.some(doc => doc.status !== "ready" && doc.status !== "failed");
        const results = await Promise.allSettled(list.filter(doc => doc.status !== "ready" && doc.ingestion_job_id)
          .map(async doc => [doc.document_id, await api.job(doc.ingestion_job_id!, controller.signal)] as const));
        if (controller.signal.aborted) return;
        setJobs(Object.fromEntries(results.flatMap(result => result.status === "fulfilled" ? [result.value] : [])));
        const failed = results.find(result => result.status === "rejected");
        setPollError(failed?.status === "rejected" ? errorText(failed.reason) : "");
      } catch (error) {
        if (!controller.signal.aborted) setPollError(errorText(error));
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
          if (pending) timer = setTimeout(refresh, 4000);
        }
      }
    }
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [chatId, revision, setDocuments]);

  async function mutate(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (error) {
      setError(errorText(error));
    } finally {
      setBusy(false);
      setRevision(value => value + 1);
    }
  }

  function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const mib = 1024 * 1024;
    if (!files.length || busy || readOnly) return;
    if (files.length > 10 || files.some(file => file.size > 50 * mib) ||
        files.reduce((size, file) => size + file.size, 0) > 100 * mib) {
      setError("Choose at most 10 files, 50 MiB per file and 100 MiB per batch.");
      return;
    }
    setReceipts([]);
    void mutate(async () => {
      const result = await api.upload(chatId, files);
      setReceipts(result.items);
      setFiles([]);
      if (input.current) input.current.value = "";
    });
  }

  const available = library?.filter(item => !documents.some(doc => doc.document_id === item.id));

  return <section className="panel">
    <h2>Documents</h2>
    {!readOnly && <form onSubmit={upload}>
      <label htmlFor="documents">Choose documents</label>
      <input id="documents" ref={input} type="file" multiple accept=".pdf,.docx,.txt,.md,.csv"
        disabled={busy} onChange={event => setFiles(Array.from(event.target.files ?? []))} />
      <p className="muted">10 files per batch · 50 MiB each · 100 MiB total</p>
      <button disabled={busy || !files.length}>{busy ? "Working…" : "Add selected files"}</button>
    </form>}
    {!readOnly && <div className="document-library">
      <button className="secondary" disabled={busy} onClick={() => {
        if (library) setLibrary(null);
        else void mutate(async () => setLibrary(await api.reusableDocuments()));
      }}>{library ? "Close document library" : "Add an indexed document"}</button>
      {available && (available.length ? <ul aria-label="Reusable documents">
          {available.map(item => <li key={item.id}>
            {item.filename} <small>({item.id.slice(0, 8)})</small>{" "}
            <button className="secondary" disabled={busy}
              onClick={() => void mutate(async () => {
                await api.attach(chatId, item.id);
                setLibrary(null);
              })}>Attach</button>
          </li>)}
        </ul> : <p className="muted">No other compatible ready documents.</p>)}
    </div>}
    {error && <p role="alert">{error}</p>}
    {pollError && <p role="alert">{pollError}</p>}
    {receipts.length > 0 && <ul aria-label="Upload results" className="receipts">
      {receipts.map((item, index) => <li key={index}>
        {item.filename} · {item.status}{item.deduplicated ? " (reused)" : ""}{item.error ? ` — ${item.error}` : ""}
      </li>)}
    </ul>}
    <button className="secondary" onClick={() => setRevision(value => value + 1)}>Refresh documents</button>
    {loading && <p role="status">Loading documents…</p>}
    {!loading && !pollError && !documents.length && <p className="muted">No documents attached.</p>}
    {documents.map(doc => {
      const job = jobs[doc.document_id];
      return <article className="document" key={doc.document_id}>
        <strong>{doc.filename}</strong> <span className="badge">{doc.status}</span>
        {job && <p className="muted">{job.stage} · attempt {job.attempt}/{job.max_attempts}
          {job.total > 0 ? ` · ${job.completed}/${job.total}` : ""}</p>}
        {(doc.processing_error || job?.error) && <p role="alert">{doc.processing_error || job?.error}</p>}
        {doc.warnings.map((warning, index) => <p key={index}>{warning}</p>)}
        <div className="actions">
          <a href={contentUrl(doc.document_id)}>Download original</a>
          {!readOnly && job?.status === "failed" && !job.non_retryable && doc.ingestion_job_id &&
            <button className="secondary" disabled={busy} onClick={() => void mutate(() => api.retry(doc.ingestion_job_id!))}>Retry</button>}
          {!readOnly && <button className="secondary" disabled={busy} onClick={() => void mutate(() => api.detach(chatId, doc.document_id))}>Remove from chat</button>}
        </div>
      </article>;
    })}
  </section>;
}
