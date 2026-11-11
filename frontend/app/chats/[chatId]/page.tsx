import { ChatWorkspace } from "../../../components/chat-workspace";

export default async function ChatPage({ params }: { params: Promise<{chatId: string}> }) {
  const { chatId } = await params;
  return <ChatWorkspace key={chatId} chatId={chatId} />;
}
