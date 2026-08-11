"use client";

import { FormEvent, useRef, useState } from "react";
import LatexField from "./LatexField";
import MathMarkdown from "./MathMarkdown";

type Result = {
  ok: boolean;
  proof?: string;
  plan?: string;
  review?: string[];
  revisions?: number;
  formalization?: { verified?: boolean; aligned?: boolean | null; level?: string; notes?: string[]; error?: string };
  error?: string;
};

type Props = {
  apiBase: string;
  modelConfigured: boolean;
  onError?: (message: string) => void;
};

export default function AutoProve({ apiBase, modelConfigured, onError }: Props) {
  const [problem, setProblem] = useState("");
  const [guidance, setGuidance] = useState("");
  const [depth, setDepth] = useState<"quick" | "deep">("quick");
  const [formalize, setFormalize] = useState(false);
  const [status, setStatus] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [busy, setBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);

  async function run(event: FormEvent) {
    event.preventDefault();
    if (!problem.trim() || busy) return;
    if (!modelConfigured) {
      onError?.("OPENAI_API_KEY is required for Auto Prove.");
      return;
    }
    controller.current = new AbortController();
    setBusy(true);
    setResult(null);
    setStatus("Starting proof workflow");
    try {
      const response = await fetch(`${apiBase}/api/auto-prove/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ problem: problem.trim(), guidance: guidance.trim(), depth, formalize }),
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
          if (eventData.type === "status") setStatus(eventData.label ?? eventData.type);
          if (eventData.type === "result") {
            setResult(eventData);
            setStatus(eventData.ok ? "Complete" : "Failed");
          }
        }
      }
    } catch (reason) {
      if ((reason as Error).name === "AbortError") setStatus("Cancelled");
      else onError?.(reason instanceof Error ? reason.message : "Auto Prove failed");
    } finally {
      controller.current = null;
      setBusy(false);
    }
  }

  function cancel() {
    controller.current?.abort();
  }

  return (
    <section className="autoProve">
      <header className="leanHeader">
        <div>
          <span className="chapterTag">AUTO PROVE</span>
          <h2>Proof search, with a referee loop</h2>
          <p className="leanSubtitle">
            A bounded QED-inspired workflow: plan, draft, independent review, and revision. Natural-language
            proofs remain unverified unless the optional Lean check succeeds.
          </p>
        </div>
        <span className={`leanStatus ${modelConfigured ? "ok" : "bad"}`}>
          {modelConfigured ? "Model ready" : "API unavailable"}
        </span>
      </header>
      <form className="autoProveForm" onSubmit={run}>
        <LatexField apiBase={apiBase} disabled={busy} label="Problem to prove" modelConfigured={modelConfigured}
          onChange={setProblem} placeholder="State a theorem or exercise precisely. LaTex is supported." rows={8} value={problem} />
        <LatexField apiBase={apiBase} disabled={busy} label="Hints or constraints (optional)" modelConfigured={modelConfigured}
          onChange={setGuidance} placeholder="For example: use induction; avoid advanced theorems." rows={4} value={guidance} />
        <div className="autoProveControls">
          <label>Mode <select disabled={busy} value={depth} onChange={(e) => setDepth(e.target.value as "quick" | "deep")}>
            <option value="quick">Quick — draft + two reviews</option><option value="deep">Deep — up to 2 revisions</option>
          </select></label>
          <label className="autoProveCheck"><input checked={formalize} disabled={busy} onChange={(e) => setFormalize(e.target.checked)} type="checkbox" /> Attempt Lean formalization</label>
          <button disabled={busy || !problem.trim()} type="submit">{busy ? "Working…" : "Prove"}</button>
          {busy && <button className="ghost" onClick={cancel} type="button">Cancel</button>}
        </div>
      </form>
      {status && <p className="autoProveStatus">{status}</p>}
      {result?.error && <p className="error">{result.error}</p>}
      {result?.proof && <div className="autoProveResult"><h3>Proof</h3><MathMarkdown content={result.proof} /></div>}
      {result?.review && result.review.length > 0 && <div className="autoProveReview"><strong>Remaining referee notes</strong><ul>{result.review.map((item) => <li key={item}>{item}</li>)}</ul></div>}
      {result?.plan && <details className="autoProvePlan"><summary>Proof plan</summary><MathMarkdown content={result.plan} /></details>}
      {result?.formalization && <div className="autoProveReview"><strong>Lean attempt · {result.formalization.level ?? "not verified"}</strong><p>{result.formalization.error ?? result.formalization.notes?.join(" ") ?? "No result."}</p></div>}
    </section>
  );
}
