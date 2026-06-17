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

export type PostDuplicateCandidate = PostListItem & {
  reasons: string[];
  snippet: string;
};

export type PostDuplicateCheckResponse = {
  items: PostDuplicateCandidate[];
};

export type PostThumbnailResponse = {
  image_markdown: string;
  image_data_url: string;
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
  type: "create_post" | "apply_post_draft";
  title: string;
  content: string;
  tags: string[];
};

export type AgentChatContext = {
  page: "new_post" | "edit_post" | "list" | "detail" | "unknown";
  post_id?: number | null;
  title?: string | null;
  content?: string | null;
  tags?: string[];
};

export type AgentWorkflowStep = {
  id: string;
  label: string;
  status: "completed" | "needs_confirmation" | "pending";
  detail: string | null;
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
  steps: AgentWorkflowStep[];
  pending_action: AgentPendingAction | null;
  created_post: AgentCreatedPost | null;
};
