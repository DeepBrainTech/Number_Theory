"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import ChatComposer from "./components/ChatComposer";
import { type PendingDocument } from "./components/ChatComposer";
import GoogleLogin from "./components/GoogleLogin";
import ThinkingStatus, { LoadingStatus, streamChat } from "./components/ThinkingStatus";
import LeanWorkbench, { type LeanRun } from "./components/LeanWorkbench";
import AutoProve, { type SavedRun } from "./components/AutoProve";
import ModeDropdown, { ANSWER_MODE_OPTIONS, TEACH_DEPTH_OPTIONS } from "./components/ModeDropdown";
import MathMarkdown from "./components/MathMarkdown";
import MemoryPanel from "./components/MemoryPanel";
import NotebookPanel from "./components/NotebookPanel";
import { API_BASE, apiFetch, type AuthUser } from "./lib/api";
import {
  loadGuestWorkspace,
  newGuestId,
  saveGuestWorkspace,
  type GuestConversation,
  type GuestMemory,
  type GuestMessage,
  type GuestNotebookEntry,
} from "./lib/guestStore";

type Message = GuestMessage & { id?: number };

type Conversation = Omit<GuestConversation, "messages">;

type Memory = GuestMemory;

type ToolStatus = {
  deepseek: { configured: boolean; model: string };
  openai_vision: { configured: boolean; model: string };
  sage: { available: boolean; engine?: string };
  lean: { available: boolean; engine?: string };
};

type LabResult = {
  operation: string;
  args: string;
  ok: boolean;
  output: string;
};

type NotebookEntry = GuestNotebookEntry;

type TeachDepth = "hint" | "socratic" | "full";

type ImagePreview = { alt: string; src: string };

type AnswerMode = "auto" | "general" | "teach" | "solve" | "research";
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

function autoProveTitle(problem: string): string {
  const text = problem.replace(/\s+/g, " ").trim();
  return text.length > 44 ? `${text.slice(0, 44)}…` : text || "Untitled proof";
}

function placeholderFor(mode: AnswerMode): string {
  switch (mode) {
    case "solve":
      return "Ask a problem to solve…";
    case "teach":
      return "Ask something you'd like to understand…";
    case "general":
      return "Ask a question…";
    case "research":
      return "Ask about the literature or open questions…";
    default:
      return "Ask anything…";
  }
}

