"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import ChatComposer from "./components/ChatComposer";
import GoogleLogin from "./components/GoogleLogin";
import ThinkingStatus, { LoadingStatus, streamChat } from "./components/ThinkingStatus";
import LeanWorkbench from "./components/LeanWorkbench";
import AutoProve from "./components/AutoProve";
import ModeDropdown, { ANSWER_MODE_OPTIONS, TEACH_DEPTH_OPTIONS } from "./components/ModeDropdown";
import MathMarkdown from "./components/MathMarkdown";
import MemoryPanel from "./components/MemoryPanel";
import NotebookPanel from "./components/NotebookPanel";
import { API_BASE, apiFetch, type AuthUser } from "./lib/api";

type Message = {
  id?: number;
  role: "user" | "assistant";
  content: string;
  images?: string[];
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
};

type LabResult = {
  operation: string;
  args: string;
  ok: boolean;
  output: string;
};

type NotebookEntry = {
  id: number;
  kind: "experiment" | "conjecture" | "counterexample";
  title: string;
  content: string;
  payload: Record<string, unknown>;
  created_at: string;
};

type TeachDepth = "hint" | "socratic" | "full";

type AnswerMode = "auto" | "teach" | "solve" | "research";
type RightView = "chat" | "lean" | "auto-prove" | "notebook" | "memory";

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

function placeholderFor(mode: AnswerMode): string {
  switch (mode) {
    case "solve":
      return "Ask a problem to solve…";
    case "teach":
      return "Ask something you'd like to understand…";
    case "research":
      return "Ask about the literature or open questions…";
    default:
      return "Ask anything…";
  }
}

