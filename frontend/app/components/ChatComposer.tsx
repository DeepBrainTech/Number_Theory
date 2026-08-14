"use client";

import { ChangeEvent, ClipboardEvent, KeyboardEvent, useRef } from "react";

const MAX_IMAGES = 4;
const MAX_DOCUMENTS = 4;

export type PendingDocument = { file: File; name: string };

type Props = {
  value: string;
  images: string[];
  documents: PendingDocument[];
  onChange: (value: string) => void;
  onImagesChange: (images: string[]) => void;
  onDocumentsChange: (documents: PendingDocument[]) => void;
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
  documents,
  onChange,
  onImagesChange,
  onDocumentsChange,
  placeholder,
  disabled = false,
  onEnterSubmit,
}: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

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

  async function onFilesSelected(event: ChangeEvent<HTMLInputElement>) {
    const selected = Array.from(event.target.files ?? []);
    const imageFiles = selected.filter((file) => file.type.startsWith("image/")).slice(0, MAX_IMAGES - images.length);
    const documentFiles = selected
      .filter((file) => !file.type.startsWith("image/"))
      .slice(0, MAX_DOCUMENTS - documents.length);
    if (imageFiles.length > 0) {
      const attachments = await Promise.all(imageFiles.map(fileToDataUrl));
      onImagesChange([...images, ...attachments]);
    }
    if (documentFiles.length > 0) {
      onDocumentsChange([...documents, ...documentFiles.map((file) => ({ file, name: file.name }))]);
    }
    event.target.value = "";
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
      {documents.length > 0 && (
        <div className="chatDocuments" aria-label="Attached documents">
          {documents.map((document, index) => (
            <button
              className="chatDocument"
              key={`${document.name}-${index}`}
              onClick={() => onDocumentsChange(documents.filter((_, itemIndex) => itemIndex !== index))}
              type="button"
            >
              {document.name} ×
            </button>
          ))}
        </div>
      )}
      <div className="chatComposerInputRow">
        <input
          accept="image/*,.pdf,.docx,.txt,.md"
          className="chatComposerFileInput"
          disabled={disabled || (images.length >= MAX_IMAGES && documents.length >= MAX_DOCUMENTS)}
          multiple
          onChange={onFilesSelected}
          ref={fileInputRef}
          type="file"
        />
        <button
          aria-label="Attach images or documents"
          className="chatComposerAttach"
          disabled={disabled || (images.length >= MAX_IMAGES && documents.length >= MAX_DOCUMENTS)}
          onClick={() => fileInputRef.current?.click()}
          type="button"
        >
          +
        </button>
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
    </div>
  );
}
