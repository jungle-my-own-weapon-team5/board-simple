export type User = {
  id: number;
  email: string;
  nickname: string;
  created_at: string;
};

export type Author = {
  id: number;
  nickname: string;
};

export type Tag = {
  id: number;
  name: string;
};

export type Post = {
  id: number;
  title: string;
  content: string;
  author: Author;
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
  author: Author;
  created_at: string;
  updated_at: string;
};

export type CommentPage = {
  items: Comment[];
  total: number;
  offset: number;
  limit: number;
};

// AI/RAG 화면과 API client가 공유하는 검색·생성 응답 타입입니다.

export type RagSearchMode = "focused_answer" | "issue_spotting";

export type LegalDocumentType =
  | "statute"
  | "case"
  | "interpretation"
  | "admin_appeal"
  | "user_file"
  | "memo";

export type RagSearchFilters = {
  document_type?: LegalDocumentType;
  document_types?: LegalDocumentType[];
};

export type RagSearchRequest = {
  query: string;
  search_mode: RagSearchMode;
  top_k?: number;
  score_threshold?: number;
  max_chunks_per_document?: number;
  embedding_profile_id?: number;
  filters?: RagSearchFilters;
};

export type RagSearchItem = {
  retrieval_id: number | null;
  chunk_embedding_id: number;
  chunk_id: number;
  document_id: number;
  rank: number;
  score: number;
  title: string;
  source_url: string | null;
  heading: string | null;
  content: string;
  metadata: Record<string, unknown>;
};

export type RagSearchResponse = {
  run_id: number;
  query: string;
  search_mode: RagSearchMode;
  top_k: number;
  score_threshold: number | null;
  max_chunks_per_document: number | null;
  embedding_profile_id: number;
  embedding_provider: string;
  embedding_model_name: string;
  embedding_dimensions: number;
  items: RagSearchItem[];
};

export type AgentToolCall = {
  step_index: number;
  tool_name: string;
  status: string;
};

export type AgentCitation = {
  chunk_id: number | null;
  title: string | null;
  source_url: string | null;
  heading: string | null;
  rank: number | null;
};

export type AgentRunStatus = "completed" | "failed";

export type AnswerDraftRequest = {
  facts: string;
  question: string;
  tone?: string;
  search_mode: RagSearchMode;
  top_k?: number;
  score_threshold?: number;
  max_chunks_per_document?: number;
};

export type AnswerDraftResponse = {
  run_id: number;
  status: AgentRunStatus;
  agent_provider: string | null;
  agent_model_name: string | null;
  draft: string | null;
  citations: AgentCitation[];
  disclaimer: string | null;
  tool_calls: AgentToolCall[];
};

export type FullAnalysisRequest = {
  facts: string;
  question: string;
  tone?: string;
  search_mode: RagSearchMode;
  top_k?: number;
  score_threshold?: number;
  max_chunks_per_document?: number;
};

export type FullAnalysisResponse = {
  search: RagSearchResponse;
  issues: DisputeIssuesResponse;
  draft: AnswerDraftResponse;
};

export type DisputeIssuesRequest = {
  facts: string;
  question: string;
  search_mode: RagSearchMode;
  top_k?: number;
  score_threshold?: number;
  max_chunks_per_document?: number;
};

export type DisputeIssuesResponse = {
  run_id: number;
  status: AgentRunStatus;
  agent_provider: string | null;
  agent_model_name: string | null;
  issues_text: string | null;
  citations: AgentCitation[];
  disclaimer: string | null;
  tool_calls: AgentToolCall[];
};
