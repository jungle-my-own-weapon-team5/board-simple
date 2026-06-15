"use client";

import { Save } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import type { PostPayload } from "../api/posts";
import MarkdownEditor from "./MarkdownEditor";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

type PostFormProps = {
  initialTitle?: string;
  initialContent?: string;
  initialTags?: string[];
  submitLabel: string;
  onSubmit: (payload: PostPayload) => Promise<void>;
};

const TAG_SEPARATOR_PATTERN = /[,\s]+/;
const TAG_NAME_PATTERN = /^[0-9A-Za-z가-힣_]{1,50}$/;

function parseTagInput(input: string) {
  const seen = new Set<string>();
  const tags: string[] = [];
  const invalidTags: string[] = [];

  for (const rawTag of input.split(TAG_SEPARATOR_PATTERN)) {
    const tag = rawTag.trim().replace(/^#/, "").toLowerCase();
    if (!tag) {
      continue;
    }
    if (!TAG_NAME_PATTERN.test(tag)) {
      invalidTags.push(rawTag.trim());
      continue;
    }
    if (!seen.has(tag)) {
      seen.add(tag);
      tags.push(tag);
    }
  }

  return { tags, invalidTags };
}

export default function PostForm({
  initialTitle = "",
  initialContent = "",
  initialTags = [],
  submitLabel,
  onSubmit
}: PostFormProps) {
  const [title, setTitle] = useState(initialTitle);
  const [content, setContent] = useState(initialContent);
  const [tagInput, setTagInput] = useState(initialTags.join(", "));
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const parsedTags = useMemo(() => parseTagInput(tagInput), [tagInput]);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (parsedTags.invalidTags.length > 0) {
      setError("태그는 영문, 숫자, 한글, 밑줄(_)만 사용할 수 있습니다.");
      return;
    }
    setIsSubmitting(true);
    try {
      await onSubmit({ title, content, tags: parsedTags.tags });
    } catch (err) {
      setError(err instanceof Error ? err.message : "요청을 처리하지 못했습니다.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form className="flex flex-col gap-5" onSubmit={handleSubmit}>
      <label className="flex flex-col gap-2 text-sm font-semibold">
        <span>Title</span>
        <Input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          maxLength={200}
          required
          placeholder="제목"
        />
      </label>
      <MarkdownEditor value={content} onChange={setContent} />
      <label className="flex flex-col gap-2 text-sm font-semibold">
        <span>Tags</span>
        <Input
          value={tagInput}
          onChange={(event) => setTagInput(event.target.value)}
          placeholder="python, fastapi"
        />
      </label>
      <div className="flex flex-wrap gap-2">
        {parsedTags.tags.length === 0 ? <span className="text-sm text-muted-foreground">No tags</span> : null}
        {parsedTags.tags.map((tag) => (
          <Badge variant="secondary" key={tag}>
            #{tag}
          </Badge>
        ))}
      </div>
      {error ? <p className="font-semibold text-destructive">{error}</p> : null}
      <Button type="submit" className="w-fit" disabled={isSubmitting}>
        <Save />
        <span>{isSubmitting ? "Saving..." : submitLabel}</span>
      </Button>
    </form>
  );
}
