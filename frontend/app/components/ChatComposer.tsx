"use client";

import { ClipboardEvent, KeyboardEvent, useRef } from "react";

const MAX_IMAGES = 4;

type Props = {
  value: string;
  images: string[];
  onChange: (value: string) => void;
  onImagesChange: (images: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  onEnterSubmit?: () => void;
};

function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(new Error("Failed to read image"));
    reader.readAsDataURL(file);
  });
}

export default function ChatComposer({
  value,
  images,
  onChange,
  onImagesChange,
  placeholder,
  disabled = false,
  onEnterSubmit,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  async function onPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const items = event.clipboardData?.items;
    if (!items) return;
    for (const item of items) {
      if (!item.type.startsWith("image/")) continue;
      event.preventDefault();
      const file = item.getAsFile();
      if (!file) return;
      if (images.length >= MAX_IMAGES) return;
      const dataUrl = await fileToDataUrl(file);
      onImagesChange([...images, dataUrl]);
      return;
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== "Enter" || event.shiftKey || !onEnterSubmit) return;
    event.preventDefault();
    onEnterSubmit();
  }

  function removeImage(index: number) {
    onImagesChange(images.filter((_, itemIndex) => itemIndex !== index));
  }

  return (
    <div className="chatComposer">
      {images.length > 0 && (
        <div className="chatAttachments" aria-label="Attached images">
          {images.map((src, index) => (
            <div className="chatAttachment" key={`${src.slice(0, 48)}-${index}`}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img alt={`Attachment ${index + 1}`} src={src} />
              <button
                aria-label="Remove image"
                className="chatAttachmentRemove"
                disabled={disabled}
                onClick={() => removeImage(index)}
                type="button"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
      <textarea
        ref={textareaRef}
        className="chatComposerInput"
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
        onPaste={onPaste}
        placeholder={placeholder}
        rows={1}
        value={value}
      />
    </div>
  );
}
