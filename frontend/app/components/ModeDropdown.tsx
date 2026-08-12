"use client";

import { useEffect, useRef, useState } from "react";

export type DropdownOption = {
  value: string;
  label: string;
  description: string;
};

type Props = {
  value: string;
  options: DropdownOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
  ariaLabel: string;
};

export default function ModeDropdown({
  value,
  options,
  onChange,
  disabled = false,
  ariaLabel,
}: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const current = options.find((item) => item.value === value) ?? options[0];

  useEffect(() => {
    if (!open) return;
    function onPointerDown(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div className="modeDropdown" ref={rootRef}>
      <button
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label={ariaLabel}
        className="modeDropdownTrigger"
        disabled={disabled}
        onClick={() => setOpen((currentOpen) => !currentOpen)}
        type="button"
      >
        <span>{current.label}</span>
        <span aria-hidden className="modeDropdownChevron">
          ▾
        </span>
      </button>
      {open && (
        <div className="modeDropdownMenu" role="listbox">
          {options.map((item) => (
            <button
              aria-selected={item.value === value}
              className={`modeDropdownItem ${item.value === value ? "active" : ""}`}
              key={item.value}
              onClick={() => {
                onChange(item.value);
                setOpen(false);
              }}
              role="option"
              type="button"
            >
              <span className="modeDropdownItemLabel">{item.label}</span>
              <span className="modeDropdownTooltip" role="tooltip">
                {item.description}
              </span>
              {item.value === value && <span className="modeDropdownCheck">✓</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export const ANSWER_MODE_OPTIONS: DropdownOption[] = [
  {
    value: "auto",
    label: "Auto",
    description: "Pick teach, solve, or research automatically; can search the web and papers when needed.",
  },
  {
    value: "teach",
    label: "Teach",
    description: "Guided learning with definitions, intuition, examples — and literature when relevant.",
  },
  {
    value: "solve",
    label: "Solve",
    description: "Full problem-solving with steps and checks; can look up papers or OEIS when useful.",
  },
  {
    value: "physics",
    label: "Physics",
    description: "Physics problem-solving with model assumptions, units, dimensional checks, and derivations.",
  },
  {
    value: "research",
    label: "Research",
    description: "Literature-aware survey with fixed sections for results, evidence, conjectures, and gaps.",
  },
];

export const TEACH_DEPTH_OPTIONS: DropdownOption[] = [
  {
    value: "hint",
    label: "Hint",
    description: "Only the next useful step — no full proof or final answer.",
  },
  {
    value: "socratic",
    label: "Socratic",
    description: "Guiding questions and a plan; withhold the complete writeup for now.",
  },
  {
    value: "full",
    label: "Full",
    description: "A complete, carefully justified answer using the current mode template.",
  },
];
