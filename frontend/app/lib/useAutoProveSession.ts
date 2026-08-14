"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiFetch } from "./api";

export type ProveResult = {
  ok: boolean;
  proof?: string;
  plan?: string;
  review?: string[];
  revisions?: number;
  proof_attempts?: number;
  decompositions?: number;
  difficulty?: string;
  related_work?: string;
  passed?: boolean;
  run_id?: string;
  formalization?: { verified?: boolean; aligned?: boolean | null; level?: string; notes?: string[]; error?: string };
  error?: string;
};

export type SavedRun = {
  run_id: string;
  problem: string;
  guidance: string;
  depth: string;
  formalize: boolean;
  status: string;
  phase: string;
  current_tool?: string;
  difficulty?: string | null;
  passed?: boolean | null;
  proof_attempts: number;
  revisions: number;
  decompositions: number;
  error?: string | null;
  created_at: string;
  updated_at: string;
};

export type RunArtifacts = { files: string[]; checkpoint?: string; status?: string; meta?: SavedRun };

export type LiveRun = {
  runId: string;
  status: string;
  phase: string;
  tool: string;
  createdAt: string;
};

export type ProveStartBody = {
  problem: string;
  guidance: string;
  references: { name: string; content: string }[];
  depth: "quick" | "deep";
  formalize: boolean;
  run_id?: string | null;
  resume?: boolean;
};

type StreamEvent = ProveResult & {
  type: string;
  phase?: string;
  label?: string;
  tool?: string;
  run_id?: string;
  status?: string;
  current_tool?: string;
  created_at?: string;
};

function applySnapshot(event: StreamEvent): LiveRun | null {
  const runId = event.run_id;
  if (!runId) return null;
  return {
    runId,
    status: event.status || "running",
    phase: event.phase || event.label || "",
    tool: event.current_tool || (event.phase === "tool" ? (event.tool || event.label || "") : ""),
    createdAt: event.created_at || "",
  };
}

async function readEventStream(
  response: Response,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  if (!response.body) throw new Error("Auto Prove request failed");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const chunk = await reader.read();
    if (chunk.done) break;
    buffer += decoder.decode(chunk.value, { stream: true });
    const events = buffer.split("\n\n");
    buffer = events.pop() ?? "";
    for (const eventText of events) {
      const line = eventText.split("\n").find((item) => item.startsWith("data: "));
      if (!line) continue;
      onEvent(JSON.parse(line.slice(6)) as StreamEvent);
    }
  }
}

