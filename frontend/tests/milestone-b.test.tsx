import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ChatWorkspace } from "../components/chat-workspace";
import { api } from "../lib/api";

vi.mock("../lib/api", () => ({
  api: { chat: vi.fn(), documents: vi.fn(), messages: vi.fn(), setArchived: vi.fn(), renameChat: vi.fn() },
  contentUrl: (id: string) => "/original/" + id,
  errorText: (error: Error) => error.message,
}));

afterEach(cleanup);

it("renames, archives and restores the same chat while preserving history", async () => {
  const chat = { id: "same-id", title: "Original", status: "active" as const };
  vi.mocked(api.chat).mockResolvedValue(chat);
  vi.mocked(api.documents).mockResolvedValue([]);
  vi.mocked(api.messages).mockResolvedValue([
    { id: "1", role: "user", content: "Saved question", status: "completed", citations: [], answer_warnings: [] },
  ]);
  vi.mocked(api.renameChat).mockResolvedValue({ ...chat, title: "Renamed" });
  vi.mocked(api.setArchived).mockResolvedValueOnce({ ...chat, title: "Renamed", status: "archived" })
    .mockResolvedValueOnce({ ...chat, title: "Renamed" });

  render(<ChatWorkspace chatId={chat.id} />);
  await screen.findByText("Saved question");
  fireEvent.change(screen.getByLabelText("Chat title"), { target: { value: "Renamed" } });
  fireEvent.click(screen.getByRole("button", { name: "Rename" }));
  await screen.findByRole("heading", { name: "Renamed" });
  expect(api.renameChat).toHaveBeenCalledWith(chat.id, "Renamed");
  fireEvent.click(screen.getByRole("button", { name: "Archive chat" }));
  await screen.findByRole("button", { name: "Restore chat" });
  expect(screen.queryByLabelText("Question")).toBeNull();
  expect(screen.queryByLabelText("Choose documents")).toBeNull();
  expect(screen.getByText("Saved question")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Restore chat" }));
  await screen.findByLabelText("Question");
  expect(api.setArchived).toHaveBeenNthCalledWith(1, chat.id, true);
  expect(api.setArchived).toHaveBeenNthCalledWith(2, chat.id, false);
});
