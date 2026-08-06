"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import MathMarkdown from "./components/MathMarkdown";

type Stats = {
  documents: number;
  chunks: number;
  page_start: number | null;
  page_end: number | null;
  block_types: Record<string, number>;
  embedding_model?: string | null;
};

type Message = {
  id?: number;
  role: "user" | "assistant";
  content: string;
  verification?: string;
  verificationLevel?: string;
  verificationLabel?: string;
  verificationNotes?: string[];
};

type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

type Memory = {
  id: number;
  content: string;
  source_conversation_id?: string | null;
  created_at: string;
  updated_at: string;
};

type ToolStatus = {
  openai: { configured: boolean; model: string };
  sage: { available: boolean; engine?: string };
  lean: { available: boolean; engine?: string };
  embedding?: { model: string; configured: boolean; dimensions: number };
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const CLIENT_KEY = "nt_client_id";

const WELCOME: Message = {
  role: "assistant",
  content:
    "Chapter 1 is ready. Ask about divisibility, Euclid’s algorithm, Bézout’s lemma, linear congruences, the Chinese Remainder Theorem, and prime factorization. Answers use LaTeX and carry a V0–V4 correctness level.",
  verificationLevel: "system",
  verificationLabel: "System",
};

function badgeClass(level?: string): string {
  switch (level) {
    case "V4":
      return "verification v4";
    case "V3":
      return "verification v3";
    case "V2":
      return "verification v2";
    case "V1":
      return "verification v1";
    case "retrieval_only":
      return "verification retrieval";
    default:
      return "verification v0";
  }
}

function ensureClientId(): string {
  const existing = window.localStorage.getItem(CLIENT_KEY);
  if (existing && existing.length >= 8) return existing;
  const created =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `client-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  window.localStorage.setItem(CLIENT_KEY, created);
  return created;
}

function formatTime(value: string): string {
  try {
    return new Date(value).toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return "";
  }
}

export default function Home() {
  const [clientId, setClientId] = useState("");
  const [stats, setStats] = useState<Stats | null>(null);
  const [tools, setTools] = useState<ToolStatus | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([WELCOME]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [input, setInput] = useState("");
  const [memoryDraft, setMemoryDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState("");

  const refreshConversations = useCallback(async (cid: string) => {
    const response = await fetch(`${API_BASE}/api/conversations?client_id=${encodeURIComponent(cid)}`);
    if (!response.ok) throw new Error("Failed to load conversations");
    const data: Conversation[] = await response.json();
    setConversations(data);
    return data;
  }, []);

  const refreshMemories = useCallback(async (cid: string) => {
    const response = await fetch(`${API_BASE}/api/memories?client_id=${encodeURIComponent(cid)}`);
    if (!response.ok) throw new Error("Failed to load memories");
    setMemories(await response.json());
  }, []);

  const loadConversation = useCallback(async (cid: string, conversationId: string) => {
    setSwitching(true);
    setError("");
    try {
      const response = await fetch(
        `${API_BASE}/api/conversations/${conversationId}/messages?client_id=${encodeURIComponent(cid)}`,
      );
      if (!response.ok) throw new Error("Failed to load chat history");
      const data = await response.json();
      const mapped: Message[] = data.map(
        (item: {
          id: number;
          role: "user" | "assistant";
          content: string;
          verification_level?: string;
          verification_label?: string;
          verification_notes?: string[];
        }) => ({
          id: item.id,
          role: item.role,
          content: item.content,
          verificationLevel: item.verification_level,
          verificationLabel: item.verification_label,
          verificationNotes: item.verification_notes ?? [],
        }),
      );
      setActiveId(conversationId);
      setMessages(mapped.length > 0 ? mapped : [WELCOME]);
    } finally {
      setSwitching(false);
    }
  }, []);

  useEffect(() => {
    const cid = ensureClientId();
    setClientId(cid);

    Promise.all([
      fetch(`${API_BASE}/api/library/stats`),
      fetch(`${API_BASE}/api/tools/status`),
      refreshConversations(cid),
      refreshMemories(cid),
    ])
      .then(async ([statsResponse, toolsResponse, convs]) => {
        if (!statsResponse.ok || !toolsResponse.ok) throw new Error("Failed to load system status");
        setStats(await statsResponse.json());
        setTools(await toolsResponse.json());
        if (convs.length > 0) {
          await loadConversation(cid, convs[0].id);
        }
      })
      .catch((reason: Error) => setError(reason.message));
  }, [loadConversation, refreshConversations, refreshMemories]);

  async function startNewChat() {
    if (!clientId || loading) return;
    setActiveId(null);
    setMessages([WELCOME]);
    setError("");
  }

  async function removeConversation(conversationId: string) {
    if (!clientId) return;
    const response = await fetch(
      `${API_BASE}/api/conversations/${conversationId}?client_id=${encodeURIComponent(clientId)}`,
      { method: "DELETE" },
    );
    if (!response.ok) {
      setError("Failed to delete conversation");
      return;
    }
    const remaining = await refreshConversations(clientId);
    if (activeId === conversationId) {
      if (remaining.length > 0) {
        await loadConversation(clientId, remaining[0].id);
      } else {
        setActiveId(null);
        setMessages([WELCOME]);
      }
    }
  }

  async function addMemoryManually(event: FormEvent) {
    event.preventDefault();
    const content = memoryDraft.trim();
    if (!clientId || !content) return;
    const response = await fetch(`${API_BASE}/api/memories`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ client_id: clientId, content }),
    });
    if (!response.ok) {
      setError("Failed to add memory");
      return;
    }
    setMemoryDraft("");
    await refreshMemories(clientId);
  }

  async function removeMemory(memoryId: number) {
    if (!clientId) return;
    const response = await fetch(
      `${API_BASE}/api/memories/${memoryId}?client_id=${encodeURIComponent(clientId)}`,
      { method: "DELETE" },
    );
    if (!response.ok) {
      setError("Failed to delete memory");
      return;
    }
    await refreshMemories(clientId);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const question = input.trim();
    if (!question || loading || !clientId) return;

    setMessages((current) => [...current, { role: "user", content: question }]);
    setInput("");
    setLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: question,
          limit: 5,
          client_id: clientId,
          conversation_id: activeId,
        }),
      });
      if (!response.ok) throw new Error("Failed to get a reply");
      const data = await response.json();
      setActiveId(data.conversation_id);
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: data.answer,
          verification: data.verification,
          verificationLevel: data.verification_level,
          verificationLabel: data.verification_label,
          verificationNotes: data.verification_notes ?? [],
        },
      ]);
      await refreshConversations(clientId);
      if (data.new_memories?.length) {
        await refreshMemories(clientId);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }

  const activeTitle =
    conversations.find((item) => item.id === activeId)?.title ?? (activeId ? "Chat" : "New chat");

  return (
    <main className="shell">
      <aside className="sidebar">
        <div>
          <p className="eyebrow">NUMBER THEORY</p>
          <h1>Number Theory Agent</h1>
          <p className="subtitle">Correctness first, starting from one reliable chapter.</p>
        </div>

        <button className="newChatBtn" disabled={loading} onClick={startNewChat} type="button">
          + New chat
        </button>

        <section className="conversationSection">
          <h2>Chats</h2>
          <div className="conversationList">
            {conversations.length === 0 && <p className="emptyHint">No saved chats yet</p>}
            {conversations.map((item) => (
              <div
                className={`conversationItem ${item.id === activeId ? "active" : ""}`}
                key={item.id}
              >
                <button
                  className="conversationMain"
                  onClick={() => loadConversation(clientId, item.id)}
                  type="button"
                >
                  <span className="conversationTitle">{item.title}</span>
                  <span className="conversationTime">{formatTime(item.updated_at)}</span>
                </button>
                <button
                  aria-label="Delete chat"
                  className="iconBtn"
                  onClick={() => removeConversation(item.id)}
                  type="button"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        </section>

        <section className="memorySection">
          <h2>Long-term memory</h2>
          <p className="sectionHint">Remember learning goals and preferences across chats</p>
          <ul className="memoryList">
            {memories.length === 0 && (
              <li className="emptyHint">No memories yet — they are extracted from chat</li>
            )}
            {memories.map((item) => (
              <li key={item.id}>
                <span>{item.content}</span>
                <button
                  aria-label="Delete memory"
                  className="iconBtn"
                  onClick={() => removeMemory(item.id)}
                  type="button"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
          <form className="memoryForm" onSubmit={addMemoryManually}>
            <input
              onChange={(event) => setMemoryDraft(event.target.value)}
              placeholder="Add a memory manually"
              value={memoryDraft}
            />
            <button disabled={!memoryDraft.trim()} type="submit">
              Add
            </button>
          </form>
        </section>

        <section className="statusCard compact">
          <div className="statusHeading">
            <span className="statusDot" />
            Library
          </div>
          <dl>
            <div>
              <dt>Docs / chunks</dt>
              <dd>
                {stats?.documents ?? "—"} / {stats?.chunks ?? "—"}
              </dd>
            </div>
            <div>
              <dt>Checks</dt>
              <dd className="smallDd">
                {[
                  tools?.openai.configured ? "Model" : null,
                  tools?.sage.available ? "Sage" : null,
                  tools?.lean.available ? "Lean" : null,
                ]
                  .filter(Boolean)
                  .join(" · ") || "—"}
              </dd>
            </div>
          </dl>
        </section>
      </aside>

      <section className="chatPanel">
        <header className="chatHeader">
          <div>
            <span className="chapterTag">HILL · CHAPTER 1</span>
            <h2>{activeTitle}</h2>
          </div>
          <span className="modeTag">
            {tools?.openai.configured ? "OPENAI · V0–V4 gating" : "Retrieval mode"}
          </span>
        </header>

        <div className="messages" aria-live="polite">
          {switching ? (
            <p className="thinking">Loading chat…</p>
          ) : (
            messages.map((message, index) => (
              <article className={`message ${message.role}`} key={message.id ?? `${message.role}-${index}`}>
                <div className="avatar">{message.role === "assistant" ? "N" : "You"}</div>
                <div className="bubble">
                  {message.role === "assistant" ? (
                    <MathMarkdown content={message.content} />
                  ) : (
                    <p>{message.content}</p>
                  )}
                  {message.role === "assistant" && message.verificationLabel && (
                    <div className={badgeClass(message.verificationLevel)}>
                      <span>{message.verificationLabel}</span>
                      {message.verificationNotes && message.verificationNotes.length > 0 && (
                        <ul>
                          {message.verificationNotes.slice(0, 4).map((note) => (
                            <li key={note}>{note}</li>
                          ))}
                        </ul>
                      )}
                    </div>
                  )}
                </div>
              </article>
            ))
          )}
          {loading && <p className="thinking">Retrieving, generating, and gating for correctness…</p>}
        </div>

        <div className="composerWrap">
          {error && <p className="error">{error}</p>}
          <form className="composer" onSubmit={submit}>
            <textarea
              aria-label="Ask a number theory question"
              onChange={(event) => setInput(event.target.value)}
              placeholder="e.g. How do I compute $\gcd(391,299)$ with Euclid’s algorithm?"
              rows={2}
              value={input}
            />
            <button disabled={loading || !input.trim() || !clientId} type="submit">
              Ask
            </button>
          </form>
          <p className="notice">
            V4 means the Lean formal statement passed; V2 means a concrete computation passed.
            Problem translation and general proofs still need human review.
          </p>
        </div>
      </section>
    </main>
  );
}
