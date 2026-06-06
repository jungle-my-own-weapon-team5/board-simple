import { FormEvent, useEffect, useState } from "react";
import * as commentApi from "../api/comments";
import { useAuthStore } from "../stores/authStore";
import type { Comment } from "../types";

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

  const handleSubmit = async (event: FormEvent) => {
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
    <section className="comments">
      <div className="section-header">
        <h2>Comments</h2>
        <span className="muted">{total}</span>
      </div>
      {user ? (
        <form className="comment-form" onSubmit={handleSubmit}>
          <textarea
            value={content}
            onChange={(event) => setContent(event.target.value)}
            rows={3}
            placeholder="댓글을 입력하세요."
          />
          <button type="submit">Add comment</button>
        </form>
      ) : (
        <p className="muted">로그인 후 댓글을 작성할 수 있습니다.</p>
      )}
      {error ? <p className="error">{error}</p> : null}
      <div className="comment-stack">
        {items.map((comment) => (
          <article className="comment" key={comment.id}>
            <div className="comment-meta">
              <strong>{comment.author.nickname}</strong>
              <span>{new Date(comment.created_at).toLocaleString()}</span>
            </div>
            <p>{comment.content}</p>
          </article>
        ))}
      </div>
      {hasMore ? (
        <button type="button" className="secondary-button" onClick={() => loadComments(items.length)}>
          View more
        </button>
      ) : null}
    </section>
  );
}
