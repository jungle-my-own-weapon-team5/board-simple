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

export type Post = {
  id: number;
  title: string;
  content: string;
  author: User;
  tags: Tag[];
  created_at: string;
  updated_at: string;
};

export type PostListItem = Omit<Post, "content">;

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

export type RagChatSource = {
  post_id: number;
  title: string;
  heading: string | null;
  anchor: string | null;
  snippet: string;
};

export type RagChatResponse = {
  answer: string;
  sources: RagChatSource[];
};

export type AgentPendingAction = {
  type: "create_post";
  title: string;
  content: string;
};

export type AgentSource = {
  post_id: number;
  title: string;
  heading: string | null;
  anchor: string | null;
  snippet: string;
};

export type AgentCreatedPost = {
  post_id: number;
  title: string;
};

export type AgentChatResponse = {
  answer: string;
  sources: AgentSource[];
  pending_action: AgentPendingAction | null;
  created_post: AgentCreatedPost | null;
};