export default function Home() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [guestMode, setGuestMode] = useState(false);
  const [guestStorageReady, setGuestStorageReady] = useState(false);
  const [tools, setTools] = useState<ToolStatus | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [input, setInput] = useState("");
  const [pendingImages, setPendingImages] = useState<string[]>([]);
  const [imagePreview, setImagePreview] = useState<ImagePreview | null>(null);
  const [pendingDocuments, setPendingDocuments] = useState<PendingDocument[]>([]);
  const [rightView, setRightView] = useState<RightView>("chat");
  const [leanExpanded, setLeanExpanded] = useState(false);
  const [leanRuns, setLeanRuns] = useState<LeanRun[]>([]);
  const [selectedLeanRunId, setSelectedLeanRunId] = useState<number | null>(null);
  const [autoProveExpanded, setAutoProveExpanded] = useState(false);
  const [autoProveRuns, setAutoProveRuns] = useState<SavedRun[]>([]);
  const [selectedAutoProveRunId, setSelectedAutoProveRunId] = useState<string | null>(null);
  const [autoProveRevision, setAutoProveRevision] = useState(0);
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
  const activeRequestRef = useRef<AbortController | null>(null);
  const messagesRef = useRef<HTMLDivElement>(null);

  const loadGuestWorkspaceIntoState = useCallback(() => {
    const workspace = loadGuestWorkspace();
    setConversations(workspace.conversations.map(({ messages: _messages, ...conversation }) => conversation));
    setMemories(workspace.memories);
    setNotebook(workspace.notebook);
    setActiveId(workspace.conversations[0]?.id ?? null);
    setMessages(workspace.conversations[0]?.messages ?? []);
    setGuestStorageReady(true);
  }, []);

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
    const [toolsResponse] = await Promise.all([
      apiFetch("/api/tools/status"),
      refreshConversations(),
      refreshMemories(),
      refreshNotebook(),
    ]);
    if (!toolsResponse.ok) throw new Error("Failed to load system status");
    setTools(await toolsResponse.json());
    setActiveId(null);
    setMessages([]);
    setRightView("chat");
  }, [refreshConversations, refreshMemories, refreshNotebook]);

  const refreshAutoProveRuns = useCallback(async () => {
    if (!user) {
      setAutoProveRuns([]);
      return;
    }
    const response = await apiFetch("/api/auto-prove/runs");
    if (response.ok) setAutoProveRuns(await response.json() as SavedRun[]);
  }, [user]);

  useEffect(() => {
    void refreshAutoProveRuns();
  }, [refreshAutoProveRuns]);

  const deleteAutoProveRun = useCallback(async (run: SavedRun) => {
    if (run.status === "running") {
      setError("Cancel the running Auto Prove job before deleting it.");
      return;
    }
    if (!window.confirm("Delete this Auto Prove run and all of its saved proof files? This cannot be undone.")) {
      return;
    }
    const response = await apiFetch(`/api/auto-prove/runs/${run.run_id}`, { method: "DELETE" });
    if (!response.ok) {
      const detail = await response.json().catch(() => null) as { detail?: string } | null;
      setError(detail?.detail || "Could not delete the Auto Prove run.");
      return;
    }
    setAutoProveRuns((runs) => runs.filter((item) => item.run_id !== run.run_id));
    if (selectedAutoProveRunId === run.run_id) {
      setSelectedAutoProveRunId(null);
      setAutoProveRevision((value) => value + 1);
    }
  }, [selectedAutoProveRunId]);

  useEffect(() => {
    apiFetch("/api/auth/me")
      .then(async (response) => {
        if (!response.ok) {
          setUser(null);
          loadGuestWorkspaceIntoState();
          const toolsResponse = await apiFetch("/api/tools/status");
          if (toolsResponse.ok) setTools(await toolsResponse.json());
          return;
        }
        setUser((await response.json()) as AuthUser);
        await loadWorkspace();
      })
      .catch((reason: Error) => setError(reason.message))
      .finally(() => setAuthReady(true));
  }, [loadGuestWorkspaceIntoState, loadWorkspace]);

  useEffect(() => {
    if (!guestMode || user || !guestStorageReady) return;
    const existing = loadGuestWorkspace();
    saveGuestWorkspace({
      conversations: conversations.map((conversation) => ({
        ...conversation,
        messages: conversation.id === activeId
          ? messages
          : existing.conversations.find((item) => item.id === conversation.id)?.messages ?? [],
      })),
      memories,
      notebook,
    });
  }, [activeId, conversations, guestMode, guestStorageReady, memories, messages, notebook, user]);

  async function startNewChat() {
    if (loading) return;
    setActiveId(null);
    setRightView("chat");
    setMessages([]);
    setPendingImages([]);
    setError("");
  }

  function openChat(conversationId: string) {
    if (!user) {
      const conversation = loadGuestWorkspace().conversations.find((item) => item.id === conversationId);
      if (!conversation) return;
      setActiveId(conversation.id);
      setMessages(conversation.messages);
      setRightView("chat");
      return;
    }
    void loadConversation(conversationId);
  }

  async function removeConversation(conversationId: string) {
    if (!user) {
      const workspace = loadGuestWorkspace();
      const remaining = workspace.conversations.filter((item) => item.id !== conversationId);
      saveGuestWorkspace({ ...workspace, conversations: remaining });
      setConversations(remaining.map(({ messages: _messages, ...conversation }) => conversation));
      if (activeId === conversationId) {
        setActiveId(remaining[0]?.id ?? null);
        setMessages(remaining[0]?.messages ?? []);
      }
      return;
    }
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
    if (!content) return;
    if (!user) {
      const now = new Date().toISOString();
      setMemories((current) => [{ id: Date.now(), content, created_at: now, updated_at: now }, ...current]);
      setMemoryDraft("");
      return;
    }
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
    if (!user) {
      setMemories((current) => current.filter((item) => item.id !== memoryId));
      return;
    }
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
    if (args.length === 0 || labBusy) return;
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
      if (data.ok && !user) {
        const now = new Date().toISOString();
        setNotebook((current) => [{
          id: Date.now(), kind: "experiment", title: `${labOp}(${args.join(",")})`, content: output,
          payload: { operation: labOp, arguments: args, result: data.result, engine: data.engine }, created_at: now,
        }, ...current]);
      } else if (data.ok) {
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
    if (!text) return;
    if (!user) {
      const now = new Date().toISOString();
      setNotebook((current) => [{ id: Date.now(), kind: "conjecture", title: text.slice(0, 80), content: text, payload: {}, created_at: now }, ...current]);
      setConjectureDraft("");
      return;
    }
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
    if (!user) {
      setNotebook((current) => current.filter((item) => item.id !== entryId));
      return;
    }
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
    const documents = [...pendingDocuments];
    if ((!question && images.length === 0 && documents.length === 0) || loading) return;

    let extractedDocuments: { name: string; content: string }[];
    try {
      extractedDocuments = await Promise.all(documents.map(async ({ file }) => {
        const form = new FormData();
        form.append("file", file);
        const response = await apiFetch("/api/chat/attachments/extract", { method: "POST", body: form });
        if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? `Could not read ${file.name}`);
        return response.json() as Promise<{ name: string; content: string }>;
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not read the attachment");
      return;
    }

    let guestConversationId = activeId;
    if (!user && !guestConversationId) {
      const now = new Date().toISOString();
      guestConversationId = newGuestId();
      setActiveId(guestConversationId);
      setConversations((current) => [{ id: guestConversationId!, title: question.slice(0, 80) || "Image chat", created_at: now, updated_at: now }, ...current]);
    }

    setMessages((current) => [
      ...current,
      { role: "user", content: [question, ...extractedDocuments.map((document) => `[Attached: ${document.name}]`)].filter(Boolean).join("\n"), images: images.length ? images : undefined },
    ]);
    window.requestAnimationFrame(() => {
      const userMessages = messagesRef.current?.querySelectorAll<HTMLElement>(".message.user");
      const latestUserMessage = userMessages?.[userMessages.length - 1];
      latestUserMessage?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
    setInput("");
    setPendingImages([]);
    setPendingDocuments([]);
    setLoading(true);
    setLoadingStatus({ phase: "retrieving" });
    setError("");
    const abortController = new AbortController();
    activeRequestRef.current = abortController;

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
          documents: extractedDocuments,
          conversation_id: activeId,
          answer_mode: answerMode,
          teach_depth: teachDepth,
          ...(user ? {} : { history: messages, memories: memories.map((memory) => memory.content) }),
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
        user ? "/api/chat/stream" : "/api/chat/guest/stream",
        { signal: abortController.signal },
      );
      if (abortController.signal.aborted) return;
      if (user) setActiveId(data.conversation_id as string);
      if (assistantStarted) {
        patchAssistant(() => (data.answer as string) ?? "");
      } else {
        setMessages((current) => [
          ...current,
          { role: "assistant", content: data.answer as string },
        ]);
      }
      if (user) {
        await refreshConversations();
        window.setTimeout(() => { void refreshMemories(); }, 2500);
      } else if (guestConversationId) {
        const now = new Date().toISOString();
        setConversations((current) => current.map((item) => item.id === guestConversationId ? { ...item, updated_at: now } : item));
      }
    } catch (reason) {
      if (abortController.signal.aborted) return;
      setError(reason instanceof Error ? reason.message : "Unknown error");
    } finally {
      if (activeRequestRef.current === abortController) {
        activeRequestRef.current = null;
        setLoading(false);
        setLoadingStatus(null);
      }
    }
  }

  function stopGeneration() {
    const activeRequest = activeRequestRef.current;
    if (!activeRequest) return;
    activeRequest.abort();
    activeRequestRef.current = null;
    setLoading(false);
    setLoadingStatus(null);
  }

  const isEmptyChat = messages.length === 0;

  const composerSection = (
    <div className="composerWrap">
      {error && <p className="error">{error}</p>}
      <form className="composer" onSubmit={submit} ref={composerFormRef}>
        <ChatComposer
          disabled={loading}
          images={pendingImages}
          documents={pendingDocuments}
          onChange={setInput}
          onEnterSubmit={() => composerFormRef.current?.requestSubmit()}
          onImagesChange={setPendingImages}
          onDocumentsChange={setPendingDocuments}
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
            {(answerMode === "teach" || answerMode === "solve") && (
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
            disabled={!loading && (!input.trim() && pendingImages.length === 0 && pendingDocuments.length === 0)}
            onClick={loading ? stopGeneration : undefined}
            type={loading ? "button" : "submit"}
          >
            {loading ? "Stop" : "Send"}
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
    setGuestMode(true);
    loadGuestWorkspaceIntoState();
  }

  if (!authReady) {
    return (
      <main className="loginScreen">
        <p className="loginCopy">Loading…</p>
      </main>
    );
  }
  if (!user && !guestMode) {
    return (
      <GoogleLogin
        onSignedIn={async (next) => {
          setUser(next);
          setGuestMode(false);
          setError("");
          await loadWorkspace();
        }}
        onClose={() => setGuestMode(true)}
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
              setLeanExpanded((value) => !value);
              setRightView("lean");
              setError("");
            }}
            type="button"
          >
            <span className="toolNavIcon">λ</span>
            Lean workbench
            <span className="autoProveChevron" aria-hidden="true">{leanExpanded ? "⌄" : "›"}</span>
          </button>
          {leanExpanded && (
            <div className="autoProveNavRuns" aria-label="Saved Lean workbench runs">
              {!user && <p className="emptyHint">Sign in to view saved runs</p>}
              {user && leanRuns.length === 0 && <p className="emptyHint">No Lean runs yet</p>}
              {leanRuns.map((run) => (
                <div
                  className={`conversationItem ${
                    rightView === "lean" && selectedLeanRunId === run.id ? "active" : ""
                  }`}
                  key={run.id}
                >
                  <button
                    className="conversationMain"
                    onClick={() => {
                      setSelectedLeanRunId(run.id);
                      setRightView("lean");
                      setError("");
                    }}
                    title={`Lean verification: ${run.result?.level ?? "V0"}`}
                    type="button"
                  >
                    <span className="conversationTitle">{autoProveTitle(run.question)}</span>
                  </button>
                </div>
              ))}
            </div>
          )}
          <button
            className={`toolNavItem ${rightView === "auto-prove" ? "active" : ""}`}
            onClick={() => {
              setAutoProveExpanded((value) => !value);
              setSelectedAutoProveRunId(null);
              setAutoProveRevision((value) => value + 1);
              setRightView("auto-prove");
              setError("");
            }}
            type="button"
          >
            <span className="toolNavIcon">∎</span>
            Auto Prove
            <span className="autoProveChevron" aria-hidden="true">{autoProveExpanded ? "⌄" : "›"}</span>
          </button>
          {autoProveExpanded && (
            <div className="autoProveNavRuns" aria-label="Saved Auto Prove runs">
              {!user && <p className="emptyHint">Sign in to view saved runs</p>}
              {user && autoProveRuns.length === 0 && <p className="emptyHint">No proof runs yet</p>}
              {autoProveRuns.map((run) => (
                <div
                  className={`conversationItem ${
                    rightView === "auto-prove" && selectedAutoProveRunId === run.run_id ? "active" : ""
                  }`}
                  key={run.run_id}
                >
                  <button
                    onClick={() => {
                      setSelectedAutoProveRunId(run.run_id);
                      setRightView("auto-prove");
                      setError("");
                    }}
                    className="conversationMain"
                    title={`Auto Prove run: ${run.status}`}
                    type="button"
                  >
                    <span className="conversationTitle">{autoProveTitle(run.problem)}</span>
                  </button>
                  <button
                    aria-label="Delete Auto Prove run"
                    className="iconBtn autoProveNavDelete"
                    disabled={run.status === "running"}
                    onClick={() => void deleteAutoProveRun(run)}
                    title={run.status === "running" ? "Cancel the run before deleting it" : "Delete run and saved files"}
                    type="button"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          )}
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
          {user?.picture ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img alt="" className="accountAvatar" src={user.picture} />
          ) : (
            <span className="accountAvatarFallback">{(user?.name || user?.email || "G").slice(0, 1)}</span>
          )}
          <div className="accountMeta">
            <span className="accountName">{user ? user.name || user.email || "Signed in" : "Guest mode"}</span>
            {user?.email && user.name ? <span className="accountEmail">{user.email}</span> : <span className="accountEmail">Saved in this browser</span>}
          </div>
          <button className="accountSignOut" onClick={() => user ? void signOut() : setGuestMode(false)} type="button">
            {user ? "Sign out" : "Sign in"}
          </button>
        </div>
      </aside>

      <section className={`chatPanel ${rightView === "auto-prove" ? "pageScrollPanel" : ""} ${rightView === "chat" && !isEmptyChat ? "chatPageScroll" : ""}`}>
        {rightView === "lean" ? (
          <>
            {error && <p className="error leanError">{error}</p>}
            <LeanWorkbench
              key={user?.id ?? "guest"}
              apiBase={API_BASE}
              conversationId={activeId}
              authenticated={Boolean(user)}
              leanAvailable={Boolean(tools?.lean.available)}
              modelConfigured={Boolean(tools?.deepseek?.configured)}
              onRunsChange={setLeanRuns}
              selectedRunId={selectedLeanRunId}
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
            <AutoProve
              key={autoProveRevision}
              apiBase={API_BASE}
              authenticated={Boolean(user)}
              modelConfigured={Boolean(tools?.deepseek?.configured)}
              onRunsChange={setAutoProveRuns}
              selectedRunId={selectedAutoProveRunId}
              onError={setError}
            />
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
                <div className="messages" aria-live="polite" ref={messagesRef}>
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
                                    <button
                                      aria-label={`View uploaded image ${imageIndex + 1}`}
                                      className="messageImageButton"
                                      key={`${message.id ?? index}-${imageIndex}`}
                                      onClick={() => setImagePreview({ alt: `Uploaded ${imageIndex + 1}`, src })}
                                      type="button"
                                    >
                                      {/* eslint-disable-next-line @next/next/no-img-element */}
                                      <img alt={`Uploaded ${imageIndex + 1}`} src={src} />
                                    </button>
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
      {imagePreview && (
        <div
          aria-label="Image preview"
          className="imageLightbox"
          onClick={() => setImagePreview(null)}
          role="dialog"
        >
          <button
            aria-label="Close image preview"
            className="imageLightboxClose"
            onClick={() => setImagePreview(null)}
            type="button"
          >
            ×
          </button>
          <img
            alt={imagePreview.alt}
            className="imageLightboxImage"
            onClick={(event) => event.stopPropagation()}
            src={imagePreview.src}
          />
        </div>
      )}
    </main>
  );
}
