"use client";

import {
  Bold,
  Code2,
  Heading2,
  ImageIcon,
  Italic,
  Link,
  List,
  ListOrdered,
  Quote,
  Type,
} from "lucide-react";
import { ChangeEvent, useRef, useState } from "react";
import MarkdownContent from "./MarkdownContent";
import { Button } from "./ui/button";
import { Textarea } from "./ui/textarea";

type MarkdownEditorProps = {
  value: string;
  onChange: (value: string) => void;
  onUploadImage?: (file: File) => Promise<string>;
};

type EditorMode = "write" | "preview";
type EditorFont = "sans" | "serif" | "mono";

function fontClass(font: EditorFont) {
  if (font === "serif") {
    return "font-serif";
  }
  if (font === "mono") {
    return "font-mono";
  }
  return "font-sans";
}

export default function MarkdownEditor({ value, onChange, onUploadImage }: MarkdownEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [mode, setMode] = useState<EditorMode>("write");
  const [editorFont, setEditorFont] = useState<EditorFont>("sans");
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [isUploading, setIsUploading] = useState(false);

  const replaceSelection = (nextText: string, selectOffset = nextText.length) => {
    const textarea = textareaRef.current;
    if (!textarea) {
      onChange(`${value}${nextText}`);
      return;
    }

    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    const nextValue = `${value.slice(0, start)}${nextText}${value.slice(end)}`;
    onChange(nextValue);

    requestAnimationFrame(() => {
      textarea.focus();
      const nextCursor = start + selectOffset;
      textarea.setSelectionRange(nextCursor, nextCursor);
    });
  };

  const wrapSelection = (prefix: string, suffix: string, placeholder: string) => {
    const textarea = textareaRef.current;
    const start = textarea?.selectionStart ?? value.length;
    const end = textarea?.selectionEnd ?? value.length;
    const selectedText = value.slice(start, end) || placeholder;
    const nextText = `${prefix}${selectedText}${suffix}`;
    replaceSelection(nextText, prefix.length + selectedText.length);
  };

  const prefixLines = (marker: string, placeholder: string) => {
    const textarea = textareaRef.current;
    const start = textarea?.selectionStart ?? value.length;
    const end = textarea?.selectionEnd ?? value.length;
    const selectedText = value.slice(start, end);
    const block = selectedText || placeholder;
    replaceSelection(
      block
        .split("\n")
        .map((line) => `${marker}${line}`)
        .join("\n")
    );
  };

  const wrapFontBlock = () => {
    const textarea = textareaRef.current;
    const start = textarea?.selectionStart ?? value.length;
    const end = textarea?.selectionEnd ?? value.length;
    const selectedText = value.slice(start, end) || "글꼴을 바꿀 문장";
    replaceSelection(`\n:::${editorFont}\n${selectedText}\n:::\n`);
  };

  const handleImageChange = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !onUploadImage) {
      return;
    }
    setUploadError(null);
    setIsUploading(true);
    try {
      const imageUrl = await onUploadImage(file);
      const alt = file.name.replace(/\.[^.]+$/, "") || "첨부 이미지";
      replaceSelection(`\n![${alt}](${imageUrl})\n`);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : "이미지를 업로드하지 못했습니다.");
    } finally {
      setIsUploading(false);
    }
  };

  const editorFontClass = fontClass(editorFont);

  return (
    <section className="flex min-w-0 flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2 border border-border bg-card p-2">
        <div className="flex flex-wrap items-center gap-1">
          <Button type="button" variant="ghost" size="icon" title="굵게" onClick={() => wrapSelection("**", "**", "굵은 글씨")}>
            <Bold />
          </Button>
          <Button type="button" variant="ghost" size="icon" title="기울임" onClick={() => wrapSelection("*", "*", "기울임")}>
            <Italic />
          </Button>
          <Button type="button" variant="ghost" size="icon" title="제목" onClick={() => prefixLines("## ", "제목")}>
            <Heading2 />
          </Button>
          <Button type="button" variant="ghost" size="icon" title="인용" onClick={() => prefixLines("> ", "인용문")}>
            <Quote />
          </Button>
          <Button type="button" variant="ghost" size="icon" title="목록" onClick={() => prefixLines("- ", "목록")}>
            <List />
          </Button>
          <Button type="button" variant="ghost" size="icon" title="번호 목록" onClick={() => prefixLines("1. ", "목록")}>
            <ListOrdered />
          </Button>
          <Button type="button" variant="ghost" size="icon" title="코드" onClick={() => wrapSelection("`", "`", "코드")}>
            <Code2 />
          </Button>
          <Button type="button" variant="ghost" size="icon" title="링크" onClick={() => wrapSelection("[", "](https://example.com)", "링크 텍스트")}>
            <Link />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            title="이미지 첨부"
            onClick={() => fileInputRef.current?.click()}
            disabled={isUploading || !onUploadImage}
          >
            <ImageIcon />
          </Button>
          <Button type="button" variant="ghost" size="icon" title="선택 글꼴 적용" onClick={wrapFontBlock}>
            <Type />
          </Button>
          <input ref={fileInputRef} className="hidden" type="file" accept="image/*" onChange={handleImageChange} />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            className="h-9 rounded-md border border-input bg-background px-2 text-sm font-semibold"
            value={editorFont}
            onChange={(event) => setEditorFont(event.target.value as EditorFont)}
            aria-label="에디터 글꼴"
          >
            <option value="sans">Sans</option>
            <option value="serif">Serif</option>
            <option value="mono">Mono</option>
          </select>
          <div className="flex rounded-md border border-input bg-background p-0.5">
            <Button type="button" variant={mode === "write" ? "secondary" : "ghost"} size="sm" onClick={() => setMode("write")}>
              작성
            </Button>
            <Button type="button" variant={mode === "preview" ? "secondary" : "ghost"} size="sm" onClick={() => setMode("preview")}>
              미리보기
            </Button>
          </div>
        </div>
      </div>
      {mode === "write" ? (
        <Textarea
          ref={textareaRef}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          rows={22}
          className={`min-h-[520px] resize-y leading-7 ${editorFontClass}`}
          placeholder="내용을 작성하세요. #태그 형식으로 태그를 추가할 수 있습니다."
        />
      ) : (
        <MarkdownContent
          value={value}
          emptyText="미리볼 내용이 없습니다."
          className={`min-h-[520px] rounded-md border border-input bg-background p-4 ${editorFontClass}`}
        />
      )}
      {uploadError ? <p className="text-sm font-semibold text-destructive">{uploadError}</p> : null}
    </section>
  );
}
