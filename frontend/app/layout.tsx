import type { Metadata } from "next";
import type { ReactNode } from "react";
import { ChatSidebar } from "../components/chat-sidebar";
import "./styles.css";

export const metadata: Metadata = { title: "AgenticRAG", description: "Document chat workspace" };
export default function Layout({ children }: { children: ReactNode }) {
  return <html lang="en"><body><div className="shell"><ChatSidebar /><main>{children}</main></div></body></html>;
}
