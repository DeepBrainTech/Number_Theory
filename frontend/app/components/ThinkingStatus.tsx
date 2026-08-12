"use client";

import { apiUrl } from "../lib/api";

const TOOL_LABELS: Record<string, string> = {
  web_search: "Searching the web",
  sage_calculate: "Computing with SageMath",
  arxiv_search: "Searching arXiv",
  semantic_scholar_search: "Searching Semantic Scholar",
  crossref_search: "Searching Crossref",
  literature_search: "Searching literature",
  oeis_search: "Searching OEIS",
};

export type LoadingStatus = {
  phase: string;
  detail?: string | null;
};

export type StreamHandlers = {
  onStatus?: (status: LoadingStatus) => void;
  onDelta?: (text: string) => void;
  onReset?: () => void;
  onGate?: (gate: Record<string, unknown>) => void;
};

export function statusLabel(phase: string, detail?: string | null): string {
  switch (phase) {
    case "retrieving":
      return "Starting";
    case "thinking":
      return "Thinking";
    case "gating":
      return "Checking correctness";
    case "structuring":
      return "Structuring research outline";
    case "tool":
      if (detail && TOOL_LABELS[detail]) return TOOL_LABELS[detail];
      if (detail) return `Running ${detail.replaceAll("_", " ")}`;
      return "Running tool";
    default:
      return "Thinking";
  }
}

type Props = {
  status: LoadingStatus;
};

export default function ThinkingStatus({ status }: Props) {
  return (
    <p className="thinkingStatus" aria-live="polite">
      <span className="thinkingPulse" />
      <span>{statusLabel(status.phase, status.detail)}</span>
    </p>
  );
}

export async function streamChat(
  apiBase: string,
  body: Record<string, unknown>,
  handlers: StreamHandlers | ((status: LoadingStatus) => void) = {},
): Promise<Record<string, unknown>> {
  const resolved: StreamHandlers =
    typeof handlers === "function" ? { onStatus: handlers } : handlers;

  const response = await fetch(apiUrl("/api/chat/stream"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    credentials: "include",
  });
  if (!response.ok) throw new Error("Failed to get a reply");

  const reader = response.body?.getReader();
  if (!reader) throw new Error("No response stream");

  const decoder = new TextDecoder();
  let buffer = "";
  let payload: Record<string, unknown> | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() ?? "";
    for (const chunk of chunks) {
      const line = chunk.trim();
      if (!line.startsWith("data: ")) continue;
      const data = JSON.parse(line.slice(6)) as {
        type: string;
        phase?: string;
        detail?: string | null;
        text?: string;
        message?: string;
        answer?: string;
      };
      if (data.type === "status" && data.phase) {
        resolved.onStatus?.({ phase: data.phase, detail: data.detail });
      }
      if (data.type === "delta" && typeof data.text === "string") {
        resolved.onDelta?.(data.text);
      }
      if (data.type === "reset") {
        resolved.onReset?.();
      }
      if (data.type === "gate") {
        resolved.onGate?.(data as Record<string, unknown>);
        if (payload) {
          payload = Object.assign({}, payload, data, { type: "done" });
        }
      }
      if (data.type === "error") throw new Error(data.message ?? "Stream failed");
      if (data.type === "done") payload = data as Record<string, unknown>;
    }
  }

  if (!payload) throw new Error("No response");
  return payload;
}
