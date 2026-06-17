"use client";

import { useEffect, useState } from "react";
import type { SubmitEvent } from "react";
import * as commentApi from "../api/comments";
import { useAuthStore } from "../stores/authStore";
import type { Comment } from "../types";
import { Button } from "./ui/button";
import { Card, CardContent } from "./ui/card";
import { Textarea } from "./ui/textarea";

type CommentListProps = {
  postId: number;
};

const COMMENT_LIMIT = 5;

export default function CommentList({ postId }: CommentListProps) {
  const { user } = useAuthStore();
  const [items, setItems] = useState<Comment[]>([]);
  const [total, setTotal] = useState(0);
  const [content, setContent] = useState("");
  const [error, setError] = useState<string | null>(null);

  const loadComments = async (offset = 0) => {
    const page = await commentApi.listComments(postId, {
      offset,
      limit: COMMENT_LIMIT
    });
    setItems((current) => (offset === 0 ? page.items : [...current, ...page.items]));
    setTotal(page.total);
  };

  useEffect(() => {
    void loadComments(0);
  }, [postId]);

  const handleSubmit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!content.trim()) {
      return;
    }
    setError(null);
    try {
      await commentApi.createComment(postId, { content });
      setContent("");
      await loadComments(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "댓글을 저장하지 못했습니다.");
    }
  };

  const hasMore = items.length < total;

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-2xl font-extrabold">Comments</h2>
        <span className="text-sm text-muted-foreground">{total}</span>
      </div>
      {user ? (
        <form className="grid gap-2" onSubmit={handleSubmit}>
          <Textarea
            value={content}
            onChange={(event) => setContent(event.target.value)}
            rows={3}
            placeholder="댓글을 입력하세요."
          />
          <Button type="submit" variant="outline" className="w-fit">
            Add comment
          </Button>
        </form>
      ) : (
        <p className="text-sm text-muted-foreground">로그인 후 댓글을 작성할 수 있습니다.</p>
      )}
      {error ? <p className="font-semibold text-destructive">{error}</p> : null}
      <div className="grid gap-3">
        {items.map((comment) => (
          <Card key={comment.id}>
            <CardContent className="p-4">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                <strong>{comment.author.nickname}</strong>
                <span className="text-muted-foreground">
                  {new Date(comment.created_at).toLocaleString()}
                </span>
              </div>
              <p className="mt-2 break-words">{comment.content}</p>
            </CardContent>
          </Card>
        ))}
      </div>
      {hasMore ? (
        <Button type="button" variant="outline" className="w-fit" onClick={() => loadComments(items.length)}>
          View more
        </Button>
      ) : null}
    </section>
  );
}
