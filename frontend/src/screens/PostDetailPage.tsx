"use client";

import { BookOpen, ExternalLink, ImageIcon, Pencil, Sparkles, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import * as aiApi from "../api/ai";
import { ApiError, getAssetUrl } from "../api/client";
import * as postApi from "../api/posts";
import CommentList from "../components/CommentList";
import MarkdownContent from "../components/MarkdownContent";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { useAuthStore } from "../stores/authStore";
import type { AgentRunResponse, ExternalSearchResponse, Post, RagSearchResponse, ThumbnailCandidate } from "../types";

const recentViewIncrements = new Map<number, number>();
const VIEW_INCREMENT_DEDUPE_MS = 1500;
const RAG_CONTENT_EXCERPT_LENGTH = 1000;

function cleanMarkdownForSearch(content: string) {
  return content
    .replace(/```[\s\S]*?```/g, " ")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[[^\]]*]\([^)]*\)/g, " ")
    .replace(/\[([^\]]+)]\([^)]*\)/g, "$1")
    .replace(/[#>*_~|-]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function buildRagQuery(post: Post) {
  const tagNames = post.tags.map((tag) => tag.name).join(", ");
  const contentExcerpt = cleanMarkdownForSearch(post.content).slice(0, RAG_CONTENT_EXCERPT_LENGTH);

  return [
    `제목: ${post.title}`,
    `글 유형: ${post.post_type}`,
    `카테고리: ${post.category}`,
    `태그: ${tagNames || "없음"}`,
    post.ai_search_summary ? `검색 요약: ${post.ai_search_summary}` : null,
    `본문 발췌: ${contentExcerpt}`
  ].filter(Boolean).join("\n");
}

function aiErrorMessage(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 0) {
      return error.message;
    }
    return `${error.status}: ${error.message}`;
  }
  return error instanceof Error ? error.message : "AI 보조 자료를 불러오지 못했습니다.";
}

