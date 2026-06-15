"use client";

import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import { BookOpen, ExternalLink, Pencil, Sparkles, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import * as aiApi from "../api/ai";
import * as postApi from "../api/posts";
import CommentList from "../components/CommentList";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { useAuthStore } from "../stores/authStore";
import type { AgentRunResponse, ExternalSearchResponse, Post, RagSearchResponse } from "../types";

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
  const [isAiLoading, setIsAiLoading] = useState(false);

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
        const storageKey = `viewed-post:${numericPostId}`;
        if (window.sessionStorage.getItem(storageKey)) {
          setPost(loadedPost);
          return;
        }
        window.sessionStorage.setItem(storageKey, "1");
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
    try {
      const [ragResult, externalResult, agentResult] = await Promise.all([
        aiApi.searchRag({ query: post.title, top_k: 3 }),
        aiApi.searchExternal({ keyword: post.title }),
        aiApi.runAgent({ goal: "게시글 근거와 토론 보조", topic: post.title })
      ]);
      setRag(ragResult);
      setExternal(externalResult);
      setAgent(agentResult);
    } finally {
      setIsAiLoading(false);
    }
  };

  if (error) {
    return <p className="font-semibold text-destructive">{error}</p>;
  }

  if (!post) {
    return <p className="text-muted-foreground">Loading...</p>;
  }

  return (
    <article className="flex flex-col gap-5">
      <header className="flex flex-col items-start justify-between gap-4 md:flex-row">
        <div>
          <h1 className="break-words text-3xl font-extrabold leading-tight sm:text-4xl">
            {post.title}
          </h1>
          <p className="text-sm text-muted-foreground">
            {post.author.nickname} · 댓글 {post.comment_count} · 조회 {post.view_count} · {new Date(post.created_at).toLocaleString()}
          </p>
        </div>
        {isAuthor ? (
          <div className="flex flex-wrap items-center gap-2">
            <Button asChild variant="outline">
              <Link href={`/posts/${post.id}/edit`}>
                <Pencil />
                <span>Edit</span>
              </Link>
            </Button>
            <Button type="button" variant="destructive" onClick={handleDelete}>
              <Trash2 />
              <span>Delete</span>
            </Button>
          </div>
        ) : null}
      </header>
      <div className="flex flex-wrap gap-2">
        <Badge>{post.post_type}</Badge>
        <Badge variant="outline">{post.category}</Badge>
        <Badge variant="secondary">{post.has_ai_evidence ? "근거 있음" : "AI 미확인"}</Badge>
        {post.tags.map((tag) => (
          <Badge variant="secondary" key={tag.id}>
            #{tag.name}
          </Badge>
        ))}
      </div>
      <section className="markdown-body border-y border-border py-5">
        <ReactMarkdown rehypePlugins={[rehypeSanitize]}>{post.content}</ReactMarkdown>
      </section>
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
        {rag ? (
          <div className="grid gap-3 lg:grid-cols-3">
            <Card>
              <CardContent className="p-4">
                <h3 className="mb-2 flex items-center gap-2 font-extrabold"><BookOpen size={18} /> RAG 요약</h3>
                <p className="text-sm text-muted-foreground">{rag.answer_summary}</p>
              </CardContent>
            </Card>
            {rag.citations.slice(0, 2).map((item) => (
              <Card key={item.id}>
                <CardContent className="p-4 text-sm">
                  <p className="font-bold">{item.title}</p>
                  <p className="text-muted-foreground">{item.period} · 관련도 {item.relevance}</p>
                  <p>{item.summary}</p>
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
