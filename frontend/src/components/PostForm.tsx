"use client";

import { Image, Loader2, Save, SearchCheck } from "lucide-react";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import * as postApi from "../api/posts";
import type { PostPayload } from "../api/posts";
import { useEditorAgentStore, type AgentDraft } from "../stores/editorAgentStore";
import type { PostDuplicateCandidate } from "../types";
import MarkdownEditor from "./MarkdownEditor";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

type PostFormProps = {
  postId?: number;
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
  postId,
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
  const [duplicateMessage, setDuplicateMessage] = useState<string | null>(null);
  const [duplicateItems, setDuplicateItems] = useState<PostDuplicateCandidate[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isCheckingDuplicates, setIsCheckingDuplicates] = useState(false);
  const [isGeneratingThumbnail, setIsGeneratingThumbnail] = useState(false);
  const setApplyDraft = useEditorAgentStore((state) => state.setApplyDraft);
  const clearApplyDraft = useEditorAgentStore((state) => state.clearApplyDraft);
  const setAgentContext = useEditorAgentStore((state) => state.setContext);
  const clearAgentContext = useEditorAgentStore((state) => state.clearContext);
  const parsedTags = useMemo(() => parseTagInput(tagInput), [tagInput]);

  const applyAgentDraft = useCallback((draft: AgentDraft) => {
    setTitle(draft.title);
    setContent(draft.content);
    setTagInput(draft.tags.join(", "));
    setDuplicateItems([]);
    setDuplicateMessage(null);
    setError(null);
  }, []);

  useEffect(() => {
    setApplyDraft(applyAgentDraft);
    return () => clearApplyDraft(applyAgentDraft);
  }, [applyAgentDraft, clearApplyDraft, setApplyDraft]);

  useEffect(() => {
    setAgentContext({
      page: postId ? "edit_post" : "new_post",
      post_id: postId ?? null,
      title,
      content,
      tags: parsedTags.tags,
    });
    return () => clearAgentContext();
  }, [clearAgentContext, content, parsedTags.tags, postId, setAgentContext, title]);

  const buildPayload = (): PostPayload | null => {
    setError(null);
    if (parsedTags.invalidTags.length > 0) {
      setError("태그는 영문, 숫자, 한글, 밑줄(_)만 사용할 수 있습니다.");
      return null;
    }
    return { title, content, tags: parsedTags.tags };
  };

  const handleDuplicateCheck = async () => {
    const payload = buildPayload();
    if (!payload || isCheckingDuplicates) {
      return;
    }

    setDuplicateMessage(null);
    setIsCheckingDuplicates(true);
    try {
      const response = await postApi.checkDuplicatePosts({
        ...payload,
        exclude_post_id: postId,
      });
      setDuplicateItems(response.items);
      setDuplicateMessage(response.items.length > 0 ? null : "중복 의심 게시글이 없습니다.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "중복 검사를 실행하지 못했습니다.");
    } finally {
      setIsCheckingDuplicates(false);
    }
  };

  const insertThumbnail = (currentContent: string, imageMarkdown: string) => {
    const thumbnailPattern = /^!\[thumbnail\]\(data:image\/[^)]+\)\n{0,2}/;
    if (thumbnailPattern.test(currentContent)) {
      return currentContent.replace(thumbnailPattern, `${imageMarkdown}\n\n`);
    }
    return `${imageMarkdown}\n\n${currentContent}`;
  };

  const handleGenerateThumbnail = async () => {
    const payload = buildPayload();
    if (!payload || isGeneratingThumbnail) {
      return;
    }
    if (!payload.title.trim() || !payload.content.trim()) {
      setError("썸네일을 생성하려면 제목과 본문을 입력해주세요.");
      return;
    }

    setIsGeneratingThumbnail(true);
    try {
      const response = await postApi.generateThumbnail(payload);
      setContent((current) => insertThumbnail(current, response.image_markdown));
    } catch (err) {
      setError(err instanceof Error ? err.message : "썸네일을 생성하지 못했습니다.");
    } finally {
      setIsGeneratingThumbnail(false);
    }
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const payload = buildPayload();
    if (!payload) {
      return;
    }
    setIsSubmitting(true);
    try {
      await onSubmit(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : "요청을 처리하지 못했습니다.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <form className="flex flex-col gap-5" onSubmit={handleSubmit}>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          onClick={() => void handleDuplicateCheck()}
          disabled={isCheckingDuplicates}
        >
          {isCheckingDuplicates ? <Loader2 className="animate-spin" /> : <SearchCheck />}
          <span>{isCheckingDuplicates ? "Checking..." : "Duplicate check"}</span>
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => void handleGenerateThumbnail()}
          disabled={isGeneratingThumbnail}
        >
          {isGeneratingThumbnail ? <Loader2 className="animate-spin" /> : <Image />}
          <span>{isGeneratingThumbnail ? "Generating..." : "Generate thumbnail"}</span>
        </Button>
      </div>
      {duplicateMessage ? <p className="text-sm font-semibold text-muted-foreground">{duplicateMessage}</p> : null}
      {duplicateItems.length > 0 ? (
        <div className="rounded-md border border-border bg-muted/40 p-3">
          <p className="text-sm font-extrabold">중복 의심 게시글</p>
          <div className="mt-3 flex flex-col gap-3">
            {duplicateItems.map((item) => (
              <div key={item.id} className="border-t border-border pt-3 first:border-t-0 first:pt-0">
                <Link href={`/posts/${item.id}`} className="font-semibold hover:text-primary">
                  {item.title}
                </Link>
                <p className="mt-1 text-sm text-muted-foreground">{item.snippet}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {item.reasons.map((reason) => (
                    <Badge variant="secondary" key={reason}>
                      {reason}
                    </Badge>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : null}
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
