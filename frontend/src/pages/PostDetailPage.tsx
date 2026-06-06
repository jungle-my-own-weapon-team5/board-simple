import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import { Pencil, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import * as postApi from "../api/posts";
import CommentList from "../components/CommentList";
import { useAuthStore } from "../stores/authStore";
import type { Post } from "../types";

export default function PostDetailPage() {
  const navigate = useNavigate();
  const { postId } = useParams();
  const { user } = useAuthStore();
  const [post, setPost] = useState<Post | null>(null);
  const [error, setError] = useState<string | null>(null);

  const numericPostId = Number(postId);
  const isAuthor = user && post && user.id === post.author.id;

  useEffect(() => {
    if (!Number.isFinite(numericPostId)) {
      setError("잘못된 게시글입니다.");
      return;
    }
    postApi
      .getPost(numericPostId)
      .then(setPost)
      .catch((err) => setError(err instanceof Error ? err.message : "게시글을 불러오지 못했습니다."));
  }, [numericPostId]);

  const handleDelete = async () => {
    if (!post) {
      return;
    }
    await postApi.deletePost(post.id);
    navigate("/");
  };

  if (error) {
    return <p className="error">{error}</p>;
  }

  if (!post) {
    return <p className="muted">Loading...</p>;
  }

  return (
    <article className="stack">
      <header className="post-detail-header">
        <div>
          <h1>{post.title}</h1>
          <p className="muted">
            {post.author.nickname} · {new Date(post.created_at).toLocaleString()}
          </p>
        </div>
        {isAuthor ? (
          <div className="button-row">
            <Link className="icon-button" to={`/posts/${post.id}/edit`}>
              <Pencil size={18} />
              <span>Edit</span>
            </Link>
            <button type="button" className="danger-button" onClick={handleDelete}>
              <Trash2 size={18} />
              <span>Delete</span>
            </button>
          </div>
        ) : null}
      </header>
      <div className="tag-row">
        {post.tags.map((tag) => (
          <span className="tag" key={tag.id}>
            #{tag.name}
          </span>
        ))}
      </div>
      <section className="markdown-body post-body">
        <ReactMarkdown rehypePlugins={[rehypeSanitize]}>{post.content}</ReactMarkdown>
      </section>
      <CommentList postId={post.id} />
    </article>
  );
}
