"use client";

import { ChangeEvent, FormEvent, useEffect, useRef, useState } from "react";
import LatexField from "./LatexField";
import MathMarkdown from "./MathMarkdown";
import { apiFetch } from "../lib/api";
import {
  type LiveRun,
  type ProveResult,
  type ProveStartBody,
  type RunArtifacts,
  type SavedRun,
} from "../lib/useAutoProveSession";

export type { SavedRun, ProveResult, RunArtifacts, LiveRun, ProveStartBody };

type Props = {
  apiBase: string;
  modelConfigured: boolean;
  authenticated: boolean;
  selectedRunId?: string | null;
  runs: SavedRun[];
  live: LiveRun | null;
  result: ProveResult | null;
  artifacts: RunArtifacts | null;
  starting: boolean;
  onProve: (body: ProveStartBody) => Promise<string | void>;
  onCancel: (runId?: string | null) => Promise<void> | void;
  onOpenRun: (run: SavedRun) => void;
  onError?: (message: string) => void;
};

type ReferenceMaterial = { name: string; content: string };

function formatElapsed(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return minutes ? `${minutes}m${remainder}s` : `${remainder}s`;
}

function elapsedSince(iso: string | null | undefined): number {
  if (!iso) return 0;
  const started = Date.parse(iso);
  if (Number.isNaN(started)) return 0;
  return Math.max(0, Math.floor((Date.now() - started) / 1000));
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function statusLabel(live: LiveRun | null, starting: boolean, fallback: string): string {
  if (live?.tool) {
    const tool = live.tool.startsWith("Tool:") ? live.tool : `Tool: ${live.tool}`;
    return tool;
  }
  if (live?.phase) return live.phase;
  if (starting) return "Starting proof workflow";
  return fallback;
}

export default function AutoProve({
  apiBase,
  modelConfigured,
  authenticated,
  selectedRunId,
  runs,
  live,
  result,
  artifacts,
  starting,
  onProve,
  onCancel,
  onOpenRun,
  onError,
}: Props) {
  const [problem, setProblem] = useState("");
  const [guidance, setGuidance] = useState("");
  const [depth, setDepth] = useState<"quick" | "deep">("quick");
  const [formalize, setFormalize] = useState(false);
  const [researchNote, setResearchNote] = useState("");
  const [references, setReferences] = useState<ReferenceMaterial[]>([]);
  const [uploadingReferences, setUploadingReferences] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const referenceInput = useRef<HTMLInputElement | null>(null);
  const proofExportContent = useRef<HTMLDivElement | null>(null);
  const problemExportContent = useRef<HTMLDivElement | null>(null);

  const selected = runs.find((run) => run.run_id === selectedRunId) ?? null;
  const activeRunId = live?.runId || selectedRunId || null;
  const running = Boolean(starting || live?.status === "running" || selected?.status === "running");
  const displayResult = running ? null : result;
  const displayStatus = running
    ? statusLabel(live, starting, selected?.phase || "Working…")
    : selected?.status === "failed"
      ? "Failed"
      : selected?.status === "cancelled"
        ? "Cancelled"
        : displayResult
          ? displayResult.ok
            ? displayResult.passed === false
              ? "Proof workflow finished without a passing review"
              : "Proof workflow complete"
            : "Failed"
          : selected?.phase || "";

  useEffect(() => {
    if (!running) {
      setElapsedSeconds(0);
      return;
    }
    const createdAt = live?.createdAt || selected?.created_at;
    const updateElapsed = () => setElapsedSeconds(elapsedSince(createdAt));
    updateElapsed();
    const timer = window.setInterval(updateElapsed, 1000);
    return () => window.clearInterval(timer);
  }, [live?.createdAt, running, selected?.created_at]);

  const openedId = useRef<string | null>(null);
  useEffect(() => {
    if (!selectedRunId) {
      openedId.current = null;
      return;
    }
    const run = runs.find((item) => item.run_id === selectedRunId);
    if (!run || openedId.current === selectedRunId) return;
    setProblem(run.problem);
    setGuidance(run.guidance || "");
    setDepth(run.depth === "deep" ? "deep" : "quick");
    setFormalize(Boolean(run.formalize));
    setReferences([]);
    openedId.current = selectedRunId;
    onOpenRun(run);
  }, [onOpenRun, runs, selectedRunId]);

  function downloadProofHtml() {
    if (!displayResult?.proof || !proofExportContent.current || !problemExportContent.current) return;

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
      <h2>Proof${displayResult.passed === false ? " (best attempt)" : ""}</h2>
      ${proofExportContent.current.innerHTML}
    </section>
  </main>
</body>
</html>`;
    const file = new Blob([documentHtml], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(file);
    const link = document.createElement("a");
    link.href = url;
    link.download = `proof-lab-${displayResult.run_id ?? "proof"}.html`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function run(event: FormEvent, resume = false) {
    event.preventDefault();
    if (!problem.trim() || running) return;
    if (!authenticated) {
      onError?.("Sign in to run Auto Prove. Proof runs are saved to your account.");
      return;
    }
    if (!modelConfigured) {
      onError?.("DEEPSEEK_API_KEY is required for Auto Prove.");
      return;
    }
    const reuseRun = Boolean(
      activeRunId
      && (resume || selected?.status === "cancelled" || selected?.status === "failed"),
    );
    await onProve({
      problem: problem.trim(),
      guidance: guidance.trim(),
      references,
      depth,
      formalize,
      run_id: reuseRun ? activeRunId : null,
      resume: reuseRun,
    });
  }

  async function submitResearchNote() {
    if (!activeRunId || !researchNote.trim()) return;
    const response = await apiFetch(`/api/auto-prove/runs/${activeRunId}/guidance`, {
      method: "POST",
      body: JSON.stringify({ guidance: researchNote.trim() }),
    });
    if (!response.ok) throw new Error("Could not save research guidance");
    setResearchNote("");
  }

  async function addReferences(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (!files.length || running) return;
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

  const canResume = Boolean(
    activeRunId
    && !running
    && (selected?.status === "failed" || selected?.status === "cancelled"),
  );

  return (
    <section className="autoProve">
      <header className="leanHeader">
        <div>
          <span className="chapterTag">AUTO PROVE</span>
          <h2>Proof search, with a referee loop</h2>
          <p className="leanSubtitle">
            A QED workflow surveys literature, decomposes the problem, writes a proof, and reviews it
            with citation checks against source URLs. Agents read and write the run directory, search
            repeatedly, and may use Sage for computation. Every run is saved to your account; a
            conclusion is formally verified only when the optional Lean check passes.
          </p>
        </div>
        <span className={`leanStatus ${modelConfigured ? "ok" : "bad"}`}>
          {modelConfigured ? "Model ready" : "API unavailable"}
        </span>
      </header>
      <form className="autoProveForm" onSubmit={run}>
        <LatexField apiBase={apiBase} disabled={running} label="Problem to prove (LaTeX format)" modelConfigured={modelConfigured} showPasteHint={false}
          onChange={setProblem} placeholder="State a theorem or exercise precisely. LaTex is supported." rows={8} value={problem} />
        <div aria-hidden="true" className="autoProveExportSource" ref={problemExportContent}>
          <MathMarkdown content={problem} />
        </div>
        <div className="autoProveReferences">
          <label htmlFor="auto-prove-guidance">Research guidance, conjectures, and links (optional)</label>
          <p>Give the agents a direction, a counterexample lead, or paper URLs. Attach readable source files below; they are saved with this run. A <code>## Verification rules</code> section is treated as a hard requirement by the structural verifier.</p>
          <textarea
            disabled={running}
            id="auto-prove-guidance"
            onChange={(event) => setGuidance(event.target.value)}
            placeholder="For example: conjecture that the obstruction is a parity barrier; compare https://arxiv.org/abs/...; avoid using unproved hypotheses."
            rows={5}
            value={guidance}
          />
          <input
            accept=".pdf,.txt,.md,.tex,.bib,.csv,.json"
            className="autoProveReferenceInput"
            disabled={!authenticated || running || uploadingReferences || references.length >= 4}
            multiple
            onChange={(event) => void addReferences(event)}
            ref={referenceInput}
            type="file"
          />
          <button
            className="autoProveReferenceUpload"
            disabled={!authenticated || running || uploadingReferences || references.length >= 4}
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
                  <button aria-label={`Remove ${reference.name}`} disabled={running} onClick={() => setReferences((items) => items.filter((_, itemIndex) => itemIndex !== index))} type="button">×</button>
                </div>
              ))}
            </div>
          )}
        </div>
        <div className="autoProveControls">
          <span className="autoProveWorkflow">QED workflow · up to 4 proof attempts × 4 plan revisions × 4 rewrites</span>
          <label className="autoProveCheck"><input checked={formalize} disabled={running} onChange={(e) => setFormalize(e.target.checked)} type="checkbox" /> Attempt Lean formalization</label>
          <button disabled={running || !problem.trim()} type="submit">{running ? "Working…" : "Prove"}</button>
          {running && <button className="ghost" onClick={() => void onCancel(activeRunId)} type="button">Cancel</button>}
        </div>
      </form>
      {(displayStatus || running) && (
        <p className="autoProveStatus">
          {displayStatus}{running ? ` · ${formatElapsed(elapsedSeconds)}` : ""}
        </p>
      )}
      {activeRunId && <div className="autoProveResearch">
        <strong>Research run · {activeRunId}</strong>
        <p>Add a constraint, counterexample lead, or suggested direction. The next agent call reads it from the persistent run record.</p>
        <textarea disabled={!running} onChange={(e) => setResearchNote(e.target.value)} placeholder="For example: avoid the current analytic route; first test the conjecture for prime powers." value={researchNote} />
        <button disabled={!running || !researchNote.trim()} onClick={() => void submitResearchNote()} type="button">Add research guidance</button>
        {canResume && <button className="secondary" onClick={() => void run({ preventDefault() {} } as FormEvent, true)} type="button">Resume from checkpoint</button>}
      </div>}
      {displayResult?.error && <p className="error">{displayResult.error}</p>}
      {displayResult?.proof && (
        <div className="autoProveResult">
          <div className="autoProveResultHead">
            <h3>Proof{displayResult.passed === false ? " (best attempt)" : ""}</h3>
            <button className="autoProveDownload" onClick={downloadProofHtml} type="button">Download HTML</button>
          </div>
          <div ref={proofExportContent}><MathMarkdown content={displayResult.proof} /></div>
        </div>
      )}
      {displayResult?.review && displayResult.review.length > 0 && <div className="autoProveReview"><strong>Remaining referee notes</strong><ul>{displayResult.review.map((item) => <li key={item}>{item}</li>)}</ul></div>}
      {(displayResult?.difficulty || displayResult?.run_id) && (
        <div className="autoProveReview">
          {displayResult.difficulty && <p><strong>Difficulty:</strong> {displayResult.difficulty}</p>}
          <p>
            {displayResult.proof_attempts ?? 0} proof(s) · {displayResult.revisions ?? 0} plan revision(s) · {displayResult.decompositions ?? 0} decomposition(s)
            {displayResult.run_id ? ` · run ${displayResult.run_id}` : ""}
          </p>
        </div>
      )}
      {displayResult?.plan && <details className="autoProvePlan"><summary>Proof plan</summary><MathMarkdown content={displayResult.plan} /></details>}
      {displayResult?.related_work && <details className="autoProvePlan"><summary>Literature survey</summary><MathMarkdown content={displayResult.related_work} /></details>}
      {!running && artifacts && <details className="autoProvePlan"><summary>Research artifacts ({artifacts.files.length})</summary><ul>{artifacts.files.map((file) => <li key={file}><code>{file}</code></li>)}</ul></details>}
      {displayResult?.formalization && <div className="autoProveReview"><strong>Lean attempt · {displayResult.formalization.level ?? "not verified"}</strong><p>{displayResult.formalization.error ?? displayResult.formalization.notes?.join(" ") ?? "No result."}</p></div>}
    </section>
  );
}
