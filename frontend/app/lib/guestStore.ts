export type GuestMessage = {
  role: "user" | "assistant";
  content: string;
  images?: string[];
};

export type GuestConversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  messages: GuestMessage[];
};

export type GuestMemory = {
  id: number;
  content: string;
  source_conversation_id?: string | null;
  created_at: string;
  updated_at: string;
};

export type GuestNotebookEntry = {
  id: number;
  kind: "experiment" | "conjecture" | "counterexample";
  title: string;
  content: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type GuestWorkspace = {
  conversations: GuestConversation[];
  memories: GuestMemory[];
  notebook: GuestNotebookEntry[];
};

const STORAGE_KEY = "proof_lab_guest_workspace_v1";

export function loadGuestWorkspace(): GuestWorkspace {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}") as Partial<GuestWorkspace>;
    return {
      conversations: Array.isArray(parsed.conversations) ? parsed.conversations : [],
      memories: Array.isArray(parsed.memories) ? parsed.memories : [],
      notebook: Array.isArray(parsed.notebook) ? parsed.notebook : [],
    };
  } catch {
    return { conversations: [], memories: [], notebook: [] };
  }
}

export function saveGuestWorkspace(workspace: GuestWorkspace): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(workspace));
  } catch {
    // Private browsing or a full quota should not block the guest workspace.
  }
}

export function newGuestId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `guest-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}
