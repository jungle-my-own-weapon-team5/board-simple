export type User = {
  id: number;
  email: string;
  nickname: string;
  created_at: string;
  is_admin: boolean;
};

export type Tag = {
  id: number;
  name: string;
};

export type Post = {
  id: number;
  title: string;
  content: string;
  post_type: string;
  category: string;
  ai_search_summary?: string | null;
  thumbnail_url?: string | null;
  view_count: number;
  comment_count: number;
  has_ai_evidence: boolean;
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

export type MyComment = {
  id: number;
  post_id: number;
  post_title: string;
  content: string;
  created_at: string;
  updated_at: string;
};

export type MyCommentPage = {
  items: MyComment[];
  total: number;
  page: number;
  size: number;
};

export type DiscussionTopic = {
  source: string;
  title: string;
  summary: string;
  question: string;
  reason: string;
  tags: string[];
};

export type WritingAssist = {
  improved_titles: string[];
  tags: string[];
  category: string;
  questions: string[];
  keywords: string[];
};

export type RagCitation = {
  id: string;
  title: string;
  period: string;
  summary: string;
  relevance: number;
  source_url: string;
};

export type RagSearchResponse = {
  answer_summary: string;
  citations: RagCitation[];
  weak_evidence: boolean;
};

export type RagQualityAttempt = {
  query: string;
  citation_count: number;
  max_relevance: number;
  weak_evidence: boolean;
  decision: string;
};

export type RagQualityAgentResponse = {
  final_query: string;
  answer_summary: string;
  citations: RagCitation[];
  weak_evidence: boolean;
  attempts: RagQualityAttempt[];
  agent_steps: { name: string; output: string }[];
  needs_external_search: boolean;
  suggested_external_keywords: string[];
};

export type ExternalSearchResponse = {
  resources: {
    title: string;
    provider: string;
    url: string;
    description: string;
  }[];
  tool_log: {
    tool: string;
    input: string;
    status: string;
    elapsed_ms: number;
  };
};

export type AgentRunResponse = {
  steps: { name: string; output: string }[];
  final_answer: string;
  tool_logs: ExternalSearchResponse["tool_log"][];
};

export type AgentChatPageContext = {
  path?: string | null;
  post_id?: number | null;
  post_title?: string | null;
  post_summary?: string | null;
};

export type ThumbnailPreviewResponse = {
  image_url: string | null;
  visual_brief: string;
  prompt: string;
  agent_steps: string[];
  tool_log: {
    tool: string;
    input: string;
    status: string;
    elapsed_ms: number;
  };
};