export default function Home() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [tools, setTools] = useState<ToolStatus | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [input, setInput] = useState("");
  const [pendingImages, setPendingImages] = useState<string[]>([]);
  const [rightView, setRightView] = useState<RightView>("chat");
  const [answerMode, setAnswerMode] = useState<AnswerMode>("auto");
  const [teachDepth, setTeachDepth] = useState<TeachDepth>("full");
  const [memoryDraft, setMemoryDraft] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingStatus, setLoadingStatus] = useState<LoadingStatus | null>(null);
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState("");
  const [labOp, setLabOp] = useState<string>("gcd");
  const [labArgs, setLabArgs] = useState("");
  const [labSplit, setLabSplit] = useState("");
  const [labBusy, setLabBusy] = useState(false);
  const [labResults, setLabResults] = useState<LabResult[]>([]);
  const [notebook, setNotebook] = useState<NotebookEntry[]>([]);
  const [conjectureDraft, setConjectureDraft] = useState("");
  const composerFormRef = useRef<HTMLFormElement>(null);

  const refreshConversations = useCallback(async () => {
    const response = await apiFetch("/api/conversations");
    if (!response.ok) throw new Error("Failed to load conversations");
    const data: Conversation[] = await response.json();
    setConversations(data);
    return data;
  }, []);

  const refreshMemories = useCallback(async () => {
    const response = await apiFetch("/api/memories");
    if (!response.ok) throw new Error("Failed to load memories");
    setMemories(await response.json());
  }, []);

  const refreshNotebook = useCallback(async () => {
    const response = await apiFetch("/api/notebook");
    if (!response.ok) throw new Error("Failed to load notebook");
    setNotebook(await response.json());
  }, []);

  const loadConversation = useCallback(async (conversationId: string) => {
    setSwitching(true);
    setError("");
    try {
      const response = await apiFetch(`/api/conversations/${conversationId}/messages`);
      if (!response.ok) throw new Error("Failed to load chat history");
      const data = await response.json();
      const mapped: Message[] = data.map(
        (item: {
          id: number;
          role: "user" | "assistant";
          content: string;
          attachments?: string[];
        }) => ({
          id: item.id,
          role: item.role,
          content: item.content,
          images: item.attachments?.length ? item.attachments : undefined,
        }),
      );
      setActiveId(conversationId);
      setRightView("chat");
      setMessages(mapped);
    } finally {
      setSwitching(false);
    }
  }, []);

  const loadWorkspace = useCallback(async () => {
    const [toolsResponse, convs] = await Promise.all([
      apiFetch("/api/tools/status"),
      refreshConversations(),
      refreshMemories(),
      refreshNotebook(),
    ]);
    if (!toolsResponse.ok) throw new Error("Failed to load system status");
    setTools(await toolsResponse.json());
    if (convs.length > 0) {
      await loadConversation(convs[0].id);
    }
  }, [loadConversation, refreshConversations, refreshMemories, refreshNotebook]);

  useEffect(() => {
    apiFetch("/api/auth/me")
      .then(async (response) => {
        if (!response.ok) {
          setUser(null);
          return;
        }
        setUser((await response.json()) as AuthUser);
        await loadWorkspace();
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setAuthReady(true));
  }, [loadWorkspace]);

  async function startNewChat() {
    if (!user || loading) return;
    setActiveId(null);
    setRightView("chat");
    setMessages([]);
    setPendingImages([]);
    setError("");
  }

  function openChat(conversationId: string) {
    if (!user) return;
    void loadConversation(conversationId);
  }

  async function removeConversation(conversationId: string) {
    if (!user) return;
    const response = await apiFetch(`/api/conversations/${conversationId}`, { method: "DELETE" });
    if (!response.ok) {
      setError("Failed to delete conversation");
      return;
    }
    const remaining = await refreshConversations();
    if (activeId === conversationId) {
      if (remaining.length > 0) {
        await loadConversation(remaining[0].id);
      } else {
        setActiveId(null);
        setMessages([]);
      }
    }
  }

  async function addMemoryManually(event: FormEvent) {
    event.preventDefault();
    const content = memoryDraft.trim();
    if (!user || !content) return;
    const response = await apiFetch("/api/memories", {
      method: "POST",
      body: JSON.stringify({ content }),
    });
    if (!response.ok) {
      setError("Failed to add memory");
      return;
    }
    setMemoryDraft("");
    await refreshMemories();
  }

  async function removeMemory(memoryId: number) {
    if (!user) return;
    const response = await apiFetch(`/api/memories/${memoryId}`, { method: "DELETE" });
    if (!response.ok) {
      setError("Failed to delete memory");
      return;
    }
    await refreshMemories();
  }

  async function runLab(event: FormEvent) {
    event.preventDefault();
    const args = labArgs
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    if (args.length === 0 || labBusy || !user) return;
    setLabBusy(true);
    try {
      const response = await apiFetch("/api/tools/sage", {
        method: "POST",
        body: JSON.stringify({
          operation: labOp,
          arguments: args,
          split: labSplit.trim() ? Number.parseInt(labSplit, 10) : null,
        }),
      });
      const data = await response.json();
      const output = data.ok ? JSON.stringify(data.result) : (data.error ?? "failed");
      setLabResults((current) =>
        [{ operation: labOp, args: args.join(","), ok: Boolean(data.ok), output }, ...current].slice(0, 6),
      );
      if (data.ok) {
        await apiFetch("/api/notebook", {
          method: "POST",
          body: JSON.stringify({
            kind: "experiment",
            title: `${labOp}(${args.join(",")})`,
            content: output,
            payload: {
              operation: labOp,
              arguments: args,
              result: data.result,
              engine: data.engine,
            },
          }),
        });
        await refreshNotebook();
      }
    } catch {
      setLabResults((current) =>
        [{ operation: labOp, args: args.join(","), ok: false, output: "request failed" }, ...current].slice(0, 6),
      );
    } finally {
      setLabBusy(false);
    }
  }

  async function saveConjecture(event: FormEvent) {
    event.preventDefault();
    const text = conjectureDraft.trim();
    if (!user || !text) return;
    const response = await apiFetch("/api/notebook", {
      method: "POST",
      body: JSON.stringify({
        kind: "conjecture",
        title: text.slice(0, 80),
        content: text,
        payload: {},
      }),
    });
    if (!response.ok) {
      setError("Failed to save conjecture");
      return;
    }
    setConjectureDraft("");
    await refreshNotebook();
  }

  async function removeNotebookEntry(entryId: number) {
    if (!user) return;
    const response = await apiFetch(`/api/notebook/${entryId}`, { method: "DELETE" });
    if (!response.ok) {
      setError("Failed to delete notebook entry");
      return;
    }
    await refreshNotebook();
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const question = input.trim();
    const images = [...pendingImages];
    if ((!question && images.length === 0) || loading || !user) return;

    setMessages((current) => [
      ...current,
      { role: "user", content: question, images: images.length ? images : undefined },
    ]);
    setInput("");
    setPendingImages([]);
    setLoading(true);
    setLoadingStatus({ phase: "retrieving" });
    setError("");

    let assistantStarted = false;
    const ensureAssistant = () => {
      if (assistantStarted) return;
      assistantStarted = true;
      setMessages((current) => [...current, { role: "assistant", content: "" }]);
    };
    const patchAssistant = (updater: (content: string) => string) => {
      setMessages((current) => {
        const copy = [...current];
        for (let i = copy.length - 1; i >= 0; i -= 1) {
          if (copy[i].role === "assistant") {
            copy[i] = { ...copy[i], content: updater(copy[i].content) };
            return copy;
          }
        }
        return [...copy, { role: "assistant", content: updater("") }];
      });
    };

    try {
      const data = await streamChat(
        API_BASE,
        {
          message: question,
          images,
          conversation_id: activeId,
          answer_mode: answerMode,
          teach_depth: teachDepth,
        },
        {
          onStatus: setLoadingStatus,
          onDelta: (text) => {
            ensureAssistant();
            patchAssistant((content) => content + text);
          },
          onReset: () => {
            if (assistantStarted) patchAssistant(() => "");
          },
          onGate: (gate) => {
            if (typeof gate.answer === "string") {
              ensureAssistant();
              patchAssistant(() => gate.answer as string);
            }
          },
        },
      );
      setActiveId(data.conversation_id as string);
      if (assistantStarted) {
        patchAssistant(() => (data.answer as string) ?? "");
      } else {
        setMessages((current) => [
          ...current,
          { role: "assistant", content: data.answer as string },
        ]);
      }
      await refreshConversations();
      // Memories are extracted in the background; refresh shortly after.
      window.setTimeout(() => {
        void refreshMemories();
      }, 2500);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unknown error");
    } finally {
      setLoading(false);
      setLoadingStatus(null);
    }
  }

  const isEmptyChat = messages.length === 0;

  const composerSection = (
    <div className="composerWrap">
      {error && <p className="error">{error}</p>}
      <form className="composer" onSubmit={submit} ref={composerFormRef}>
        <ChatComposer
          disabled={loading || !user}
          images={pendingImages}
          onChange={setInput}
          onEnterSubmit={() => composerFormRef.current?.requestSubmit()}
          onImagesChange={setPendingImages}
          placeholder={placeholderFor(answerMode)}
          value={input}
        />
        <div className="composerFooter">
          <div className="composerFooterLeft">
            <ModeDropdown
              ariaLabel="Answer mode"
              disabled={loading}
              onChange={(value) => setAnswerMode(value as AnswerMode)}
              options={ANSWER_MODE_OPTIONS}
              value={answerMode}
            />
            {answerMode !== "research" && (
              <ModeDropdown
                ariaLabel="Answer depth"
                disabled={loading}
                onChange={(value) => setTeachDepth(value as TeachDepth)}
                options={TEACH_DEPTH_OPTIONS}
                value={teachDepth}
              />
            )}
          </div>
          <button
            disabled={loading || (!input.trim() && pendingImages.length === 0) || !user}
            type="submit"
          >
            Ask
          </button>
        </div>
      </form>
    </div>
  );

  async function signOut() {
    await apiFetch("/api/auth/logout", { method: "POST" });
    setUser(null);
    setConversations([]);
    setMessages([]);
    setMemories([]);
    setNotebook([]);
    setActiveId(null);
    setTools(null);
  }

  if (!authReady) {
    return (
      <main className="loginScreen">
        <p className="loginCopy">Loading…</p>
      </main>
    );
  }
  if (!user) {
    return (
      <GoogleLogin
        onSignedIn={async (next) => {
          setUser(next);
          setError("");
          await loadWorkspace();
        }}
      />
    );
  }

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="sidebarBrand">
          <strong>Proof Lab</strong>
          <span>Math proving workbench</span>
        </div>
        <nav className="sidebarTools" aria-label="Tools">
          <button
            className={`toolNavItem ${rightView === "chat" && !activeId ? "active" : ""}`}
            disabled={loading}
            onClick={startNewChat}
            type="button"
          >
            <span className="toolNavIcon">✎</span>
            New chat
          </button>
          <button
            className={`toolNavItem ${rightView === "lean" ? "active" : ""}`}
            onClick={() => {
              setRightView("lean");
              setError("");
            }}
            type="button"
          >
            <span className="toolNavIcon">λ</span>
            Lean workbench
          </button>
          <button
            className={`toolNavItem ${rightView === "auto-prove" ? "active" : ""}`}
            onClick={() => { setRightView("auto-prove"); setError(""); }}
            type="button"
          >
            <span className="toolNavIcon">∎</span>
            Auto Prove
          </button>
          <button
            className={`toolNavItem ${rightView === "notebook" ? "active" : ""}`}
            onClick={() => {
              setRightView("notebook");
              setError("");
            }}
            type="button"
          >
            <span className="toolNavIcon">∑</span>
            Notebook
          </button>
          <button
            className={`toolNavItem ${rightView === "memory" ? "active" : ""}`}
            onClick={() => {
              setRightView("memory");
              setError("");
            }}
            type="button"
          >
            <span className="toolNavIcon">◎</span>
            Memory
          </button>
        </nav>

        <section className="sidebarChats" aria-label="Recent chats">
          <div className="conversationList">
            {conversations.length === 0 && <p className="emptyHint">No saved chats yet</p>}
            {conversations.map((item) => (
              <div
                className={`conversationItem ${
                  rightView === "chat" && item.id === activeId ? "active" : ""
                }`}
                key={item.id}
              >
                <button
                  className="conversationMain"
                  onClick={() => openChat(item.id)}
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
        <div className="sidebarFooter accountFooter">
          {user.picture ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img alt="" className="accountAvatar" src={user.picture} />
          ) : (
            <span className="accountAvatarFallback">{(user.name || user.email || "?").slice(0, 1)}</span>
          )}
          <div className="accountMeta">
            <span className="accountName">{user.name || user.email || "Signed in"}</span>
            {user.email && user.name ? <span className="accountEmail">{user.email}</span> : null}
          </div>
          <button className="accountSignOut" onClick={() => void signOut()} type="button">
            Sign out
          </button>
        </div>
      </aside>

      <section className="chatPanel">
        {rightView === "lean" ? (
          <>
            {error && <p className="error leanError">{error}</p>}
            <LeanWorkbench
              apiBase={API_BASE}
              conversationId={activeId}
              leanAvailable={Boolean(tools?.lean.available)}
              modelConfigured={Boolean(tools?.openai.configured)}
              onAttachedToChat={async () => {
                if (activeId) {
                  await loadConversation(activeId);
                  setRightView("chat");
                }
              }}
              onError={setError}
            />
          </>
        ) : rightView === "auto-prove" ? (
          <>
            {error && <p className="error toolPanelError">{error}</p>}
            <AutoProve apiBase={API_BASE} modelConfigured={Boolean(tools?.openai.configured)} onError={setError} />
          </>
        ) : rightView === "notebook" ? (
          <>
            {error && <p className="error toolPanelError">{error}</p>}
            <NotebookPanel
              apiBase={API_BASE}
              conjectureDraft={conjectureDraft}
              entries={notebook}
              labArgs={labArgs}
              labBusy={labBusy}
              labOp={labOp}
              labResults={labResults}
              labSplit={labSplit}
              onConjectureDraftChange={setConjectureDraft}
              onDeleteEntry={removeNotebookEntry}
              onLabArgsChange={setLabArgs}
              onLabOpChange={setLabOp}
              onLabSplitChange={setLabSplit}
              onRunLab={runLab}
              onSaveConjecture={saveConjecture}
            />
          </>
        ) : rightView === "memory" ? (
          <>
            {error && <p className="error toolPanelError">{error}</p>}
            <MemoryPanel
              draft={memoryDraft}
              memories={memories}
              onAdd={addMemoryManually}
              onDelete={removeMemory}
              onDraftChange={setMemoryDraft}
            />
          </>
        ) : (
          <div className={`chatView ${isEmptyChat ? "chatViewEmpty" : ""}`}>
            {isEmptyChat ? (
              <div className="chatEmptyState">
                {switching ? (
                  <p className="thinking">Loading chat…</p>
                ) : (
                  <>
                    <h2 className="chatEmptyTitle">Where do we start ?</h2>
                    {loading && loadingStatus && <ThinkingStatus status={loadingStatus} />}
                    {composerSection}
                  </>
                )}
              </div>
            ) : (
              <>
                <div className="messages" aria-live="polite">
                  {switching ? (
                    <p className="thinking">Loading chat…</p>
                  ) : (
                    messages.map((message, index) => (
                      <article
                        className={`message ${message.role}`}
                        key={message.id ?? `${message.role}-${index}`}
                      >
                        <div className="avatar">{message.role === "assistant" ? "N" : "You"}</div>
                        <div className="bubble">
                          {message.role === "assistant" ? (
                            <MathMarkdown content={message.content} />
                          ) : (
                            <>
                              {message.images && message.images.length > 0 && (
                                <div className="messageImages">
                                  {message.images.map((src, imageIndex) => (
                                    // eslint-disable-next-line @next/next/no-img-element
                                    <img
                                      alt={`Uploaded ${imageIndex + 1}`}
                                      key={`${message.id ?? index}-${imageIndex}`}
                                      src={src}
                                    />
                                  ))}
                                </div>
                              )}
                              {message.content ? <p>{message.content}</p> : null}
                            </>
                          )}
                        </div>
                      </article>
                    ))
                  )}
                  {loading && loadingStatus && <ThinkingStatus status={loadingStatus} />}
                </div>
                {composerSection}
              </>
            )}
          </div>
        )}
      </section>
    </main>
  );
}
