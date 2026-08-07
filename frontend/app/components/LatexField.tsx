"use client";

import { ClipboardEvent, KeyboardEvent, useRef, useState } from "react";
import MathMarkdown from "./MathMarkdown";

type Props = {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
  disabled?: boolean;
  apiBase: string;
  modelConfigured: boolean;
  /** full = toolbar + preview (Lean); compact = minimal chat input */
  variant?: "full" | "compact";
  /** Enter sends; Shift+Enter inserts newline (compact chat). */
  onEnterSubmit?: () => void;
};

type Snippet = {
  label: string;
  insert: string;
  title?: string;
};

const SNIPPETS: Snippet[] = [
  { label: "ℤ", insert: "\\mathbb{Z}", title: "Integers" },
  { label: "ℚ", insert: "\\mathbb{Q}", title: "Rationals" },
  { label: "ℕ", insert: "\\mathbb{N}", title: "Natural numbers" },
  { label: "≡", insert: "\\equiv ", title: "Congruent" },
  { label: "mod", insert: "\\pmod{n}", title: "Modulo" },
  { label: "∣", insert: "\\mid ", title: "Divides" },
  { label: "gcd", insert: "\\gcd(a,b)", title: "GCD" },
  { label: "φ", insert: "\\varphi(n)", title: "Euler phi" },
  { label: "∀", insert: "\\forall ", title: "For all" },
  { label: "∃", insert: "\\exists ", title: "Exists" },
  { label: "frac", insert: "\\frac{a}{b}", title: "Fraction" },
  { label: "√", insert: "\\sqrt{n}", title: "Square root" },
  { label: "^", insert: "^{}", title: "Superscript" },
  { label: "_", insert: "_{}", title: "Subscript" },
  { label: "∑", insert: "\\sum_{i=1}^{n} ", title: "Sum" },
  { label: "∏", insert: "\\prod_{p\\mid n} ", title: "Product" },
  { label: "inline", insert: "$x$", title: "Inline math" },
  { label: "display", insert: "\n$$\n\n$$\n", title: "Display math block" },
];

function insertAtCursor(
  textarea: HTMLTextAreaElement,
  current: string,
  snippet: string,
  onChange: (value: string) => void,
) {
  const start = textarea.selectionStart ?? current.length;
  const end = textarea.selectionEnd ?? current.length;
  const next = current.slice(0, start) + snippet + current.slice(end);
  onChange(next);
  const cursor = start + snippet.length;
  requestAnimationFrame(() => {
    textarea.focus();
    textarea.setSelectionRange(cursor, cursor);
  });
}

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(new Error("Failed to read image"));
    reader.readAsDataURL(file);
  });
}

export default function LatexField({
  label,
  value,
  onChange,
  placeholder,
  rows = 5,
  disabled = false,
  apiBase,
  modelConfigured,
  variant = "full",
  onEnterSubmit,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [converting, setConverting] = useState(false);
  const [ocrNote, setOcrNote] = useState<string | null>(null);
  const [toolbarOpen, setToolbarOpen] = useState(variant === "full");

  async function transcribeImage(dataUrl: string) {
    if (!modelConfigured) {
      setOcrNote("OPENAI_API_KEY is required for image → LaTeX.");
      return;
    }
    const textarea = textareaRef.current;
    if (!textarea) return;
    setConverting(true);
    setOcrNote(null);
    try {
      const response = await fetch(`${apiBase}/api/latex/from-image`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image: dataUrl }),
      });
      if (!response.ok) throw new Error("Image transcription failed");
      const data = await response.json();
      if (!data.ok) throw new Error(data.error ?? "Transcription failed");
      const wrapped = (data.wrapped as string) || `$${data.latex}$`;
      insertAtCursor(textarea, value, wrapped, onChange);
      const confidence = data.confidence ? ` (${data.confidence} confidence)` : "";
      const notes = (data.notes as string[] | undefined)?.join(" · ") ?? "";
      setOcrNote(
        `Pasted formula → LaTeX${confidence}.${notes ? ` ${notes}` : " Edit below if needed."}`,
      );
    } catch (reason) {
      setOcrNote(reason instanceof Error ? reason.message : "Transcription failed");
    } finally {
      setConverting(false);
    }
  }

  async function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const items = event.clipboardData?.items;
    if (!items) return;
    for (const item of items) {
      if (!item.type.startsWith("image/")) continue;
      event.preventDefault();
      const file = item.getAsFile();
      if (!file) return;
      const dataUrl = await fileToDataUrl(file);
      await transcribeImage(dataUrl);
      return;
    }
  }

  function onSnippet(snippet: string) {
    const textarea = textareaRef.current;
    if (!textarea || disabled) return;
    insertAtCursor(textarea, value, snippet, onChange);
  }

  const previewSource = value.trim();
  const hasPreview = variant !== "compact" && /[$\\]/.test(previewSource);

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || !onEnterSubmit) return;
    event.preventDefault();
    onEnterSubmit();
  }

  return (
    <label className={`latexField ${variant === "compact" ? "compact" : ""}`}>
      {label ? <span className="latexFieldLabel">{label}</span> : null}
      {variant === "full" && toolbarOpen && (
        <div className="latexToolbar" role="toolbar" aria-label="LaTeX snippets">
          {SNIPPETS.map((item) => (
            <button
              className="latexChip"
              disabled={disabled || converting}
              key={item.label + item.insert}
              onClick={() => onSnippet(item.insert)}
              title={item.title ?? item.insert}
              type="button"
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
      {variant !== "compact" && (
        <p className="latexHint">
          Paste a formula screenshot here (Ctrl+V) to auto-transcribe to LaTeX, then fix with the chips above.
        </p>
      )}
      <textarea
        ref={textareaRef}
        className="latexInput"
        disabled={disabled || converting}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
        onPaste={onPaste}
        placeholder={placeholder}
        rows={rows}
        value={value}
      />
      {converting && <p className="latexStatus">Transcribing pasted image…</p>}
      {ocrNote && !converting && <p className="latexStatus">{ocrNote}</p>}
      {hasPreview && (
        <div className="latexPreview">
          <span className="latexPreviewLabel">Preview</span>
          <MathMarkdown content={previewSource} />
        </div>
      )}
    </label>
  );
}
