"use client";

import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import type { Components } from "react-markdown";

const components: Components = {
  p: ({ children }) => <p>{children}</p>,
  ul: ({ children }) => <ul>{children}</ul>,
  ol: ({ children }) => <ol>{children}</ol>,
  li: ({ children }) => <li>{children}</li>,
  strong: ({ children }) => <strong>{children}</strong>,
  em: ({ children }) => <em>{children}</em>,
  code: ({ children, className }) => {
    const isBlock = Boolean(className);
    if (isBlock) {
      return <code className={className}>{children}</code>;
    }
    return <code className="inlineCode">{children}</code>;
  },
  pre: ({ children }) => <pre className="codeBlock">{children}</pre>,
  a: ({ href, children }) => (
    <a href={href} rel="noreferrer" target="_blank">
      {children}
    </a>
  ),
};

/**
 * Markdown treats `\[` as an escaped `[`, so display math written as
 * `\[ ... \]` arrives as bare brackets and never reaches KaTeX.
 * Normalize common LaTeX delimiters before remark-math runs.
 */
export function normalizeMathDelimiters(content: string): string {
  let text = content.replace(/\r\n/g, "\n");

  // Display math: \[ ... \] (including multiline)
  text = text.replace(/\\\[((?:.|\n)*?)\\\]/g, (_match, body: string) => {
    const trimmed = body.trim();
    return `\n\n$$\n${trimmed}\n$$\n\n`;
  });

  // Inline math: \( ... \)
  text = text.replace(/\\\(((?:.|\n)*?)\\\)/g, (_match, body: string) => {
    return `$${body.trim()}$`;
  });

  // Bare bracket blocks that look like display math after Markdown escaping:
  // [\n 5\cdot7\cdot9=315. \n]
  text = text.replace(
    /(^|\n)\s*\[\s*\n([\s\S]*?)\n\s*\](?=\s*(?:\n|$))/g,
    (match, lead: string, body: string) => {
      if (!/[\\^_]|\\[a-zA-Z]+/.test(body) && !/[≡∞∑∫≤≥≠]/.test(body)) {
        return match;
      }
      return `${lead}\n$$\n${body.trim()}\n$$\n`;
    },
  );

  return text;
}

export default function MathMarkdown({ content }: { content: string }) {
  const normalized = normalizeMathDelimiters(content);
  return (
    <div className="mathMarkdown">
      <ReactMarkdown
        components={components}
        remarkPlugins={[remarkMath]}
        rehypePlugins={[[rehypeKatex, { strict: "ignore", throwOnError: false }]]}
      >
        {normalized}
      </ReactMarkdown>
    </div>
  );
}
