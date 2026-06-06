import { Search } from "lucide-react";
import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import * as postApi from "../api/posts";
import Pagination from "../components/Pagination";
import { usePostStore } from "../stores/postStore";
import type { PostPage } from "../types";

export default function PostListPage() {
  const { query, page, size, setQuery, setPage } = usePostStore();
  const [draftQuery, setDraftQuery] = useState(query);
  const [data, setData] = useState<PostPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    postApi
      .listPosts({ page, size, q: query })
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "게시글을 불러오지 못했습니다."));
  }, [page, query, size]);

  const handleSearch = (event: FormEvent) => {
    event.preventDefault();
    setQuery(draftQuery.trim());
  };

  return (
    <section className="stack">
      <div className="section-header">
        <div>
          <h1>Posts</h1>
          <p className="muted">제목 검색과 페이지네이션을 지원합니다.</p>
        </div>
        <form className="search-form" onSubmit={handleSearch}>
          <Search size={18} />
          <input
            value={draftQuery}
            onChange={(event) => setDraftQuery(event.target.value)}
            placeholder="Search title"
          />
          <button type="submit">Search</button>
        </form>
      </div>

      {error ? <p className="error">{error}</p> : null}
      <div className="post-list">
        {data?.items.map((post) => (
          <article className="post-card" key={post.id}>
            <div className="post-card-main">
              <Link to={`/posts/${post.id}`} className="post-title">
                {post.title}
              </Link>
              <p className="muted">
                {post.author.nickname} · {new Date(post.created_at).toLocaleDateString()}
              </p>
            </div>
            <div className="tag-row">
              {post.tags.map((tag) => (
                <span className="tag" key={tag.id}>
                  #{tag.name}
                </span>
              ))}
            </div>
          </article>
        ))}
      </div>
      {data ? (
        <Pagination page={page} size={size} total={data.total} onPageChange={setPage} />
      ) : null}
    </section>
  );
}
