"use client";

import { FormEvent } from "react";

export type NotebookEntry = {
  id: number;
  kind: "experiment" | "conjecture" | "counterexample";
  title: string;
  content: string;
  payload: Record<string, unknown>;
  created_at: string;
};

type LabResult = {
  operation: string;
  args: string;
  ok: boolean;
  output: string;
};

const SAGE_OPS = [
  "gcd",
  "xgcd",
  "factor",
  "is_prime",
  "inverse_mod",
  "crt",
  "power_mod",
  "euler_phi",
  "multiplicative_order",
  "legendre_symbol",
  "kronecker",
  "primitive_root",
  "divisors",
  "next_prime",
  "quadratic_class_number",
  "elliptic_curve_invariants",
  "pari_bnfinit",
  "ideal_prime_dec",
  "pari_polgalois",
] as const;

type Props = {
  apiBase: string;
  clientId: string;
  entries: NotebookEntry[];
  labOp: string;
  labArgs: string;
  labSplit: string;
  labBusy: boolean;
  labResults: LabResult[];
  conjectureDraft: string;
  onLabOpChange: (value: string) => void;
  onLabArgsChange: (value: string) => void;
  onLabSplitChange: (value: string) => void;
  onConjectureDraftChange: (value: string) => void;
  onRunLab: (event: FormEvent) => void;
  onSaveConjecture: (event: FormEvent) => void;
  onDeleteEntry: (id: number) => void;
};

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

export default function NotebookPanel({
  apiBase,
  clientId,
  entries,
  labOp,
  labArgs,
  labSplit,
  labBusy,
  labResults,
  conjectureDraft,
  onLabOpChange,
  onLabArgsChange,
  onLabSplitChange,
  onConjectureDraftChange,
  onRunLab,
  onSaveConjecture,
  onDeleteEntry,
}: Props) {
  return (
    <div className="toolPanel">
      <header className="toolPanelHeader">
        <div>
          <span className="chapterTag">RESEARCH TOOL</span>
          <h2>Notebook</h2>
          <p className="toolPanelSubtitle">
            Run Sage experiments, register conjectures, and keep a persistent log of computational
            evidence. Polynomial ops use coefficients a₀,…,aₙ (e.g. x²+1 → 1,0,1).
          </p>
        </div>
        {clientId && (
          <a
            className="downloadLog"
            download
            href={`${apiBase}/api/notebook/export?client_id=${encodeURIComponent(clientId)}`}
          >
            ⇩ Export JSON
          </a>
        )}
      </header>

      <div className="toolPanelGrid">
        <section className="toolCard">
          <h3>Sage experiment</h3>
          <form className="notebookForm" onSubmit={onRunLab}>
            <label>
              Operation
              <select onChange={(event) => onLabOpChange(event.target.value)} value={labOp}>
                {SAGE_OPS.map((operation) => (
                  <option key={operation} value={operation}>
                    {operation}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Arguments (comma-separated)
              <input
                onChange={(event) => onLabArgsChange(event.target.value)}
                placeholder="e.g. 391, 299"
                value={labArgs}
              />
            </label>
            {labOp === "crt" && (
              <label>
                Split (residue count)
                <input
                  onChange={(event) => onLabSplitChange(event.target.value)}
                  placeholder="2"
                  value={labSplit}
                />
              </label>
            )}
            <button disabled={labBusy || !labArgs.trim()} type="submit">
              {labBusy ? "Running…" : "Run & save to notebook"}
            </button>
          </form>
        </section>

        <section className="toolCard">
          <h3>Register conjecture</h3>
          <form className="notebookForm" onSubmit={onSaveConjecture}>
            <label>
              Conjecture statement
              <textarea
                onChange={(event) => onConjectureDraftChange(event.target.value)}
                placeholder="State a testable conjecture explicitly — not a theorem."
                rows={4}
                value={conjectureDraft}
              />
            </label>
            <button disabled={!conjectureDraft.trim()} type="submit">
              Save conjecture
            </button>
          </form>
        </section>
      </div>

      {labResults.length > 0 && (
        <section className="toolCard">
          <h3>Recent runs (this session)</h3>
          <ul className="notebookList">
            {labResults.map((item, index) => (
              <li className={item.ok ? "ok" : "failed"} key={`run-${item.operation}-${index}`}>
                <code>
                  {item.operation}({item.args})
                </code>
                <span>{item.output}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="toolCard">
        <h3>Saved entries ({entries.length})</h3>
        {entries.length === 0 ? (
          <p className="emptyTool">No notebook entries yet. Run an experiment or save a conjecture.</p>
        ) : (
          <ul className="notebookList saved">
            {entries.map((item) => (
              <li className={`kind-${item.kind}`} key={item.id}>
                <div className="notebookEntryHead">
                  <span className="notebookKind">{item.kind}</span>
                  <time>{formatTime(item.created_at)}</time>
                  <button
                    aria-label="Delete entry"
                    className="iconBtnDark"
                    onClick={() => onDeleteEntry(item.id)}
                    type="button"
                  >
                    ×
                  </button>
                </div>
                <strong>{item.title}</strong>
                <pre>{item.content}</pre>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
