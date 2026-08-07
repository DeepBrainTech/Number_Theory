"use client";

import { FormEvent } from "react";

export type Memory = {
  id: number;
  content: string;
  source_conversation_id?: string | null;
  created_at: string;
  updated_at: string;
};

type Props = {
  memories: Memory[];
  draft: string;
  onDraftChange: (value: string) => void;
  onAdd: (event: FormEvent) => void;
  onDelete: (id: number) => void;
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

export default function MemoryPanel({ memories, draft, onDraftChange, onAdd, onDelete }: Props) {
  return (
    <div className="toolPanel">
      <header className="toolPanelHeader">
        <div>
          <span className="chapterTag">PERSONALIZATION</span>
          <h2>Long-term memory</h2>
          <p className="toolPanelSubtitle">
            Facts the agent should remember across chats — learning level, notation preferences, or
            ongoing goals. Memories are also extracted automatically from conversations when relevant.
          </p>
        </div>
      </header>

      <section className="toolCard">
        <h3>Add memory</h3>
        <form className="notebookForm" onSubmit={onAdd}>
          <label>
            What should the agent remember?
            <textarea
              onChange={(event) => onDraftChange(event.target.value)}
              placeholder="e.g. I am comfortable with algebraic NT but new to p-adic methods."
              rows={3}
              value={draft}
            />
          </label>
          <button disabled={!draft.trim()} type="submit">
            Save memory
          </button>
        </form>
      </section>

      <section className="toolCard">
        <h3>Saved memories ({memories.length})</h3>
        {memories.length === 0 ? (
          <p className="emptyTool">No memories yet. Add one above or let chat extract them.</p>
        ) : (
          <ul className="memoryPanelList">
            {memories.map((item) => (
              <li key={item.id}>
                <p>{item.content}</p>
                <div className="memoryMeta">
                  <time>{formatTime(item.updated_at)}</time>
                  <button
                    aria-label="Delete memory"
                    className="iconBtnDark"
                    onClick={() => onDelete(item.id)}
                    type="button"
                  >
                    Delete
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
