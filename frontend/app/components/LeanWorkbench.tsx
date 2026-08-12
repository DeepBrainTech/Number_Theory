"use client";

import { FormEvent, useState } from "react";
import LatexField from "./LatexField";
import MathMarkdown from "./MathMarkdown";
import { apiFetch } from "../lib/api";

type LeanResult = {
  verified: boolean;
  aligned: boolean | null;
  level: string;
  statement: string | null;
  code: string;
  output: string;
  notes: string[];
};

type Props = {
  apiBase: string;
  leanAvailable: boolean;
  modelConfigured: boolean;
  conversationId: string | null;
  onAttachedToChat?: () => void;
  onError?: (message: string) => void;
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
    default:
      return "verification v0";
  }
}

export default function LeanWorkbench({
  apiBase,
  leanAvailable,
  modelConfigured,
  conversationId,
  onAttachedToChat,
  onError,
}: Props) {
  const [question, setQuestion] = useState("");
  const [method, setMethod] = useState("");
  const [statement, setStatement] = useState("");
  const [explanation, setExplanation] = useState("");
  const [caveats, setCaveats] = useState<string[]>([]);
  const [code, setCode] = useState(
    "-- Lean 4 + mathlib\n-- 1) Convert NL → statement\n-- 2) Edit / generate a proof\n-- 3) Compile & check alignment\n",
  );
  const [busy, setBusy] = useState<"statement" | "proof" | "compile" | "attach" | null>(null);
  const [result, setResult] = useState<LeanResult | null>(null);

  function fail(message: string) {
    onError?.(message);
  }

  async function toStatement(event?: FormEvent) {
    event?.preventDefault();
    const q = question.trim();
    if (!q || busy) return;
    if (!modelConfigured) {
      fail("OPENAI_API_KEY is required to translate into Lean.");
      return;
    }
    setBusy("statement");
    setResult(null);
    try {
      const response = await apiFetch("/api/formalize/statement", {
        method: "POST",
        body: JSON.stringify({ question: q, method: method.trim() }),
      });
      if (!response.ok) throw new Error("Statement request failed");
      const data = await response.json();
      if (!data.ok) throw new Error(data.error ?? "Statement generation failed");
      setStatement(data.statement ?? "");
      setCode(data.display_code ?? "");
      setExplanation(data.explanation ?? "");
      setCaveats(data.caveats ?? []);
    } catch (reason) {
      fail(reason instanceof Error ? reason.message : "Unknown error");
    } finally {
      setBusy(null);
    }
  }

  async function generateProof() {
    if (!statement.trim() || busy) return;
    if (!modelConfigured) {
      fail("OPENAI_API_KEY is required to generate a proof draft.");
      return;
    }
    setBusy("proof");
    setResult(null);
    try {
      const response = await apiFetch("/api/formalize/proof", {
        method: "POST",
        body: JSON.stringify({
          question: question.trim(),
          statement: statement.trim(),
          method: method.trim(),
        }),
      });
      if (!response.ok) throw new Error("Proof draft request failed");
      const data = await response.json();
      if (!data.ok) throw new Error(data.error ?? "Proof draft failed");
      setCode(data.code ?? "");
    } catch (reason) {
      fail(reason instanceof Error ? reason.message : "Unknown error");
    } finally {
      setBusy(null);
    }
  }

  async function compileAndCheck() {
    const q = question.trim();
    const lean = code.trim();
    if (!q || !lean || busy) return;
    if (!leanAvailable) {
      fail("Lean service is unavailable.");
      return;
    }
    setBusy("compile");
    try {
      const response = await apiFetch("/api/formalize/verify", {
        method: "POST",
        body: JSON.stringify({
          question: q,
          statement: statement.trim(),
          code: lean,
          method: method.trim(),
        }),
      });
      if (!response.ok) throw new Error("Compile request failed");
      const data = await response.json();
      if (!data.ok) throw new Error(data.error ?? "Verification failed");
      if (data.code) setCode(data.code);
      if (data.statement) setStatement(data.statement);
      setResult({
        verified: Boolean(data.verified),
        aligned: data.aligned ?? null,
        level: data.level ?? "V0",
        statement: data.statement ?? statement,
        code: data.code ?? lean,
        output: data.output ?? "",
        notes: data.notes ?? [],
      });
    } catch (reason) {
      fail(reason instanceof Error ? reason.message : "Unknown error");
    } finally {
      setBusy(null);
    }
  }

  async function attachToChat() {
    if (!result || !conversationId || busy) return;
    setBusy("attach");
    try {
      const status =
        result.verified && result.aligned === true
          ? "Lean kernel **passed** and the statement matches the question (from Lean workbench)."
          : result.verified
            ? "Lean compiled from the workbench, but statement alignment is not confirmed — not V4."
            : "Lean compilation **failed** in the workbench.";
      const content =
        `${status}\n\n**Proposition:** ${question.trim()}\n\n\`\`\`lean\n${result.code}\n\`\`\`` +
        (result.verified ? "" : `\n\nCompiler output:\n\n\`\`\`\n${result.output}\n\`\`\``);
      const response = await apiFetch(
        `/api/conversations/${conversationId}/attach-verification`,
        {
          method: "POST",
          body: JSON.stringify({
            content,
            verification_level: result.level,
            verification_label: `Lean workbench · ${result.level}`,
            verification_notes: result.notes,
            tool_results: [
              {
                tool: "lean_workbench",
                ok: result.verified,
                verified: result.verified,
                aligned: result.aligned,
                code: result.code,
              },
            ],
          }),
        },
      );
      if (!response.ok) throw new Error("Failed to attach result to chat");
      onAttachedToChat?.();
    } catch (reason) {
      fail(reason instanceof Error ? reason.message : "Unknown error");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="leanWorkbench">
      <header className="leanHeader">
        <div>
          <span className="chapterTag">LEAN WORKBENCH</span>
          <h2>Formalize</h2>
          <p className="leanSubtitle">
            Natural language on the left · editable Lean + kernel result on the right. Paste formula
            screenshots into the text fields to transcribe LaTeX. V4 only after compile{" "}
            <em>and</em> NL↔statement alignment.
          </p>
        </div>
        <span className={`leanStatus ${leanAvailable ? "ok" : "bad"}`}>
          {leanAvailable ? "Lean ready" : "Lean offline"}
        </span>
      </header>

      <div className="leanPanes">
        <div className="leanPane">
          <h3>Proposition</h3>
          <form className="leanForm" onSubmit={toStatement}>
            <LatexField
              apiBase={apiBase}
              disabled={Boolean(busy)}
              label="What to prove"
              modelConfigured={modelConfigured}
              onChange={setQuestion}
              placeholder="e.g. For all natural numbers n, $n^2 + n$ is even. Paste a formula screenshot with Ctrl+V."
              rows={6}
              value={question}
            />
            <LatexField
              apiBase={apiBase}
              disabled={Boolean(busy)}
              label="Proof idea (optional)"
              modelConfigured={modelConfigured}
              onChange={setMethod}
              placeholder="e.g. Factor $n(n+1)$; among two consecutive integers one is even."
              rows={5}
              value={method}
            />
            <div className="leanActions">
              <button disabled={Boolean(busy) || !question.trim()} type="submit">
                {busy === "statement" ? "Translating…" : "→ Lean statement"}
              </button>
              <button
                disabled={Boolean(busy) || !statement.trim()}
                onClick={generateProof}
                type="button"
              >
                {busy === "proof" ? "Drafting…" : "Generate proof draft"}
              </button>
            </div>
          </form>

          {(explanation || caveats.length > 0 || statement) && (
            <div className="leanMeta">
              {statement && (
                <p>
                  <strong>Statement</strong>
                  <code>{statement}</code>
                </p>
              )}
              {explanation && (
                <div className="leanExplanation">
                  <strong>Translation check</strong>
                  <MathMarkdown content={explanation} />
                </div>
              )}
              {caveats.length > 0 && (
                <ul>
                  {caveats.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        <div className="leanPane">
          <h3>Lean code &amp; result</h3>
          <textarea
            className="leanEditor"
            onChange={(event) => setCode(event.target.value)}
            spellCheck={false}
            value={code}
          />
          <div className="leanActions">
            <button
              disabled={Boolean(busy) || !question.trim() || !code.trim()}
              onClick={compileAndCheck}
              type="button"
            >
              {busy === "compile" ? "Compiling…" : "Compile & check"}
            </button>
            <button
              className="ghost"
              disabled={Boolean(busy) || !result || !conversationId}
              onClick={attachToChat}
              title={conversationId ? "Append this result to the active chat" : "Open a chat first"}
              type="button"
            >
              {busy === "attach" ? "Attaching…" : "Attach to chat"}
            </button>
          </div>

          {result && (
            <div className="leanResult">
              <div className={badgeClass(result.level)}>
                <span>Lean workbench · {result.level}</span>
                {result.notes.length > 0 && (
                  <ul>
                    {result.notes.slice(0, 5).map((note) => (
                      <li key={note}>{note}</li>
                    ))}
                  </ul>
                )}
              </div>
              {!result.verified && result.output && (
                <pre className="leanOutput">{result.output}</pre>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
