export type User = {
  id: number;
  email: string;
  nickname: string;
  created_at: string;
};

export type Tag = {
  id: number;
  name: string;
};

export type RelatedPost = {
  post_id: number;
  title: string;
  score: number | null;
};

export type Post = {
  id: number;
  title: string;
  content: string;
  source_type: string | null;
  source_id: string | null;
  source_url: string | null;
  source_title: string | null;
  source_fetched_at: string | null;
  author: User;
  tags: Tag[];
  created_at: string;
  updated_at: string;
  related_posts: RelatedPost[];
};

export type PostListItem = Omit<Post, "content" | "related_posts">;

export type PostPage = {
  items: PostListItem[];
  total: number;
  page: number;
  size: number;
};

export type Comment = {
  id: number;
  post_id: number;
  content: string;
  author: User;
  created_at: string;
  updated_at: string;
};

export type CommentPage = {
  items: Comment[];
  total: number;
  offset: number;
  limit: number;
};

export type RagSource = {
  post_id: number;
  title: string;
  excerpt: string;
  score: number | null;
};

export type RagAskResponse = {
  answer: string;
  sources: RagSource[];
};

export type HackerNewsSource = "top" | "best" | "new" | "search";

export type HackerNewsPreviewItem = {
  hn_id: number;
  title: string;
  url: string | null;
  hn_url: string;
  author: string | null;
  points: number | null;
  comment_count: number | null;
  created_at: string | null;
  summary_status: "success" | "failed";
  summary: string | null;
  key_points: string[];
  is_imported: boolean;
  error: string | null;
};

export type HackerNewsPreviewResponse = {
  items: HackerNewsPreviewItem[];
};

export type HackerNewsImportResponse = {
  created: { post_id: number; hn_id: number; title: string }[];
  skipped: { hn_id: number; reason: string }[];
};
