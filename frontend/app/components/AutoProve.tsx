"use client";

import { ChangeEvent, FormEvent, useCallback, useEffect, useRef, useState } from "react";
import LatexField from "./LatexField";
import MathMarkdown from "./MathMarkdown";
import { apiFetch } from "../lib/api";

type Result = {
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
  difficulty?: string | null;
  passed?: boolean | null;
  proof_attempts: number;
  revisions: number;
  decompositions: number;
  error?: string | null;
  created_at: string;
  updated_at: string;
};

type Props = {
  apiBase: string;
  modelConfigured: boolean;
  authenticated: boolean;
  onRunsChange: (runs: SavedRun[]) => void;
  selectedRunId?: string | null;
  onError?: (message: string) => void;
};

type RunArtifacts = { files: string[]; checkpoint?: string; status?: string; meta?: SavedRun };
type ReferenceMaterial = { name: string; content: string };

function formatElapsed(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return minutes ? `${minutes}m${remainder}s` : `${remainder}s`;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export default function AutoProve({
  apiBase,
  modelConfigured,
  authenticated,
  onRunsChange,
  selectedRunId,
  onError,
}: Props) {
  const [problem, setProblem] = useState("");
  const [guidance, setGuidance] = useState("");
  const [depth, setDepth] = useState<"quick" | "deep">("quick");
  const [formalize, setFormalize] = useState(false);
  const [status, setStatus] = useState("");
  const [toolStatus, setToolStatus] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [runArtifacts, setRunArtifacts] = useState<RunArtifacts | null>(null);
  const [researchNote, setResearchNote] = useState("");
  const [references, setReferences] = useState<ReferenceMaterial[]>([]);
  const [uploadingReferences, setUploadingReferences] = useState(false);
  const [savedRuns, setSavedRuns] = useState<SavedRun[]>([]);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const controller = useRef<AbortController | null>(null);
  const referenceInput = useRef<HTMLInputElement | null>(null);
  const runStartedAt = useRef<number | null>(null);
  const proofExportContent = useRef<HTMLDivElement | null>(null);
  const problemExportContent = useRef<HTMLDivElement | null>(null);

  function downloadProofHtml() {
    if (!result?.proof || !proofExportContent.current || !problemExportContent.current) return;

    const title = "Proof Lab — Auto Prove result";
    const exportedAt = new Date().toLocaleString();
    const documentHtml = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>${title}</title>
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.18.1/dist/katex.min.css">
  <style>
    body { background: #f5f2e9; color: #13241d; font: 16px/1.75 Inter, "Noto Sans SC", "Microsoft YaHei", sans-serif; margin: 0; }
    main { background: #fffdf7; border: 1px solid #dedbd0; border-radius: 14px; margin: 32px auto; max-width: 900px; padding: 32px; }
    h1 { font-family: Georgia, "Noto Serif SC", serif; font-size: 28px; margin: 0 0 8px; }
    h2 { font-family: Georgia, "Noto Serif SC", serif; font-size: 22px; margin: 28px 0 12px; }
    .meta { color: #66726d; font-size: 13px; margin: 0; }
    .problem { background: #f5f2e9; border-radius: 10px; margin-top: 20px; padding: 16px; white-space: pre-wrap; }
    .mathMarkdown p, .mathMarkdown ul, .mathMarkdown ol { margin: 0 0 .85em; }
    .mathMarkdown .katex-display, pre { overflow-x: auto; }
    pre { background: #efece3; border-radius: 6px; padding: 12px 14px; }
    @media print { body { background: #fff; } main { border: 0; margin: 0; max-width: none; } }
  </style>
</head>
<body>
  <main>
    <h1>Auto Prove result</h1>
    <p class="meta">Exported from Proof Lab on ${escapeHtml(exportedAt)}</p>
    <section class="problem">
      <h2>Problem</h2>
      ${problemExportContent.current.innerHTML}
    </section>
    <section>
      <h2>Proof${result.passed === false ? " (best attempt)" : ""}</h2>
      ${proofExportContent.current.innerHTML}
    </section>
  </main>
</body>
</html>`;
    const file = new Blob([documentHtml], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(file);
    const link = document.createElement("a");
    link.href = url;
    link.download = `proof-lab-${result.run_id ?? "proof"}.html`;
    link.click();
    URL.revokeObjectURL(url);
  }

  useEffect(() => {
    if (!busy) {
      runStartedAt.current = null;
      setElapsedSeconds(0);
      return;
    }
    if (runStartedAt.current === null) runStartedAt.current = Date.now();
    const updateElapsed = () => setElapsedSeconds(Math.floor((Date.now() - (runStartedAt.current ?? Date.now())) / 1000));
    updateElapsed();
    const timer = window.setInterval(updateElapsed, 1000);
    return () => window.clearInterval(timer);
  }, [busy]);

  const refreshHistory = useCallback(async () => {
    if (!authenticated) {
      setSavedRuns([]);
      onRunsChange([]);
      return;
    }
    const response = await apiFetch("/api/auto-prove/runs");
    if (!response.ok) return;
    const runs = await response.json() as SavedRun[];
    setSavedRuns(runs);
    onRunsChange(runs);
  }, [authenticated, onRunsChange]);

  useEffect(() => {
    void refreshHistory();
  }, [refreshHistory]);

  async function loadArtifacts(runId: string) {
    const response = await apiFetch(`/api/auto-prove/runs/${runId}`);
    if (!response.ok) return;
    const payload = await response.json() as RunArtifacts & {
      result?: Result | null;
      status?: string;
    };
    setRunArtifacts(payload);
    if (payload.meta) {
      setProblem(payload.meta.problem || "");
      setGuidance(payload.meta.guidance || "");
      setDepth(payload.meta.depth === "deep" ? "deep" : "quick");
      setFormalize(Boolean(payload.meta.formalize));
      setStatus(payload.meta.phase || payload.meta.status);
    }
    if (payload.result && typeof payload.result === "object") {
      setResult({ ...payload.result, run_id: runId, ok: payload.result.ok ?? true });
    }
  }

  async function openSavedRun(run: SavedRun) {
    if (busy) return;
    setActiveRunId(run.run_id);
    setResult(null);
    setRunArtifacts(null);
    setProblem(run.problem);
    setGuidance(run.guidance || "");
    setDepth(run.depth === "deep" ? "deep" : "quick");
    setFormalize(Boolean(run.formalize));
    setReferences([]);
    setStatus(run.phase || run.status);
    await loadArtifacts(run.run_id);
  }

  useEffect(() => {
    if (!selectedRunId) return;
    const run = savedRuns.find((item) => item.run_id === selectedRunId);
    if (run && activeRunId !== selectedRunId) void openSavedRun(run);
  }, [activeRunId, savedRuns, selectedRunId]);

  async function run(event: FormEvent, resume = false) {
    event.preventDefault();
    if (!problem.trim() || busy) return;
    if (!authenticated) {
      onError?.("Sign in to run Auto Prove. Proof runs are saved to your account.");
      return;
    }
    if (!modelConfigured) {
      onError?.("DEEPSEEK_API_KEY is required for Auto Prove.");
      return;
    }
    controller.current = new AbortController();
    setBusy(true);
    setResult(null);
    const continuingRunId = resume ? activeRunId : null;
    if (!resume) {
      setRunArtifacts(null);
      setActiveRunId(null);
    }
    setStatus(resume ? "Resuming proof workflow" : "Starting proof workflow");
    try {
      const response = await apiFetch("/api/auto-prove/stream", {
        method: "POST",
        body: JSON.stringify({
          problem: problem.trim(),
          guidance: guidance.trim(),
          references,
          depth,
          formalize,
          run_id: continuingRunId,
          resume,
        }),
        signal: controller.current.signal,
      });
      if (!response.ok || !response.body) throw new Error("Auto Prove request failed");
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
          const line = eventText.split("\n").find((line) => line.startsWith("data: "));
          if (!line) continue;
          const eventData = JSON.parse(line.slice(6)) as Result & { type: string; phase?: string; label?: string };
          if (eventData.type === "status") {
            if (eventData.phase === "tool") {
              setToolStatus(eventData.label ?? "");
            } else if (eventData.phase === "tool_complete") {
              setToolStatus("");
            } else {
              setStatus(eventData.label ?? eventData.type);
              setToolStatus("");
            }
            if (eventData.run_id) setActiveRunId(eventData.run_id);
          }
          if (eventData.type === "result") {
            setResult(eventData);
            if (eventData.run_id) {
              setActiveRunId(eventData.run_id);
              void loadArtifacts(eventData.run_id);
            }
            const cancelled = Boolean(eventData.error?.toLowerCase().includes("cancelled"));
            setStatus(
              cancelled
                ? "Cancelled"
                : eventData.ok
                  ? eventData.passed === false
                    ? "Proof workflow finished without a passing review"
                    : "Proof workflow complete"
                  : "Failed",
            );
            void refreshHistory();
          }
        }
      }
    } catch (reason) {
      if ((reason as Error).name === "AbortError") setStatus("Cancelled");
      else onError?.(reason instanceof Error ? reason.message : "Auto Prove failed");
      void refreshHistory();
    } finally {
      controller.current = null;
      setBusy(false);
    }
  }

  async function cancelRun(runId?: string | null) {
    const id = runId ?? activeRunId;
    setStatus("Cancelling…");
    controller.current?.abort();
    if (id) {
      const response = await apiFetch(`/api/auto-prove/runs/${id}/cancel`, { method: "POST" });
      if (!response.ok) {
        onError?.("Could not cancel Auto Prove run");
        return;
      }
    }
    setStatus("Cancelled");
    setBusy(false);
    void refreshHistory();
  }

  async function submitResearchNote() {
    if (!activeRunId || !researchNote.trim()) return;
    const response = await apiFetch(`/api/auto-prove/runs/${activeRunId}/guidance`, {
      method: "POST",
      body: JSON.stringify({ guidance: researchNote.trim() }),
    });
    if (!response.ok) throw new Error("Could not save research guidance");
    setResearchNote("");
    setStatus("Research guidance saved; it will be used by the next agent call");
  }

  async function addReferences(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (!files.length || busy) return;
    const available = Math.max(0, 4 - references.length);
    if (!available) {
      onError?.("You can attach up to four reference files per proof run.");
      return;
    }
    setUploadingReferences(true);
    try {
      const extracted: ReferenceMaterial[] = [];
      for (const file of files.slice(0, available)) {
        const form = new FormData();
        form.append("file", file);
        const response = await apiFetch("/api/auto-prove/references/extract", { method: "POST", body: form });
        if (!response.ok) {
          const detail = await response.json().catch(() => null) as { detail?: string } | null;
          throw new Error(detail?.detail ?? `Could not read ${file.name}`);
        }
        extracted.push(await response.json() as ReferenceMaterial);
      }
      setReferences((current) => [...current, ...extracted]);
    } catch (reason) {
      onError?.(reason instanceof Error ? reason.message : "Could not read the reference file");
    } finally {
      setUploadingReferences(false);
    }
  }

  const activeMeta = savedRuns.find((r) => r.run_id === activeRunId);
  const canResume = Boolean(
    activeRunId
    && !busy
    && (
      status === "Failed"
      || status === "Cancelled"
      || activeMeta?.status === "failed"
      || activeMeta?.status === "cancelled"
    ),
  );
  const canStopActive = Boolean(activeRunId && (busy || activeMeta?.status === "running"));

  return (
    <section className="autoProve">
      <header className="leanHeader">
        <div>
          <span className="chapterTag">AUTO PROVE</span>
          <h2>Proof search, with a referee loop</h2>
          <p className="leanSubtitle">
            A structured QED workflow surveys relevant literature, decomposes the problem, develops candidate
            proofs, and reviews them before revising the proof or strategy. Sage and research tools provide
            evidence throughout. Every run is saved to your account; a conclusion is formally verified only
            when the optional Lean check passes.
          </p>
        </div>
        <span className={`leanStatus ${modelConfigured ? "ok" : "bad"}`}>
          {modelConfigured ? "Model ready" : "API unavailable"}
        </span>
      </header>
      <form className="autoProveForm" onSubmit={run}>
        <LatexField apiBase={apiBase} disabled={busy} label="Problem to prove (LaTeX format)" modelConfigured={modelConfigured} showPasteHint={false}
          onChange={setProblem} placeholder="State a theorem or exercise precisely. LaTex is supported." rows={8} value={problem} />
        <div aria-hidden="true" className="autoProveExportSource" ref={problemExportContent}>
          <MathMarkdown content={problem} />
        </div>
        <div className="autoProveReferences">
          <label htmlFor="auto-prove-guidance">Research guidance, conjectures, and links (optional)</label>
          <p>Give the agents a direction, a counterexample lead, or paper URLs. Attach readable source files below; they are saved with this run.</p>
          <textarea
            disabled={busy}
            id="auto-prove-guidance"
            onChange={(event) => setGuidance(event.target.value)}
            placeholder="For example: conjecture that the obstruction is a parity barrier; compare https://arxiv.org/abs/...; avoid using unproved hypotheses."
            rows={5}
            value={guidance}
          />
          <input
            accept=".pdf,.txt,.md,.tex,.bib,.csv,.json"
            className="autoProveReferenceInput"
            disabled={!authenticated || busy || uploadingReferences || references.length >= 4}
            multiple
            onChange={(event) => void addReferences(event)}
            ref={referenceInput}
            type="file"
          />
          <button
            className="autoProveReferenceUpload"
            disabled={!authenticated || busy || uploadingReferences || references.length >= 4}
            onClick={() => referenceInput.current?.click()}
            type="button"
          >
            {uploadingReferences ? "Reading reference…" : "Attach reference"}
          </button>
          <span className="autoProveReferenceLimit">PDF, TXT, Markdown, LaTeX, BibTeX, CSV, or JSON · up to 4 files, 3 MB each</span>
          {references.length > 0 && (
            <div className="autoProveReferenceList" aria-label="Attached references">
              {references.map((reference, index) => (
                <div className="autoProveReference" key={`${reference.name}-${index}`}>
                  <span title={reference.name}>{reference.name}</span>
                  <button aria-label={`Remove ${reference.name}`} disabled={busy} onClick={() => setReferences((items) => items.filter((_, itemIndex) => itemIndex !== index))} type="button">×</button>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="autoProveControls">
          <span className="autoProveWorkflow">QED workflow · up to 4 proof attempts × 4 plan revisions × 4 rewrites</span>
          <label className="autoProveCheck"><input checked={formalize} disabled={busy} onChange={(e) => setFormalize(e.target.checked)} type="checkbox" /> Attempt Lean formalization</label>
          <button disabled={busy || !problem.trim()} type="submit">{busy ? "Working…" : "Prove"}</button>
          {(busy || canStopActive) && <button className="ghost" onClick={() => void cancelRun()} type="button">Cancel</button>}
        </div>
      </form>
      {(status || toolStatus) && <p className="autoProveStatus">{toolStatus || status}{busy ? ` · ${formatElapsed(elapsedSeconds)}` : ""}</p>}
      {activeRunId && <div className="autoProveResearch">
        <strong>Research run · {activeRunId}</strong>
        <p>Add a constraint, counterexample lead, or suggested direction. The next agent call reads it from the persistent run record.</p>
        <textarea disabled={!busy} onChange={(e) => setResearchNote(e.target.value)} placeholder="For example: avoid the current analytic route; first test the conjecture for prime powers." value={researchNote} />
        <button disabled={!busy || !researchNote.trim()} onClick={() => void submitResearchNote()} type="button">Add research guidance</button>
        {canResume && <button className="secondary" onClick={() => void run({ preventDefault() {} } as FormEvent, true)} type="button">Resume from checkpoint</button>}
      </div>}
      {result?.error && <p className="error">{result.error}</p>}
      {result?.proof && (
        <div className="autoProveResult">
          <div className="autoProveResultHead">
            <h3>Proof{result.passed === false ? " (best attempt)" : ""}</h3>
            <button className="autoProveDownload" onClick={downloadProofHtml} type="button">Download HTML</button>
          </div>
          <div ref={proofExportContent}><MathMarkdown content={result.proof} /></div>
        </div>
      )}
      {result?.review && result.review.length > 0 && <div className="autoProveReview"><strong>Remaining referee notes</strong><ul>{result.review.map((item) => <li key={item}>{item}</li>)}</ul></div>}
      {(result?.difficulty || result?.run_id) && (
        <div className="autoProveReview">
          {result.difficulty && <p><strong>Difficulty:</strong> {result.difficulty}</p>}
          <p>
            {result.proof_attempts ?? 0} proof(s) · {result.revisions ?? 0} plan revision(s) · {result.decompositions ?? 0} decomposition(s)
            {result.run_id ? ` · run ${result.run_id}` : ""}
          </p>
        </div>
      )}
      {result?.plan && <details className="autoProvePlan"><summary>Proof plan</summary><MathMarkdown content={result.plan} /></details>}
      {result?.related_work && <details className="autoProvePlan"><summary>Literature survey</summary><MathMarkdown content={result.related_work} /></details>}
      {runArtifacts && <details className="autoProvePlan"><summary>Research artifacts ({runArtifacts.files.length})</summary><ul>{runArtifacts.files.map((file) => <li key={file}><code>{file}</code></li>)}</ul></details>}
      {result?.formalization && <div className="autoProveReview"><strong>Lean attempt · {result.formalization.level ?? "not verified"}</strong><p>{result.formalization.error ?? result.formalization.notes?.join(" ") ?? "No result."}</p></div>}
    </section>
  );
}
