import { DocumentPanel } from "../../../components/document-panel";
import { MessageList } from "../../../components/message-list";

export default async function ChatPage({ params }: { params: Promise<{chatId: string}> }) {
  const { chatId } = await params;
  return <div className="chat-grid" key={chatId}>
    <DocumentPanel chatId={chatId} />
    <MessageList chatId={chatId} />
  </div>;
}
