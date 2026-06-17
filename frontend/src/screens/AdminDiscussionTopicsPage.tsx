"use client";

import { Eye, EyeOff, Pin, RefreshCw, Save } from "lucide-react";
import { useEffect, useState } from "react";
import * as adminApi from "../api/admin";
import { ApiError } from "../api/client";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { useAuthStore } from "../stores/authStore";
import type { DiscussionTopic } from "../types";

function todayIsoDate() {
  return new Date().toISOString().slice(0, 10);
}

function errorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 403) {
      return "관리자 권한이 필요합니다.";
    }
    if (error.status === 401) {
      return "로그인이 필요합니다.";
    }
  }
  return error instanceof Error ? error.message : "요청을 처리하지 못했습니다.";
}

export default function AdminDiscussionTopicsPage() {
  const { user } = useAuthStore();
  const [topicDate, setTopicDate] = useState(todayIsoDate());
  const [topics, setTopics] = useState<DiscussionTopic[]>([]);
  const [editing, setEditing] = useState<Record<number, DiscussionTopic>>({});
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const loadTopics = async () => {
    setError(null);
    setIsLoading(true);
    try {
      const result = await adminApi.listDiscussionTopics({ topic_date: topicDate });
      setTopics(result);
      setEditing(Object.fromEntries(result.filter((item) => item.id).map((item) => [item.id as number, item])));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (user?.is_admin) {
      void loadTopics();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [topicDate, user?.is_admin]);

  if (!user?.is_admin) {
    return (
      <section className="mx-auto max-w-lg border border-border bg-card p-6">
        <h1 className="font-serif-display text-2xl font-bold">관리자 권한이 필요합니다</h1>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">토론거리 관리는 관리자 계정으로만 접근할 수 있습니다.</p>
      </section>
    );
  }

  const updateDraft = (topicId: number, patch: Partial<DiscussionTopic>) => {
    setEditing((current) => ({
      ...current,
      [topicId]: { ...current[topicId], ...patch }
    }));
  };

  const saveTopic = async (topic: DiscussionTopic) => {
    if (!topic.id) {
      return;
    }
    setError(null);
    try {
      const saved = await adminApi.updateDiscussionTopic(topic.id, {
        source: topic.source,
        title: topic.title,
        summary: topic.summary,
        question: topic.question,
        reason: topic.reason,
        tags: topic.tags,
        draft_title: topic.draft_title || topic.title,
        draft_content: topic.draft_content || topic.summary,
        draft_post_type: topic.draft_post_type,
        draft_category: topic.draft_category,
        is_pinned: topic.is_pinned,
        is_hidden: topic.is_hidden
      });
      setTopics((current) => current.map((item) => (item.id === saved.id ? saved : item)));
      setEditing((current) => ({ ...current, [saved.id as number]: saved }));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const refreshTopics = async () => {
    setError(null);
    setIsLoading(true);
    try {
      const result = await adminApi.refreshDiscussionTopics({ topic_date: topicDate });
      setTopics(result);
      setEditing(Object.fromEntries(result.filter((item) => item.id).map((item) => [item.id as number, item])));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <section className="mx-auto flex w-full max-w-7xl flex-col gap-6">
      <header className="flex flex-col justify-between gap-4 border-b border-border/70 pb-5 md:flex-row md:items-end">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">Topic Desk</p>
          <h1 className="font-serif-display text-3xl font-bold leading-[1.35] sm:text-4xl">토론거리 관리</h1>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">날짜별 추천 카드의 문구, 고정, 숨김, 글쓰기 초안을 관리합니다.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Input className="rounded-sm" type="date" value={topicDate} onChange={(event) => setTopicDate(event.target.value)} />
          <Button type="button" variant="outline" className="rounded-sm" onClick={() => void refreshTopics()} disabled={isLoading}>
            <RefreshCw />
            <span>{isLoading ? "처리 중" : "재생성"}</span>
          </Button>
        </div>
      </header>

      {error ? <p className="font-semibold text-destructive">{error}</p> : null}

      <div className="grid gap-4">
        {topics.map((topic) => {
          if (!topic.id) {
            return null;
          }
          const draft = editing[topic.id] ?? topic;
          return (
            <Card key={topic.id} className="bal-card relative overflow-hidden rounded-sm">
              <CardContent className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1fr)_320px]">
                <div className="flex min-w-0 flex-col gap-3">
                  <div className="flex flex-wrap gap-2">
                    <Badge className="rounded-sm" variant={draft.is_pinned ? "default" : "outline"}>고정 {draft.is_pinned ? "ON" : "OFF"}</Badge>
                    <Badge className="rounded-sm" variant={draft.is_hidden ? "outline" : "secondary"}>{draft.is_hidden ? "숨김" : "노출"}</Badge>
                    <Badge className="rounded-sm" variant="outline">{draft.topic_date}</Badge>
                  </div>
                  <Input className="rounded-sm" value={draft.source} onChange={(event) => updateDraft(topic.id as number, { source: event.target.value })} />
                  <Input className="font-serif-display rounded-sm text-lg font-bold" value={draft.title} onChange={(event) => updateDraft(topic.id as number, { title: event.target.value })} />
                  <Textarea className="rounded-sm leading-7" value={draft.summary} rows={3} onChange={(event) => updateDraft(topic.id as number, { summary: event.target.value })} />
                  <Textarea className="font-serif-display rounded-sm font-bold leading-7" value={draft.question} rows={2} onChange={(event) => updateDraft(topic.id as number, { question: event.target.value })} />
                  <Textarea className="rounded-sm leading-7" value={draft.reason} rows={2} onChange={(event) => updateDraft(topic.id as number, { reason: event.target.value })} />
                  <Input
                    className="rounded-sm"
                    value={draft.tags.join(", ")}
                    onChange={(event) => updateDraft(topic.id as number, { tags: event.target.value.split(",").map((tag) => tag.trim()).filter(Boolean) })}
                  />
                  {draft.citations.length > 0 ? (
                    <div className="rounded-sm border border-border bg-background p-3 text-sm">
                      <p className="mb-2 font-bold">추천 근거</p>
                      <div className="flex flex-col gap-2">
                        {draft.citations.map((citation) => (
                          <a key={citation.id} href={citation.source_url} target="_blank" rel="noreferrer" className="leading-6 text-muted-foreground hover:text-foreground">
                            {citation.title} · 관련도 {citation.relevance}
                          </a>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
                <div className="flex flex-col gap-3">
                  <Input className="font-serif-display rounded-sm font-bold" value={draft.draft_title ?? ""} onChange={(event) => updateDraft(topic.id as number, { draft_title: event.target.value })} />
                  <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-1">
                    <Input className="rounded-sm" value={draft.draft_post_type} onChange={(event) => updateDraft(topic.id as number, { draft_post_type: event.target.value })} />
                    <Input className="rounded-sm" value={draft.draft_category} onChange={(event) => updateDraft(topic.id as number, { draft_category: event.target.value })} />
                  </div>
                  <Textarea className="rounded-sm leading-7" value={draft.draft_content ?? ""} rows={10} onChange={(event) => updateDraft(topic.id as number, { draft_content: event.target.value })} />
                  <div className="flex flex-wrap gap-2">
                    <Button type="button" className="rounded-sm" variant={draft.is_pinned ? "default" : "outline"} onClick={() => updateDraft(topic.id as number, { is_pinned: !draft.is_pinned })}>
                      <Pin />
                      <span>고정</span>
                    </Button>
                    <Button type="button" className="rounded-sm" variant={draft.is_hidden ? "default" : "outline"} onClick={() => updateDraft(topic.id as number, { is_hidden: !draft.is_hidden })}>
                      {draft.is_hidden ? <EyeOff /> : <Eye />}
                      <span>{draft.is_hidden ? "숨김" : "노출"}</span>
                    </Button>
                    <Button type="button" className="rounded-sm" onClick={() => void saveTopic(draft)}>
                      <Save />
                      <span>저장</span>
                    </Button>
                  </div>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </section>
  );
}
