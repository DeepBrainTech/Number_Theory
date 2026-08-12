"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
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

type SavedRun = {
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
  onError?: (message: string) => void;
};

type RunArtifacts = { files: string[]; checkpoint?: string; status?: string; meta?: SavedRun };

function previewProblem(text: string, max = 96): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max)}…` : flat;
}

function statusLabel(run: SavedRun): string {
  if (run.status === "complete" && run.passed) return "Passed";
  if (run.status === "complete" && run.passed === false) return "Finished (not verified)";
  if (run.status === "failed") return "Failed";
  if (run.status === "running") return run.phase || "Running";
  return run.status;
}

export default function AutoProve({ apiBase, modelConfigured, onError }: Props) {
  const [problem, setProblem] = useState("");
  const [guidance, setGuidance] = useState("");
  const [depth, setDepth] = useState<"quick" | "deep">("quick");
  const [formalize, setFormalize] = useState(false);
  const [status, setStatus] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [runArtifacts, setRunArtifacts] = useState<RunArtifacts | null>(null);
  const [researchNote, setResearchNote] = useState("");
  const [savedRuns, setSavedRuns] = useState<SavedRun[]>([]);
  const controller = useRef<AbortController | null>(null);

  const refreshHistory = useCallback(async () => {
    const response = await apiFetch("/api/auto-prove/runs");
    if (!response.ok) return;
    setSavedRuns(await response.json() as SavedRun[]);
  }, []);

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
      setStatus(payload.meta.phase || statusLabel(payload.meta));
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
    setStatus(statusLabel(run));
    await loadArtifacts(run.run_id);
  }

  async function run(event: FormEvent, resume = false) {
    event.preventDefault();
    if (!problem.trim() || busy) return;
    if (!modelConfigured) {
      onError?.("OPENAI_API_KEY is required for Auto Prove.");
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
          const eventData = JSON.parse(line.slice(6)) as Result & { type: string; label?: string };
          if (eventData.type === "status") {
            setStatus(eventData.label ?? eventData.type);
            if (eventData.run_id) setActiveRunId(eventData.run_id);
          }
          if (eventData.type === "result") {
            setResult(eventData);
            if (eventData.run_id) {
              setActiveRunId(eventData.run_id);
              void loadArtifacts(eventData.run_id);
            }
            setStatus(eventData.ok ? "Complete" : "Failed");
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

  function cancel() {
    controller.current?.abort();
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

  const canResume = Boolean(activeRunId && !busy && (status === "Failed" || savedRuns.find((r) => r.run_id === activeRunId)?.status === "failed"));

  return (
    <section className="autoProve">
      <header className="leanHeader">
        <div>
          <span className="chapterTag">AUTO PROVE</span>
          <h2>Proof search, with a referee loop</h2>
          <p className="leanSubtitle">
            QED-style loop: literature survey, decomposition plan, proof, structural then detailed review,
            and a regulator that can revise the proof, revise the plan, or rewrite the strategy. Sage and
            literature tools are available to the agents. Runs are saved to your account so you can reopen
            them later. Natural-language proofs remain unverified unless the optional Lean check succeeds.
          </p>
        </div>
        <span className={`leanStatus ${modelConfigured ? "ok" : "bad"}`}>
          {modelConfigured ? "Model ready" : "API unavailable"}
        </span>
      </header>
      {savedRuns.length > 0 && (
        <div className="autoProveHistory">
          <div className="autoProveHistoryHead">
            <strong>Your research runs</strong>
            <button className="ghost" disabled={busy} onClick={() => void refreshHistory()} type="button">Refresh</button>
          </div>
          <ul>
            {savedRuns.map((run) => (
              <li key={run.run_id}>
                <button
                  className={activeRunId === run.run_id ? "active" : undefined}
                  disabled={busy}
                  onClick={() => void openSavedRun(run)}
                  type="button"
                >
                  <span className="autoProveHistoryTitle">{previewProblem(run.problem)}</span>
                  <span className="autoProveHistoryMeta">
                    {statusLabel(run)}
                    {run.difficulty ? ` · ${run.difficulty}` : ""}
                    {` · ${run.run_id}`}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <form className="autoProveForm" onSubmit={run}>
        <LatexField apiBase={apiBase} disabled={busy} label="Problem to prove" modelConfigured={modelConfigured}
          onChange={setProblem} placeholder="State a theorem or exercise precisely. LaTex is supported." rows={8} value={problem} />
        <LatexField apiBase={apiBase} disabled={busy} label="Hints or constraints (optional)" modelConfigured={modelConfigured}
          onChange={setGuidance} placeholder="For example: use induction; avoid advanced theorems." rows={4} value={guidance} />
        <div className="autoProveControls">
          <span className="autoProveWorkflow">QED workflow · up to 4 proof attempts × 4 plan revisions × 4 rewrites</span>
          <label className="autoProveCheck"><input checked={formalize} disabled={busy} onChange={(e) => setFormalize(e.target.checked)} type="checkbox" /> Attempt Lean formalization</label>
          <button disabled={busy || !problem.trim()} type="submit">{busy ? "Working…" : "Prove"}</button>
          {busy && <button className="ghost" onClick={cancel} type="button">Cancel</button>}
        </div>
      </form>
      {status && <p className="autoProveStatus">{status}</p>}
      {activeRunId && <div className="autoProveResearch">
        <strong>Research run · {activeRunId}</strong>
        <p>Add a constraint, counterexample lead, or suggested direction. The next agent call reads it from the persistent run record.</p>
        <textarea disabled={!busy} onChange={(e) => setResearchNote(e.target.value)} placeholder="For example: avoid the current analytic route; first test the conjecture for prime powers." value={researchNote} />
        <button disabled={!busy || !researchNote.trim()} onClick={() => void submitResearchNote()} type="button">Add research guidance</button>
        {canResume && <button className="secondary" onClick={() => void run({ preventDefault() {} } as FormEvent, true)} type="button">Resume from checkpoint</button>}
      </div>}
      {result?.error && <p className="error">{result.error}</p>}
      {result?.proof && <div className="autoProveResult"><h3>Proof{result.passed === false ? " (best attempt)" : ""}</h3><MathMarkdown content={result.proof} /></div>}
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
