"use client";

import { Save } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import MarkdownEditor from "./MarkdownEditor";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

type PostFormProps = {
  initialTitle?: string;
  initialContent?: string;
  submitLabel: string;
  onSubmit: (payload: { title: string; content: string }) => Promise<void>;
};

const TAG_PATTERN = /#([0-9A-Za-z가-힣_]{1,50})/g;

function extractTags(content: string) {
  return Array.from(new Set([...content.matchAll(TAG_PATTERN)].map((match) => match[1].toLowerCase())));
}

export default function PostForm({
  initialTitle = "",
  initialContent = "",
  submitLabel,
  onSubmit
}: PostFormProps) {
  const [title, setTitle] = useState(initialTitle);
  const [content, setContent] = useState(initialContent);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const tags = useMemo(() => extractTags(content), [content]);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await onSubmit({ title, content });
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
      <div className="flex flex-wrap gap-2">
        {tags.length === 0 ? <span className="text-sm text-muted-foreground">No tags</span> : null}
        {tags.map((tag) => (
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