export function useAutoProveSession(options: {
  authenticated: boolean;
  onError?: (message: string) => void;
}) {
  const { authenticated, onError } = options;
  const [runs, setRuns] = useState<SavedRun[]>([]);
  const [liveById, setLiveById] = useState<Record<string, LiveRun>>({});
  const [resultsById, setResultsById] = useState<Record<string, ProveResult>>({});
  const [artifactsById, setArtifactsById] = useState<Record<string, RunArtifacts>>({});
  const [starting, setStarting] = useState(false);
  const [startingRunId, setStartingRunId] = useState<string | null>(null);
  const attached = useRef<Map<string, AbortController>>(new Map());
  const pendingStart = useRef<AbortController | null>(null);

  const refreshRuns = useCallback(async () => {
    if (!authenticated) {
      setRuns([]);
      return [];
    }
    const response = await apiFetch("/api/auto-prove/runs");
    if (!response.ok) return [];
    const next = await response.json() as SavedRun[];
    setRuns(next);
    setLiveById((current) => {
      const updated = { ...current };
      for (const run of next) {
        if (run.status !== "running") {
          delete updated[run.run_id];
          continue;
        }
        updated[run.run_id] = {
          runId: run.run_id,
          status: run.status,
          phase: run.phase || updated[run.run_id]?.phase || "",
          tool: run.current_tool || updated[run.run_id]?.tool || "",
          createdAt: run.created_at,
        };
      }
      return updated;
    });
    return next;
  }, [authenticated]);

  const loadFinished = useCallback(async (runId: string) => {
    const response = await apiFetch(`/api/auto-prove/runs/${runId}`);
    if (!response.ok) return;
    const payload = await response.json() as RunArtifacts & { result?: ProveResult | null; meta?: SavedRun };
    setArtifactsById((current) => ({ ...current, [runId]: payload }));
    if (payload.meta?.status === "running") return;
    if (payload.result && typeof payload.result === "object") {
      setResultsById((current) => ({ ...current, [runId]: { ...payload.result!, run_id: runId, ok: payload.result?.ok ?? true } }));
    }
  }, []);

  const handleEvent = useCallback((event: StreamEvent) => {
    const runId = event.run_id;
    if (event.type === "snapshot") {
      const live = applySnapshot(event);
      if (!live) return;
      setLiveById((current) => ({ ...current, [live.runId]: { ...current[live.runId], ...live } }));
      return;
    }
    if (event.type === "status" && runId) {
      setLiveById((current) => {
        const previous = current[runId];
        const tool = event.phase === "tool"
          ? (event.tool || event.label || "")
          : event.phase === "tool_complete"
            ? ""
            : (previous?.tool || "");
        const phase = event.phase === "tool" || event.phase === "tool_complete"
          ? (event.phase === "tool" ? (event.label || previous?.phase || "") : (previous?.phase || ""))
          : (event.label || event.phase || previous?.phase || "");
        return {
          ...current,
          [runId]: {
            runId,
            status: "running",
            phase,
            tool,
            createdAt: previous?.createdAt || "",
          },
        };
      });
      return;
    }
    if (event.type === "result" && runId) {
      const cancelled = Boolean(event.error?.toLowerCase().includes("cancelled"));
      setLiveById((current) => {
        const next = { ...current };
        delete next[runId];
        return next;
      });
      if (event.ok || event.proof || event.error) {
        setResultsById((current) => ({ ...current, [runId]: { ...event, run_id: runId } }));
      }
      void loadFinished(runId);
      void refreshRuns();
      if (cancelled) return;
    }
  }, [loadFinished, refreshRuns]);

  const watchRun = useCallback(async (runId: string) => {
    if (!runId || attached.current.has(runId)) return;
    const controller = new AbortController();
    attached.current.set(runId, controller);
    let reconnect = true;
    try {
      const response = await apiFetch(`/api/auto-prove/runs/${runId}/events`, { signal: controller.signal });
      if (!response.ok || !response.body) {
        reconnect = false;
        throw new Error("Could not subscribe to Auto Prove run");
      }
      await readEventStream(response, handleEvent);
    } catch (reason) {
      if ((reason as Error).name === "AbortError") {
        reconnect = false;
        return;
      }
      onError?.(reason instanceof Error ? reason.message : "Auto Prove failed");
    } finally {
      attached.current.delete(runId);
      if (!reconnect || controller.signal.aborted) return;
      const latest = await refreshRuns();
      const meta = latest.find((run) => run.run_id === runId);
      if (meta?.status === "running" && !attached.current.has(runId)) {
        void watchRun(runId);
      } else if (meta && meta.status !== "running") {
        void loadFinished(runId);
      }
    }
  }, [handleEvent, loadFinished, onError, refreshRuns]);

  const startProve = useCallback(async (body: ProveStartBody) => {
    pendingStart.current?.abort();
    const controller = new AbortController();
    pendingStart.current = controller;
    setStarting(true);
    let runId = body.run_id || "";
    try {
      const response = await apiFetch("/api/auto-prove/stream", {
        method: "POST",
        body: JSON.stringify({
          problem: body.problem,
          guidance: body.guidance,
          references: body.references,
          depth: body.depth,
          formalize: body.formalize,
          run_id: body.run_id,
          resume: Boolean(body.resume),
        }),
        signal: controller.signal,
      });
      if (!response.ok || !response.body) throw new Error("Auto Prove request failed");
      await readEventStream(response, (event) => {
        if (event.run_id) {
          if (event.run_id !== runId) {
            runId = event.run_id;
            void refreshRuns();
          }
          if (!attached.current.has(runId)) attached.current.set(runId, controller);
          setStartingRunId(runId);
        }
        handleEvent(event);
      });
    } catch (reason) {
      if ((reason as Error).name === "AbortError") return runId;
      onError?.(reason instanceof Error ? reason.message : "Auto Prove failed");
    } finally {
      if (pendingStart.current === controller) pendingStart.current = null;
      if (runId) attached.current.delete(runId);
      setStarting(false);
      if (!controller.signal.aborted) {
        const latest = await refreshRuns();
        const meta = latest.find((run) => run.run_id === runId);
        if (meta?.status === "running") void watchRun(runId);
        else if (runId) void loadFinished(runId);
      }
    }
    return runId;
  }, [handleEvent, loadFinished, onError, refreshRuns, watchRun]);

  const cancelProve = useCallback(async (runId?: string | null) => {
    const id = runId || "";
    pendingStart.current?.abort();
    if (id) attached.current.get(id)?.abort();
    if (!id) {
      setStarting(false);
      return;
    }
    const response = await apiFetch(`/api/auto-prove/runs/${id}/cancel`, { method: "POST" });
    if (!response.ok) {
      onError?.("Could not cancel Auto Prove run");
      return;
    }
    setLiveById((current) => {
      const next = { ...current };
      delete next[id];
      return next;
    });
    setStarting(false);
    void refreshRuns();
  }, [onError, refreshRuns]);

  const openRun = useCallback(async (run: SavedRun) => {
    if (run.status === "running") {
      setResultsById((current) => {
        const next = { ...current };
        delete next[run.run_id];
        return next;
      });
      setLiveById((current) => ({
        ...current,
        [run.run_id]: {
          runId: run.run_id,
          status: "running",
          phase: run.phase || current[run.run_id]?.phase || "",
          tool: run.current_tool || current[run.run_id]?.tool || "",
          createdAt: run.created_at,
        },
      }));
      void watchRun(run.run_id);
      return;
    }
    await loadFinished(run.run_id);
  }, [loadFinished, watchRun]);

  useEffect(() => {
    void refreshRuns();
  }, [refreshRuns]);

  useEffect(() => {
    if (!authenticated) return;
    for (const run of runs) {
      if (run.status === "running") void watchRun(run.run_id);
    }
  }, [authenticated, runs, watchRun]);

  useEffect(() => () => {
    pendingStart.current?.abort();
    for (const controller of attached.current.values()) controller.abort();
    attached.current.clear();
  }, []);

  return {
    runs,
    liveById,
    resultsById,
    artifactsById,
    starting,
    startingRunId,
    refreshRuns,
    startProve,
    cancelProve,
    openRun,
    watchRun,
  };
}
