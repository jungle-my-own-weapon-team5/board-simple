"use client";

import { Save, UserRound } from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import * as userApi from "../api/users";
import { ApiError } from "../api/client";
import Pagination from "../components/Pagination";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { useAuthStore } from "../stores/authStore";
import type { MyCommentPage, PostPage } from "../types";

const PAGE_SIZE = 5;

function friendlyError(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return "로그인이 필요합니다. 다시 로그인해 주세요.";
    }
    if (error.status === 403) {
      return "이 작업을 할 권한이 없습니다.";
    }
    if (error.status === 409) {
      return "이미 사용 중인 닉네임입니다.";
    }
  }
  return error instanceof Error ? error.message : "요청을 처리하지 못했습니다.";
}

export default function ProfilePage() {
  const { user, setUser } = useAuthStore();
  const [nickname, setNickname] = useState(user?.nickname ?? "");
  const [postsPage, setPostsPage] = useState(1);
  const [commentsPage, setCommentsPage] = useState(1);
  const [posts, setPosts] = useState<PostPage | null>(null);
  const [comments, setComments] = useState<MyCommentPage | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setNickname(user?.nickname ?? "");
  }, [user?.nickname]);

  useEffect(() => {
    if (!user) {
      return;
    }
    userApi
      .listMyPosts({ page: postsPage, size: PAGE_SIZE })
      .then(setPosts)
      .catch((err) => setError(friendlyError(err)));
  }, [postsPage, user]);

  useEffect(() => {
    if (!user) {
      return;
    }
    userApi
      .listMyComments({ page: commentsPage, size: PAGE_SIZE })
      .then(setComments)
      .catch((err) => setError(friendlyError(err)));
  }, [commentsPage, user]);

  const handleNicknameSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setMessage(null);
    try {
      const updatedUser = await userApi.updateMe({ nickname: nickname.trim() });
      setUser(updatedUser);
      setMessage("닉네임을 변경했습니다.");
    } catch (err) {
      setError(friendlyError(err));
    }
  };

  if (!user) {
    return (
      <section className="mx-auto flex max-w-lg flex-col gap-4">
        <Card className="rounded-sm">
          <CardContent className="flex flex-col gap-4 p-6">
            <h1 className="font-serif-display text-2xl font-bold">로그인이 필요합니다</h1>
            <p className="text-sm text-muted-foreground">내 정보와 활동 내역은 로그인 후 확인할 수 있습니다.</p>
            <Button asChild className="w-fit rounded-sm">
              <Link href="/login?next=/me">로그인</Link>
            </Button>
          </CardContent>
        </Card>
      </section>
    );
  }

  return (
    <section className="mx-auto flex w-full max-w-6xl flex-col gap-6">
      <div className="border-b border-border/70 pb-5">
        <h1 className="font-serif-display flex items-center gap-2 text-3xl font-bold leading-[1.35]">
          <UserRound />
          <span>내 정보</span>
        </h1>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">{user.email}</p>
      </div>

      <Card className="rounded-sm">
        <CardHeader>
          <CardTitle className="font-serif-display text-xl font-bold">닉네임 변경</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="flex flex-col gap-3 sm:flex-row" onSubmit={handleNicknameSubmit}>
            <Input
              value={nickname}
              onChange={(event) => setNickname(event.target.value)}
              minLength={2}
              maxLength={32}
              required
            />
            <Button type="submit" className="rounded-sm sm:w-fit">
              <Save />
              <span>저장</span>
            </Button>
          </form>
          {message ? <p className="mt-3 text-sm font-semibold text-primary">{message}</p> : null}
          {error ? <p className="mt-3 text-sm font-semibold text-destructive">{error}</p> : null}
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="rounded-sm">
          <CardHeader>
            <CardTitle className="font-serif-display text-xl font-bold">내 글</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {posts?.items.length ? (
              posts.items.map((post) => (
                <div key={post.id} className="border-b border-border pb-3 last:border-b-0 last:pb-0">
                  <div className="mb-1 flex flex-wrap gap-2">
                    <Badge>{post.post_type}</Badge>
                    <Badge variant="outline">{post.category}</Badge>
                  </div>
                  <Link href={`/posts/${post.id}`} className="font-serif-display font-bold leading-7 hover:text-primary">
                    {post.title}
                  </Link>
                  <p className="text-sm text-muted-foreground">
                    댓글 {post.comment_count} · 조회 {post.view_count} · {new Date(post.created_at).toLocaleDateString()}
                  </p>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">아직 작성한 글이 없습니다.</p>
            )}
            {posts ? (
              <Pagination page={posts.page} size={posts.size} total={posts.total} onPageChange={setPostsPage} />
            ) : null}
          </CardContent>
        </Card>

        <Card className="rounded-sm">
          <CardHeader>
            <CardTitle className="font-serif-display text-xl font-bold">내 댓글</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {comments?.items.length ? (
              comments.items.map((comment) => (
                <div key={comment.id} className="border-b border-border pb-3 last:border-b-0 last:pb-0">
                  <Link href={`/posts/${comment.post_id}`} className="font-serif-display font-bold leading-7 hover:text-primary">
                    {comment.post_title}
                  </Link>
                  <p className="mt-1 break-words text-sm">{comment.content}</p>
                  <p className="text-sm text-muted-foreground">{new Date(comment.created_at).toLocaleString()}</p>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">아직 작성한 댓글이 없습니다.</p>
            )}
            {comments ? (
              <Pagination
                page={comments.page}
                size={comments.size}
                total={comments.total}
                onPageChange={setCommentsPage}
              />
            ) : null}
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
