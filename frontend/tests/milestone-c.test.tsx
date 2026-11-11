import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ChatWorkspace } from "../components/chat-workspace";
import { api } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: { chat: vi.fn(), documents: vi.fn(), messages: vi.fn(), reusableDocuments: vi.fn(), attach: vi.fn() },
  contentUrl: (id: string) => "/original/" + id,
  errorText: (error: Error) => error.message,
}));

afterEach(cleanup);

it("adds a compatible indexed file to the selected chat without an upload", async () => {
  vi.mocked(api.chat).mockResolvedValue({ id: "B", title: "Chat B", status: "active" });
  vi.mocked(api.documents).mockResolvedValue([]);
  vi.mocked(api.messages).mockResolvedValue([]);
  vi.mocked(api.reusableDocuments).mockResolvedValue([{ id: "shared", filename: "report.txt", file_type: "txt" }]);
  vi.mocked(api.attach).mockImplementation(async () => {
    vi.mocked(api.documents).mockResolvedValue([{
      document_id: "shared", filename: "report.txt", status: "ready", chunk_count: 1,
      ingestion_job_id: null, processing_error: null, warnings: [],
    }]);
    return { changed: true };
  });
  render(<ChatWorkspace chatId="B" />);
  fireEvent.click(await screen.findByRole("button", { name: "Add an indexed document" }));
  fireEvent.click(await screen.findByRole("button", { name: /^Attach$/ }));
  await waitFor(() => expect(api.attach).toHaveBeenCalledWith("B", "shared"));
  await screen.findByText("report.txt", { selector: "strong" });
  expect(screen.queryByRole("button", { name: /^Attach$/ })).toBeNull();
});
