import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ChatPage from "../app/chats/[chatId]/page";
import { api, type DocumentItem, type Message } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: {
    chat: vi.fn(), documents: vi.fn(), messages: vi.fn(),
    ask: vi.fn(), upload: vi.fn(), job: vi.fn(),
  },
  contentUrl: (id: string) => "/original/" + id,
  errorText: (error: Error) => error.message,
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function documentFor(chatId: string, status = "ready"): DocumentItem {
  return { document_id: "doc-" + chatId, filename: chatId + ".txt", status,
    chunk_count: 1, ingestion_job_id: null, processing_error: null, warnings: [] };
}

function message(content: string): Message {
  return { id: content, role: "assistant", content, status: "completed",
    citations: [], answer_warnings: [] };
}

const page = (chatId: string) => ChatPage({ params: Promise.resolve({ chatId }) });

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(api.chat).mockImplementation(async id => ({ id, title: "Chat " + id, status: "active" }));
  vi.mocked(api.documents).mockImplementation(async id => [documentFor(id)]);
  vi.mocked(api.messages).mockImplementation(async id => [message("History " + id)]);
});
afterEach(cleanup);

describe("chat switching", () => {
  it.each(["completed", "failed"])("keeps a delayed %s question in the originating chat", async outcome => {
    const request = deferred<{turn_id: string}>();
    vi.mocked(api.ask).mockReturnValue(request.promise);
    const ui = render(await page("A"));
    await screen.findByText("History A");
    fireEvent.change(screen.getByLabelText("Sources"), { target: { value: "selected" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /A.txt/ }));
    fireEvent.change(screen.getByLabelText("Question"), { target: { value: "Question for A" } });
    fireEvent.click(screen.getByRole("button", { name: "Send question" }));
    expect(api.ask).toHaveBeenCalledWith("A", expect.objectContaining({ question: "Question for A", document_ids: ["doc-A"] }));

    ui.rerender(await page("B"));
    await screen.findByText("History B");
    expect((screen.getByLabelText("Question") as HTMLTextAreaElement).value).toBe("");
    expect(screen.queryByText("History A")).toBeNull();
    expect((screen.getByLabelText("Sources") as HTMLSelectElement).value).toBe("all_ready");

    await act(async () => {
      if (outcome === "completed") request.resolve({ turn_id: "turn-A" });
      else request.reject(new Error("Failure in A"));
    });
    expect(screen.queryByText("Failure in A")).toBeNull();
    expect(screen.queryByText("Answer for A")).toBeNull();

    vi.mocked(api.messages).mockImplementation(async id => id === "A"
      ? outcome === "completed" ? [message("Answer for A")]
        : [message("Saved question for A"), { ...message(""), id: "failed-turn", status: "failed" }]
      : [message("History B")]);
    ui.rerender(await page("A"));
    await screen.findByText(outcome === "completed" ? "Answer for A" : "Saved question for A");
    if (outcome === "failed") expect(screen.getByText("failed")).toBeTruthy();
  });

  it("aborts an in-flight job poll and ignores its result after navigation", async () => {
    vi.useFakeTimers();
    try {
      const slow = deferred<DocumentItem[]>();
      let signal: AbortSignal | undefined;
      let loads = 0;
      vi.mocked(api.documents).mockImplementation((id, requestSignal) => {
        if (id === "B") return Promise.resolve([documentFor("B")]);
        if (loads++ === 0) return Promise.resolve([documentFor("A", "uploaded")]);
        signal = requestSignal;
        return slow.promise;
      });
      const ui = render(await page("A"));
      await act(async () => { await Promise.resolve(); });
      await act(async () => { await vi.advanceTimersByTimeAsync(4000); });
      expect(signal).toBeDefined();
      const nextPage = await page("B");
      await act(async () => ui.rerender(nextPage));
      expect(screen.getByText("B.txt")).toBeTruthy();
      expect(signal?.aborted).toBe(true);
      await act(async () => slow.resolve([documentFor("A")]));
      expect(screen.queryByText("A.txt")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps an upload receipt in the chat that submitted it", async () => {
    const upload = deferred<Awaited<ReturnType<typeof api.upload>>>();
    vi.mocked(api.upload).mockReturnValue(upload.promise);
    const ui = render(await page("A"));
    await screen.findByText("A.txt");
    fireEvent.change(screen.getByLabelText("Choose documents"), {
      target: { files: [new File(["A"], "upload-A.txt")] },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add selected files" }));
    expect(api.upload).toHaveBeenCalledWith("A", expect.any(Array));
    ui.rerender(await page("B"));
    await screen.findByText("B.txt");
    await act(async () => upload.resolve({
      accepted: 1, rejected: 0,
      items: [{ filename: "upload-A.txt", status: "queued", error: null, deduplicated: false }],
    }));
    expect(screen.queryByText(/upload-A.txt/)).toBeNull();
  });
});
