import { useEffect, useState } from "react";
import { Navigate, useNavigate, useParams } from "react-router-dom";
import * as postApi from "../api/posts";
import PostForm from "../components/PostForm";
import { useAuthStore } from "../stores/authStore";
import type { Post } from "../types";

export default function PostEditorPage() {
  const navigate = useNavigate();
  const { postId } = useParams();
  const { user } = useAuthStore();
  const [post, setPost] = useState<Post | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isEditing = Boolean(postId);
  const numericPostId = Number(postId);

  useEffect(() => {
    if (!isEditing) {
      return;
    }
    postApi
      .getPost(numericPostId)
      .then(setPost)
      .catch((err) => setError(err instanceof Error ? err.message : "게시글을 불러오지 못했습니다."));
  }, [isEditing, numericPostId]);

  if (!user) {
    return <Navigate to="/login" state={{ next: isEditing ? `/posts/${postId}/edit` : "/posts/new" }} replace />;
  }

  if (error) {
    return <p className="error">{error}</p>;
  }

  if (isEditing && !post) {
    return <p className="muted">Loading...</p>;
  }

  const handleSubmit = async (payload: { title: string; content: string }) => {
    const saved = isEditing
      ? await postApi.updatePost(numericPostId, payload)
      : await postApi.createPost(payload);
    navigate(`/posts/${saved.id}`);
  };

  return (
    <section className="stack">
      <h1>{isEditing ? "Edit Post" : "Write Post"}</h1>
      <PostForm
        initialTitle={post?.title}
        initialContent={post?.content}
        submitLabel={isEditing ? "Update post" : "Create post"}
        onSubmit={handleSubmit}
      />
    </section>
  );
}