export default function PostDetailPage() {
  const router = useRouter();
  const params = useParams<{ postId: string }>();
  const postId = params.postId;
  const { user } = useAuthStore();
  const [post, setPost] = useState<Post | null>(null);
  const [rag, setRag] = useState<RagSearchResponse | null>(null);
  const [external, setExternal] = useState<ExternalSearchResponse | null>(null);
  const [agent, setAgent] = useState<AgentRunResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [aiError, setAiError] = useState<string | null>(null);
  const [isAiLoading, setIsAiLoading] = useState(false);
  const [isThumbnailLoading, setIsThumbnailLoading] = useState(false);
  const [isThumbnailSelecting, setIsThumbnailSelecting] = useState(false);
  const [thumbnailCandidates, setThumbnailCandidates] = useState<ThumbnailCandidate[]>([]);

  const numericPostId = Number(postId);
  const isAuthor = user && post && user.id === post.author.id;

  useEffect(() => {
    if (!Number.isFinite(numericPostId)) {
      setError("잘못된 게시글입니다.");
      return;
    }
    postApi
      .getPost(numericPostId)
      .then(async (loadedPost) => {
        const now = Date.now();
        const lastIncrementedAt = recentViewIncrements.get(numericPostId) ?? 0;
        if (now - lastIncrementedAt < VIEW_INCREMENT_DEDUPE_MS) {
          setPost(loadedPost);
          return;
        }
        recentViewIncrements.set(numericPostId, now);
        const viewedPost = await postApi.incrementPostView(numericPostId);
        setPost(viewedPost);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "게시글을 불러오지 못했습니다."));
  }, [numericPostId]);

  const handleDelete = async () => {
    if (!post) {
      return;
    }
    if (!window.confirm("게시글을 삭제할까요?")) {
      return;
    }
    await postApi.deletePost(post.id);
    router.push("/");
  };

  const handleAiContext = async () => {
    if (!post) {
      return;
    }
    setIsAiLoading(true);
    setAiError(null);
    try {
      const ragQuery = buildRagQuery(post);
      const [ragResult, externalResult, agentResult] = await Promise.allSettled([
        aiApi.searchRag({ query: ragQuery, top_k: 3 }),
        aiApi.searchExternal({ keyword: post.title }),
        aiApi.runAgent({ goal: "게시글 근거와 토론 보조", topic: post.title })
      ]);
      const failures = [ragResult, externalResult, agentResult]
        .filter((result): result is PromiseRejectedResult => result.status === "rejected")
        .map((result) => aiErrorMessage(result.reason));

      if (ragResult.status === "fulfilled") {
        setRag(ragResult.value);
      }
      if (externalResult.status === "fulfilled") {
        setExternal(externalResult.value);
      }
      if (agentResult.status === "fulfilled") {
        setAgent(agentResult.value);
      }
      if (failures.length > 0) {
        setAiError(`일부 AI 요청이 실패했습니다. ${failures[0]}`);
      }
    } finally {
      setIsAiLoading(false);
    }
  };

  const handleGenerateThumbnail = async () => {
    if (!post) {
      return;
    }
    setIsThumbnailLoading(true);
    setError(null);
    try {
      const result = await postApi.generatePostThumbnailCandidates(post.id);
      setThumbnailCandidates(result.candidates);
    } catch (err) {
      setError(err instanceof Error ? err.message : "썸네일 후보를 생성하지 못했습니다.");
    } finally {
      setIsThumbnailLoading(false);
    }
  };

  const handleSelectThumbnail = async (candidate: ThumbnailCandidate) => {
    if (!post || !candidate.image_url) {
      return;
    }
    setIsThumbnailSelecting(true);
    setError(null);
    try {
      const updatedPost = await postApi.selectPostThumbnail(post.id, candidate.image_url);
      setPost(updatedPost);
      setThumbnailCandidates([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "썸네일을 저장하지 못했습니다.");
    } finally {
      setIsThumbnailSelecting(false);
    }
  };

  if (error) {
    return <p className="font-semibold text-destructive">{error}</p>;
  }

  if (!post) {
    return <p className="text-muted-foreground">Loading...</p>;
  }

  const actionButtons = isAuthor ? (
    <div className="flex flex-wrap items-center gap-2">
      <Button asChild variant="outline">
        <Link href={`/posts/${post.id}/edit`}>
          <Pencil />
          <span>Edit</span>
        </Link>
      </Button>
      <Button type="button" variant="outline" onClick={handleGenerateThumbnail} disabled={isThumbnailLoading}>
        <ImageIcon />
        <span>{isThumbnailLoading ? "후보 생성 중..." : "AI 썸네일 후보"}</span>
      </Button>
      <Button type="button" variant="destructive" onClick={handleDelete}>
        <Trash2 />
        <span>Delete</span>
      </Button>
    </div>
  ) : null;

  return (
    <article className="flex flex-col gap-5">
      {post.thumbnail_url ? (
        <>
          <div className="flex justify-end">{actionButtons}</div>
          <header className="relative min-h-[480px] overflow-hidden border border-border bg-card sm:min-h-[620px]">
            <img
              src={getAssetUrl(post.thumbnail_url)}
              alt={`${post.title} 썸네일`}
              className="absolute inset-0 h-full w-full object-cover object-top"
            />
            <div className="absolute inset-x-0 bottom-0 h-2/3 bg-gradient-to-t from-[hsl(var(--background))] via-[hsl(var(--background)/0.82)] to-transparent" />
            <div className="absolute inset-x-0 bottom-0 flex flex-col gap-4 p-5 sm:p-8">
              <div className="max-w-4xl">
                <h1 className="break-words text-3xl font-extrabold leading-tight sm:text-5xl">
                  {post.title}
                </h1>
                <p className="mt-3 text-sm text-muted-foreground">
                  {post.author.nickname} · 댓글 {post.comment_count} · 조회 {post.view_count} · {new Date(post.created_at).toLocaleString()}
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Badge>{post.post_type}</Badge>
                  <Badge variant="outline" className="bg-background/80">{post.category}</Badge>
                  {post.tags.map((tag) => (
                    <Badge key={tag.id} variant="secondary" className="bg-background/80">
                      #{tag.name}
                    </Badge>
                  ))}
                </div>
              </div>
            </div>
          </header>
        </>
      ) : (
        <>
          <header className="flex flex-col items-start justify-between gap-4 md:flex-row">
            <div>
              <h1 className="break-words text-3xl font-extrabold leading-tight sm:text-4xl">
                {post.title}
              </h1>
              <p className="text-sm text-muted-foreground">
                {post.author.nickname} · 댓글 {post.comment_count} · 조회 {post.view_count} · {new Date(post.created_at).toLocaleString()}
              </p>
            </div>
            {actionButtons}
          </header>
          <div className="flex flex-wrap gap-2">
            <Badge>{post.post_type}</Badge>
            <Badge variant="outline">{post.category}</Badge>
            <Badge variant="secondary">{post.has_ai_evidence ? "근거 있음" : "AI 미확인"}</Badge>
            {post.tags.map((tag) => (
              <Badge key={tag.id} variant="secondary">#{tag.name}</Badge>
            ))}
          </div>
        </>
      )}
      {thumbnailCandidates.length > 0 ? (
        <section className="flex flex-col gap-3 border border-border bg-card p-4">
          <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-lg font-extrabold">AI 썸네일 후보</h2>
              <p className="text-sm text-muted-foreground">
                마음에 드는 후보만 선택하세요. 선택하지 않으면 게시글 썸네일은 바뀌지 않습니다.
              </p>
            </div>
            <Button type="button" variant="outline" onClick={() => setThumbnailCandidates([])}>
              후보 닫기
            </Button>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            {thumbnailCandidates.map((candidate, index) => (
              <div key={`${candidate.image_url ?? "empty"}-${index}`} className="flex flex-col gap-3 rounded-md border border-border bg-background p-3">
                {candidate.image_url ? (
                  <img
                    src={getAssetUrl(candidate.image_url)}
                    alt={`${post.title} 썸네일 후보 ${index + 1}`}
                    className="aspect-[3/2] w-full rounded-sm object-cover"
                  />
                ) : (
                  <div className="grid aspect-[3/2] place-items-center rounded-sm border border-dashed border-border text-center text-sm text-muted-foreground">
                    이미지가 생성되지 않았습니다.
                  </div>
                )}
                <div className="flex flex-col gap-2">
                  <p className="text-sm font-bold">후보 {index + 1}</p>
                  <p className="line-clamp-4 text-xs leading-5 text-muted-foreground">{candidate.visual_brief}</p>
                  <Button
                    type="button"
                    size="sm"
                    disabled={!candidate.image_url || isThumbnailSelecting}
                    onClick={() => handleSelectThumbnail(candidate)}
                  >
                    {isThumbnailSelecting ? "저장 중..." : "이 썸네일 사용"}
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : null}
      <MarkdownContent value={post.content} className="border-y border-border py-5" />
      <section className="flex flex-col gap-3 border border-border bg-accent/40 p-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-lg font-extrabold">AI 근거와 토론 보조</h2>
            <p className="text-sm text-muted-foreground">사용자 댓글과 분리된 보조 자료 영역입니다.</p>
          </div>
          <Button type="button" variant="outline" onClick={handleAiContext} disabled={isAiLoading}>
            <Sparkles />
            <span>{isAiLoading ? "확인 중..." : "근거 찾아보기"}</span>
          </Button>
        </div>
        {aiError ? <p className="text-sm font-semibold text-destructive">{aiError}</p> : null}
        {rag ? (
          <div className="grid gap-3 lg:grid-cols-3">
            <Card>
              <CardContent className="p-4">
                <h3 className="mb-2 flex items-center gap-2 font-extrabold"><BookOpen size={18} /> RAG 요약</h3>
                {rag.weak_evidence ? (
                  <Badge variant="outline" className="mb-2">근거 부족</Badge>
                ) : null}
                {rag.searched_corpora.length > 0 ? (
                  <p className="mb-2 text-xs font-semibold text-muted-foreground">
                    검색 corpus: {rag.searched_corpora.join(" → ")}
                  </p>
                ) : null}
                <p className="text-sm text-muted-foreground">{rag.answer_summary}</p>
              </CardContent>
            </Card>
            {rag.citations.length === 0 ? (
              <Card>
                <CardContent className="p-4 text-sm text-muted-foreground">
                  내부 seed에서 기준치 이상의 근거를 찾지 못했습니다. 외부 자료를 확인하거나 seed 문서를 보강해야 합니다.
                </CardContent>
              </Card>
            ) : null}
            {rag.citations.slice(0, 2).map((item) => (
              <Card key={item.id}>
                <CardContent className="p-4 text-sm">
                  <p className="font-bold">{item.title}</p>
                  <p className="text-muted-foreground">{item.period} · 관련도 {item.relevance}</p>
                  <p>{item.summary}</p>
                  {item.source_url ? (
                    <Button asChild variant="outline" size="sm" className="mt-3">
                      <a href={item.source_url} target="_blank" rel="noreferrer">
                        <ExternalLink />
                        <span>근거 원문 보기</span>
                      </a>
                    </Button>
                  ) : null}
                </CardContent>
              </Card>
            ))}
          </div>
        ) : null}
        {external || agent ? (
          <div className="grid gap-3 md:grid-cols-2">
            <div className="border-t border-border pt-3 text-sm">
              <h3 className="mb-2 flex items-center gap-2 font-extrabold"><ExternalLink size={18} /> 외부 자료</h3>
              {external?.resources.map((item) => (
                <p key={item.title} className="text-muted-foreground">{item.provider}: {item.description}</p>
              ))}
            </div>
            <div className="border-t border-border pt-3 text-sm">
              <h3 className="mb-2 font-extrabold">Agent 실행 로그</h3>
              {agent?.steps.map((step) => (
                <p key={step.name}><span className="font-semibold">{step.name}</span>: {step.output}</p>
              ))}
            </div>
          </div>
        ) : null}
      </section>
      <CommentList postId={post.id} />
    </article>
  );
}
