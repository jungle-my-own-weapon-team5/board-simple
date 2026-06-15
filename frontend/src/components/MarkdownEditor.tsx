"use client";

import type { KeyboardEvent } from "react";
import { Card, CardContent } from "./ui/card";
import MarkdownRenderer from "./MarkdownRenderer";
import { Textarea } from "./ui/textarea";

type MarkdownEditorProps = {
  value: string;
  onChange: (value: string) => void;
};

const INDENT = "  ";

function selectedLineRange(value: string, selectionStart: number, selectionEnd: number) {
  const start = value.lastIndexOf("\n", selectionStart - 1) + 1;
  const effectiveEnd =
    selectionEnd > selectionStart && value[selectionEnd - 1] === "\n" ? selectionEnd - 1 : selectionEnd;
  const nextLineBreak = value.indexOf("\n", effectiveEnd);
  const end = nextLineBreak === -1 ? value.length : nextLineBreak;

  return { start, end };
}

function queueSelection(textarea: HTMLTextAreaElement, start: number, end: number) {
  window.requestAnimationFrame(() => {
    textarea.setSelectionRange(start, end);
  });
}

export default function MarkdownEditor({ value, onChange }: MarkdownEditorProps) {
  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Tab" || event.altKey || event.ctrlKey || event.metaKey) {
      return;
    }

    event.preventDefault();

    const textarea = event.currentTarget;
    const currentValue = textarea.value;
    const { selectionStart, selectionEnd } = textarea;

    if (selectionStart === selectionEnd && !event.shiftKey) {
      onChange(`${currentValue.slice(0, selectionStart)}${INDENT}${currentValue.slice(selectionEnd)}`);
      queueSelection(textarea, selectionStart + INDENT.length, selectionStart + INDENT.length);
      return;
    }

    const range = selectedLineRange(currentValue, selectionStart, selectionEnd);
    const block = currentValue.slice(range.start, range.end);
    const lines = block.split("\n");

    if (event.shiftKey) {
      const removals: Array<{ start: number; length: number }> = [];
      let offset = 0;

      const updatedBlock = lines
        .map((line) => {
          const removeLength = line.startsWith(INDENT)
            ? INDENT.length
            : line.startsWith("\t") || line.startsWith(" ")
              ? 1
              : 0;

          if (removeLength > 0) {
            removals.push({ start: range.start + offset, length: removeLength });
          }

          offset += line.length + 1;
          return line.slice(removeLength);
        })
        .join("\n");

      if (removals.length === 0) {
        return;
      }

      const removedBefore = (position: number) =>
        removals.reduce((total, removal) => {
          if (position <= removal.start) {
            return total;
          }

          return total + Math.min(removal.length, position - removal.start);
        }, 0);

      onChange(`${currentValue.slice(0, range.start)}${updatedBlock}${currentValue.slice(range.end)}`);
      queueSelection(textarea, selectionStart - removedBefore(selectionStart), selectionEnd - removedBefore(selectionEnd));
      return;
    }

    const updatedBlock = lines.map((line) => `${INDENT}${line}`).join("\n");
    const addedLength = INDENT.length * lines.length;

    onChange(`${currentValue.slice(0, range.start)}${updatedBlock}${currentValue.slice(range.end)}`);
    queueSelection(textarea, selectionStart + INDENT.length, selectionEnd + addedLength);
  };

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <label className="flex min-w-0 flex-col gap-2 text-sm font-semibold">
        <span>Markdown</span>
        <Textarea
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          rows={14}
          placeholder="Markdown으로 내용을 작성하세요."
        />
      </label>
      <Card className="min-w-0" aria-label="Markdown preview">
        <CardContent className="p-4">
          <span className="mb-2 block text-sm font-extrabold">Preview</span>
          <MarkdownRenderer content={value} />
        </CardContent>
      </Card>
    </div>
  );
}
